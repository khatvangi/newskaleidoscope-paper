#!/usr/bin/env python3
"""
recluster_chunked.py — hierarchical pass-2 clustering for large corpora.

Purpose:
- Reuse existing translated/analyzed data from DB.
- Avoid context-limit failures in pass2_cluster by chunking and hierarchical reduction.
- Write new cluster rows with a fresh run_id and regenerate absence artifact.

This does NOT rerun translation or council.
"""

import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session, Event, Article
from pipeline import (
    find_best_model,
    pass2_cluster,
    generate_absence_report,
    load_existing_results_from_db,
    write_clusters_to_db,
    write_json_artifact,
)


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def article_summary_from_result(result):
    analysis = result.get("analysis", {})
    desc = analysis.get("one_sentence_summary", "") or analysis.get("framing_description", "")
    desc = (desc or "").replace("\n", " ").strip()
    if len(desc) > 240:
        desc = desc[:240]
    return desc or "No summary available."


def top_country_for_indices(results, indices):
    countries = [results[i].get("sourcecountry", "unknown") for i in indices if 0 <= i < len(results)]
    if not countries:
        return "unknown"
    return Counter(countries).most_common(1)[0][0]


def build_pseudo_results(items, results):
    pseudo = []
    for i, item in enumerate(items):
        idxs = item["member_article_indices"]
        pseudo.append(
            {
                "url": f"micro://{i}",
                "domain": "microcluster",
                "sourcecountry": top_country_for_indices(results, idxs),
                "analysis": {
                    "one_sentence_summary": item["summary"][:220],
                    "framing_description": item["summary"][:220],
                },
            }
        )
    return pseudo


def merge_items_from_cluster_output(cluster_data, source_items):
    merged = []
    covered = set()

    for c in cluster_data.get("emergent_clusters", []):
        idxs = [i for i in c.get("member_indices", []) if 0 <= i < len(source_items)]
        if not idxs:
            continue
        covered.update(idxs)
        member_article_indices = []
        for i in idxs:
            member_article_indices.extend(source_items[i]["member_article_indices"])
        member_article_indices = sorted(set(member_article_indices))
        name = (c.get("cluster_name") or "Emergent cluster").strip()
        desc = (c.get("description") or "").strip()
        summary = f"{name}: {desc}".strip(": ").strip()
        if len(summary) > 240:
            summary = summary[:240]
        merged.append(
            {
                "name": name,
                "description": desc,
                "summary": summary or name,
                "member_article_indices": member_article_indices,
            }
        )

    for s in cluster_data.get("singletons", []):
        idx = s.get("index", -1)
        if 0 <= idx < len(source_items):
            covered.add(idx)
            base = source_items[idx]
            reason = (s.get("why_unique") or "").strip()
            summary = base["summary"]
            if reason:
                summary = f"{summary} | {reason}"
            if len(summary) > 240:
                summary = summary[:240]
            merged.append(
                {
                    "name": base.get("name", "Singleton"),
                    "description": reason or base.get("description", ""),
                    "summary": summary,
                    "member_article_indices": sorted(set(base["member_article_indices"])),
                }
            )

    # Preserve any source item not referenced by model output.
    for idx, item in enumerate(source_items):
        if idx not in covered:
            merged.append(
                {
                    "name": item.get("name", "Carryover"),
                    "description": item.get("description", ""),
                    "summary": item.get("summary", "")[:240],
                    "member_article_indices": sorted(set(item["member_article_indices"])),
                }
            )

    return merged


def cluster_items_recursive(model, items, results, event_context, min_size, tag, depth=0):
    pseudo_results = build_pseudo_results(items, results)
    cluster_data = pass2_cluster(model, pseudo_results, event_context=event_context)
    if cluster_data and not cluster_data.get("raw_response"):
        return merge_items_from_cluster_output(cluster_data, items)

    if len(items) <= min_size:
        print(f"[warn] {tag} depth={depth}: pass2 failed, keeping {len(items)} items as-is")
        return items

    mid = len(items) // 2
    left = cluster_items_recursive(
        model, items[:mid], results, event_context, min_size, tag=f"{tag}L", depth=depth + 1
    )
    right = cluster_items_recursive(
        model, items[mid:], results, event_context, min_size, tag=f"{tag}R", depth=depth + 1
    )
    return left + right


def items_to_cluster_data(final_items, results, meta_observation):
    emergent_clusters = []
    singletons = []
    seen_names = Counter()

    for item in final_items:
        idxs = sorted(set(item["member_article_indices"]))
        if not idxs:
            continue
        if len(idxs) == 1:
            singletons.append(
                {"index": idxs[0], "why_unique": (item.get("description") or item.get("summary") or "")[:240]}
            )
            continue

        name = (item.get("name") or "Emergent cluster").strip()
        seen_names[name] += 1
        if seen_names[name] > 1:
            name = f"{name} ({seen_names[name]})"

        emergent_clusters.append(
            {
                "cluster_name": name,
                "description": (item.get("description") or item.get("summary") or "")[:400],
                "member_indices": idxs,
                "geographic_pattern": f"top country: {top_country_for_indices(results, idxs)}",
                "maps_to_conventional_category": None,
            }
        )

    return {
        "emergent_clusters": emergent_clusters,
        "singletons": singletons,
        "meta_observation": meta_observation
        or "Hierarchical chunked clustering was used due to context limits in single-pass clustering.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, default=4)
    parser.add_argument("--chunk-size", type=int, default=80)
    parser.add_argument("--min-chunk-size", type=int, default=20)
    parser.add_argument("--reduce-chunk-size", type=int, default=60)
    parser.add_argument("--final-limit", type=int, default=120)
    parser.add_argument("--max-levels", type=int, default=4)
    parser.add_argument("--run-id", type=str, default=None)
    args = parser.parse_args()

    run_id = args.run_id or f"chunked_recluster_{time.strftime('%Y%m%d_%H%M%S')}"
    method = "llm_pass2_chunked_hierarchical"
    print(f"run_id={run_id}")
    print(f"method={method}")

    session = get_session()
    event = session.get(Event, args.event_id)
    if not event:
        print(f"event_id {args.event_id} not found")
        sys.exit(1)

    event_context = event.prompt_context or event.title or "major geopolitical event"
    absence_examples = event.absence_examples or "underrepresented domestic media, marginalized communities"
    print(f"event={event.id} title={event.title}")

    results_map = load_existing_results_from_db(session, event.id)
    results = list(results_map.values())
    print(f"results={len(results)}")
    if len(results) < 3:
        print("not enough analyzed results for clustering")
        sys.exit(1)

    model = find_best_model()
    print(f"model={model}")

    # Atomic item = one article summary.
    atomic = []
    for i, r in enumerate(results):
        s = article_summary_from_result(r)
        atomic.append(
            {
                "name": f"Article {i}",
                "description": s,
                "summary": s,
                "member_article_indices": [i],
            }
        )

    # Stage 1: cluster each article chunk.
    stage_items = []
    for ci, part in enumerate(chunked(atomic, args.chunk_size), start=1):
        print(f"stage1 chunk {ci}: input={len(part)}")
        reduced = cluster_items_recursive(
            model,
            part,
            results,
            event_context=event_context,
            min_size=args.min_chunk_size,
            tag=f"s1c{ci}",
        )
        print(f"stage1 chunk {ci}: output={len(reduced)}")
        stage_items.extend(reduced)

    current = stage_items
    print(f"after stage1 items={len(current)}")

    # Optional reduction passes until manageable final size.
    level = 2
    while len(current) > args.final_limit and level <= args.max_levels:
        print(f"level {level}: reducing {len(current)} items")
        nxt = []
        for ci, part in enumerate(chunked(current, args.reduce_chunk_size), start=1):
            reduced = cluster_items_recursive(
                model,
                part,
                results,
                event_context=event_context,
                min_size=max(8, args.min_chunk_size // 2),
                tag=f"s{level}c{ci}",
            )
            nxt.extend(reduced)
        current = nxt
        print(f"level {level}: output items={len(current)}")
        level += 1

    # Final merge attempt on reduced set.
    print(f"final merge input items={len(current)}")
    final_meta = ""
    final_try = pass2_cluster(model, build_pseudo_results(current, results), event_context=event_context)
    if final_try and not final_try.get("raw_response"):
        final_items = merge_items_from_cluster_output(final_try, current)
        final_meta = final_try.get("meta_observation", "")
        print(f"final merge success: {len(final_items)} items")
    else:
        print("final merge fallback: using reduced items directly")
        final_items = current

    cluster_data = items_to_cluster_data(final_items, results, meta_observation=final_meta)
    print(
        f"cluster_data: clusters={len(cluster_data.get('emergent_clusters', []))} "
        f"singletons={len(cluster_data.get('singletons', []))}"
    )

    # DB writes (additive only).
    url_to_article_id = {a.url: a.id for a in session.query(Article).filter_by(event_id=event.id).all()}
    c_count, m_count = write_clusters_to_db(
        session,
        event.id,
        cluster_data,
        results,
        url_to_article_id,
        run_id=run_id,
        method=method,
    )
    session.commit()
    print(f"db writes: clusters={c_count} memberships={m_count}")

    cluster_artifact = write_json_artifact(
        "analysis/emergent_clusters.json", cluster_data, run_id=run_id, event_id=event.id, archive_existing=True
    )
    print(f"cluster artifact: {cluster_artifact}")

    absence_data = generate_absence_report(
        model,
        results,
        cluster_data,
        event_context=event_context,
        absence_examples=absence_examples,
    )
    if absence_data and not absence_data.get("raw_response"):
        absence_artifact = write_json_artifact(
            "analysis/absence_report.json",
            absence_data,
            run_id=run_id,
            event_id=event.id,
            archive_existing=True,
        )
        print(f"absence artifact: {absence_artifact}")
    else:
        print("absence generation failed or returned raw response")
        print(absence_data)

    session.close()
    print(f"done run_id={run_id}")


if __name__ == "__main__":
    main()
