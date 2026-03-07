#!/usr/bin/env python3
"""
human_validation_scaffold.py — stratified sample + annotation CSV for human validation.

selects 30 articles stratified by:
- language (English vs non-English)
- cluster assignment (proportional to cluster size)
- confidence level (oversamples contested articles)

outputs:
- results/human_validation_sample.csv — annotation spreadsheet
- results/human_validation_instructions.md — annotator guide

usage:
  python3 scripts/human_validation_scaffold.py
  python3 scripts/human_validation_scaffold.py --event-id 3 --n 40
"""

import argparse
import csv
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import (get_session, Event, Article, Analysis, LLMCouncilVerdict,
                Cluster, ClusterMembership)


def get_cluster_for_article(session, article_id, event_id):
    """return the cluster label for an article (from most recent run_id)."""
    memberships = (
        session.query(ClusterMembership, Cluster)
        .join(Cluster, ClusterMembership.cluster_id == Cluster.id)
        .filter(ClusterMembership.article_id == article_id)
        .filter(Cluster.event_id == event_id)
        .order_by(Cluster.created_at.desc())
        .all()
    )
    if memberships:
        return memberships[0][1].label
    return "unclustered"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, default=2)
    parser.add_argument("--n", type=int, default=30, help="sample size")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    session = get_session()

    event = session.query(Event).get(args.event_id)
    if not event:
        print(f"event {args.event_id} not found")
        sys.exit(1)
    print(f"event: {event.title}")

    # load all articles with analyses and council verdicts
    articles = session.query(Article).filter_by(event_id=args.event_id).all()
    print(f"total articles: {len(articles)}")

    # build article metadata
    records = []
    for art in articles:
        analysis = session.query(Analysis).filter_by(article_id=art.id).first()
        verdict = session.query(LLMCouncilVerdict).filter_by(article_id=art.id).first()
        cluster_label = get_cluster_for_article(session, art.id, args.event_id)

        if not analysis:
            continue

        is_english = (art.original_language or "").lower() in ("english", "eng", "en")
        records.append({
            "article_id": art.id,
            "url": art.url,
            "title": art.title or "",
            "language": art.original_language or "Unknown",
            "is_english": is_english,
            "cluster_label": cluster_label,
            "confidence_level": verdict.confidence_level if verdict else "no_verdict",
            "primary_frame": analysis.primary_frame or "",
            "consensus_frame": verdict.consensus_frame if verdict else "",
            "models_agree": verdict.models_agree if verdict else None,
        })

    print(f"articles with analyses: {len(records)}")

    # stratified sampling
    # strata: language group (English/non-English) × confidence level
    strata = defaultdict(list)
    for r in records:
        lang_group = "english" if r["is_english"] else "non_english"
        conf = r["confidence_level"]
        strata[f"{lang_group}_{conf}"].append(r)

    print(f"\nstrata:")
    for stratum, items in sorted(strata.items()):
        print(f"  {stratum}: {len(items)}")

    # allocation: oversample contested articles (they're most informative)
    # target: ~40% contested, ~30% medium, ~20% high/no_verdict, ~10% unclustered
    n = args.n
    sample = []

    # first, get contested articles (most valuable for validation)
    contested = [r for r in records if r["confidence_level"] == "contested"]
    n_contested = min(int(n * 0.4), len(contested))
    sample.extend(random.sample(contested, n_contested))
    sampled_ids = {r["article_id"] for r in sample}

    # then medium confidence
    medium = [r for r in records if r["confidence_level"] == "medium" and r["article_id"] not in sampled_ids]
    n_medium = min(int(n * 0.3), len(medium))
    sample.extend(random.sample(medium, n_medium))
    sampled_ids.update(r["article_id"] for r in sample)

    # fill remaining from other strata
    remaining = [r for r in records if r["article_id"] not in sampled_ids]
    n_remaining = n - len(sample)
    if n_remaining > 0 and remaining:
        sample.extend(random.sample(remaining, min(n_remaining, len(remaining))))

    # ensure non-English representation (at least 30%)
    non_english = [r for r in sample if not r["is_english"]]
    if len(non_english) < n * 0.3:
        # swap some English articles for non-English
        ne_pool = [r for r in records if not r["is_english"] and r["article_id"] not in sampled_ids]
        en_in_sample = [r for r in sample if r["is_english"]]
        n_swap = min(int(n * 0.3) - len(non_english), len(ne_pool), len(en_in_sample))
        for i in range(n_swap):
            sample.remove(en_in_sample[-(i+1)])
            sample.append(ne_pool[i])

    print(f"\nfinal sample: {len(sample)} articles")
    print(f"  english: {sum(1 for r in sample if r['is_english'])}")
    print(f"  non-english: {sum(1 for r in sample if not r['is_english'])}")
    print(f"  contested: {sum(1 for r in sample if r['confidence_level'] == 'contested')}")
    print(f"  medium: {sum(1 for r in sample if r['confidence_level'] == 'medium')}")

    # cluster distribution in sample
    cluster_counts = defaultdict(int)
    for r in sample:
        cluster_counts[r["cluster_label"]] += 1
    print(f"\n  cluster distribution:")
    for c, count in sorted(cluster_counts.items(), key=lambda x: -x[1]):
        print(f"    {c[:50]}: {count}")

    # write CSV
    os.makedirs("results", exist_ok=True)
    csv_path = f"results/human_validation_sample_{args.event_id}.csv"
    fieldnames = [
        "article_id", "url", "title", "language", "cluster_label",
        "confidence_level", "llm_primary_frame", "llm_consensus_frame",
        # annotation columns (to be filled by human)
        "human_primary_frame", "human_agrees_with_llm", "human_cluster_label",
        "human_notes",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(sample, key=lambda x: x["article_id"]):
            writer.writerow({
                "article_id": r["article_id"],
                "url": r["url"],
                "title": r["title"][:100],
                "language": r["language"],
                "cluster_label": r["cluster_label"][:80],
                "confidence_level": r["confidence_level"],
                "llm_primary_frame": r["primary_frame"][:200],
                "llm_consensus_frame": r["consensus_frame"][:200] if r["consensus_frame"] else "",
                "human_primary_frame": "",
                "human_agrees_with_llm": "",
                "human_cluster_label": "",
                "human_notes": "",
            })
    print(f"\nsaved: {csv_path}")

    # write instructions
    instructions_path = f"results/human_validation_instructions_{args.event_id}.md"
    with open(instructions_path, "w", encoding="utf-8") as f:
        f.write(f"""# human validation instructions

## event: {event.title}

## overview

you have been given {len(sample)} articles sampled from a corpus of {len(records)} articles about {event.prompt_context or event.title}. the articles were analyzed by an LLM council (3 models: Qwen-32B, Gemma-27B, Mistral-24B) for their epistemic framing.

your task: independently assess each article's framing and compare to the LLM's assessment.

## what to annotate

for each article in the CSV:

1. **read the article** at the provided URL (or use cached text in cache/ directory, keyed by MD5 of URL)
2. **human_primary_frame**: in 1-2 sentences, describe how this article frames the event. use the article's own vocabulary, not political science labels.
3. **human_agrees_with_llm**: one of:
   - `agree` — the LLM framing captures the article's essential position
   - `partial` — the LLM framing is directionally correct but misses important nuance
   - `disagree` — the LLM framing mischaracterizes this article
   - `unclear` — the article is too ambiguous to assess
4. **human_cluster_label**: which cluster (from the cluster_label column) does this article best fit? or write `new: [description]` if none fit.
5. **human_notes**: any observations — e.g., "LLM missed the ironic tone", "article is actually about X not Y", etc.

## stratification notes

this sample is NOT random. it oversamples:
- **contested** articles (where the 3 models disagreed most) — these are the hardest cases
- **non-english** articles — to check whether translation artifacts affect framing
- articles from underrepresented clusters

## important

- do NOT look at the LLM framing before forming your own assessment. read the article first, write human_primary_frame, THEN compare.
- if the article URL is dead, note "URL dead" in human_notes and skip.
- for non-English articles you don't speak, note "cannot assess — language barrier" in human_notes.

## cluster definitions (for reference)

{_format_clusters(session, args.event_id)}
""")
    print(f"saved: {instructions_path}")
    session.close()


def _format_clusters(session, event_id):
    """format cluster definitions for annotator reference."""
    clusters = (
        session.query(Cluster)
        .filter_by(event_id=event_id)
        .order_by(Cluster.created_at.desc())
        .all()
    )
    # deduplicate by label (use most recent)
    seen = set()
    lines = []
    for c in clusters:
        if c.label not in seen and not c.label.startswith("Singleton"):
            seen.add(c.label)
            desc = c.description or "(no description)"
            lines.append(f"- **{c.label}**: {desc}")
    return "\n".join(lines) if lines else "(no clusters found)"


if __name__ == "__main__":
    main()
