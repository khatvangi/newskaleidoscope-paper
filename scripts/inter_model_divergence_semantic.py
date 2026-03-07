#!/usr/bin/env python3
"""
inter_model_divergence_semantic.py — semantic similarity-based inter-model agreement.

replaces exact string match with cosine similarity on sentence embeddings.
for each article, embeds all 3 model framing descriptions, computes pairwise
cosine similarity, thresholds at 0.75 for "agreement."

outputs:
- results/inter_model_divergence_semantic_{event_id}.json
- similarity distribution histogram data

usage:
  python3 scripts/inter_model_divergence_semantic.py
  python3 scripts/inter_model_divergence_semantic.py --event-id 3
  python3 scripts/inter_model_divergence_semantic.py --threshold 0.80
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session, Event, Article, LLMCouncilVerdict

SIMILARITY_THRESHOLD = 0.75
MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"


def extract_frame_text(reading):
    """extract the primary framing text from a model reading."""
    if not isinstance(reading, dict):
        return str(reading) if reading else ""
    # prefer primary_frame, fall back to one_sentence_summary, then framing_description
    return (reading.get("primary_frame", "")
            or reading.get("one_sentence_summary", "")
            or reading.get("framing_description", "")
            or "")


def cosine_similarity(a, b):
    """cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, default=2)
    parser.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD)
    args = parser.parse_args()

    threshold = args.threshold

    session = get_session()
    event = session.query(Event).get(args.event_id)
    if not event:
        print(f"event_id {args.event_id} not found")
        sys.exit(1)

    print(f"event: {event.title} (id={event.id})")
    print(f"similarity threshold: {threshold}")

    # load sentence transformer
    print(f"loading {MODEL_NAME}...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print("  model loaded")

    # query all verdicts
    verdicts = (
        session.query(LLMCouncilVerdict, Article)
        .join(Article, LLMCouncilVerdict.article_id == Article.id)
        .filter(Article.event_id == args.event_id)
        .all()
    )
    print(f"council verdicts: {len(verdicts)}")

    # collect all framing texts for batch embedding
    all_texts = []
    text_map = []  # (verdict_idx, model_name) for each text

    for v_idx, (verdict, article) in enumerate(verdicts):
        readings = verdict.model_readings or {}
        for model_name, reading in readings.items():
            frame = extract_frame_text(reading)
            if frame.strip():
                all_texts.append(frame)
                text_map.append((v_idx, model_name))

    print(f"embedding {len(all_texts)} framing descriptions...")
    embeddings = model.encode(all_texts, show_progress_bar=True, batch_size=64)
    print("  embeddings computed")

    # organize embeddings by verdict index
    verdict_embeddings = defaultdict(dict)  # v_idx -> {model_name: embedding}
    for i, (v_idx, model_name) in enumerate(text_map):
        verdict_embeddings[v_idx][model_name] = embeddings[i]

    # compute pairwise similarity per article
    all_similarities = []  # all pairwise similarities across all articles
    article_results = []
    by_lang = defaultdict(lambda: {
        "total": 0, "high": 0, "medium": 0, "contested": 0,
        "similarities": [],
    })

    model_pair_sims = defaultdict(list)  # "modelA vs modelB" -> [sim, sim, ...]

    for v_idx, (verdict, article) in enumerate(verdicts):
        lang = article.original_language or "Unknown"
        embs = verdict_embeddings.get(v_idx, {})
        model_names = sorted(embs.keys())

        if len(model_names) < 2:
            continue

        # pairwise cosine similarities
        pair_sims = []
        for i in range(len(model_names)):
            for j in range(i + 1, len(model_names)):
                m1, m2 = model_names[i], model_names[j]
                sim = cosine_similarity(embs[m1], embs[m2])
                pair_sims.append(sim)
                all_similarities.append(sim)
                pair_key = f"{m1} vs {m2}"
                model_pair_sims[pair_key].append(sim)

        mean_sim = np.mean(pair_sims) if pair_sims else 0.0
        min_sim = min(pair_sims) if pair_sims else 0.0

        # classify: all pairs >= threshold = high, 2/3 >= threshold = medium, else contested
        n_above = sum(1 for s in pair_sims if s >= threshold)
        n_pairs = len(pair_sims)

        if n_above == n_pairs:
            confidence = "high"
        elif n_above >= n_pairs * 0.5:
            confidence = "medium"
        else:
            confidence = "contested"

        by_lang[lang]["total"] += 1
        by_lang[lang][confidence] += 1
        by_lang[lang]["similarities"].extend(pair_sims)

        article_results.append({
            "article_id": article.id,
            "language": lang,
            "mean_similarity": round(mean_sim, 4),
            "min_similarity": round(min_sim, 4),
            "confidence": confidence,
            "n_pairs_above_threshold": n_above,
        })

    # overall stats
    total = len(article_results)
    high_count = sum(1 for r in article_results if r["confidence"] == "high")
    medium_count = sum(1 for r in article_results if r["confidence"] == "medium")
    contested_count = sum(1 for r in article_results if r["confidence"] == "contested")

    # similarity distribution histogram (10 bins from 0 to 1)
    hist_bins = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    hist_counts, _ = np.histogram(all_similarities, bins=hist_bins)
    histogram = {f"{hist_bins[i]:.1f}-{hist_bins[i+1]:.1f}": int(hist_counts[i])
                 for i in range(len(hist_counts))}

    # per-language table
    lang_table = []
    for lang, stats in sorted(by_lang.items(), key=lambda x: -x[1]["total"]):
        mean_sim = np.mean(stats["similarities"]) if stats["similarities"] else 0.0
        lang_table.append({
            "language": lang,
            "total": stats["total"],
            "high": stats["high"],
            "medium": stats["medium"],
            "contested": stats["contested"],
            "agreement_rate": round((stats["high"] + stats["medium"]) / stats["total"], 3) if stats["total"] > 0 else 0,
            "mean_similarity": round(float(mean_sim), 4),
        })

    # model pair stats
    pair_table = []
    for pair, sims in sorted(model_pair_sims.items()):
        pair_table.append({
            "pair": pair,
            "mean_similarity": round(float(np.mean(sims)), 4),
            "median_similarity": round(float(np.median(sims)), 4),
            "std": round(float(np.std(sims)), 4),
            "pct_above_threshold": round(sum(1 for s in sims if s >= threshold) / len(sims), 3),
        })

    # find lowest-agreement language
    lang_by_agreement = sorted(lang_table, key=lambda x: x["mean_similarity"])
    lowest_lang = lang_by_agreement[0] if lang_by_agreement else None

    results = {
        "event_id": args.event_id,
        "event_title": event.title,
        "method": f"cosine similarity on {MODEL_NAME}, threshold={threshold}",
        "total_articles": total,
        "confidence_distribution": {
            "high": high_count,
            "high_pct": round(high_count / total, 3) if total else 0,
            "medium": medium_count,
            "medium_pct": round(medium_count / total, 3) if total else 0,
            "contested": contested_count,
            "contested_pct": round(contested_count / total, 3) if total else 0,
        },
        "similarity_stats": {
            "mean": round(float(np.mean(all_similarities)), 4),
            "median": round(float(np.median(all_similarities)), 4),
            "std": round(float(np.std(all_similarities)), 4),
            "min": round(float(np.min(all_similarities)), 4),
            "max": round(float(np.max(all_similarities)), 4),
        },
        "similarity_histogram": histogram,
        "per_language": lang_table,
        "model_pair_stats": pair_table,
        "lowest_agreement_language": lowest_lang["language"] if lowest_lang else None,
        "lowest_agreement_rate": lowest_lang["mean_similarity"] if lowest_lang else None,
        "per_article": article_results,
    }

    # print summary
    print(f"\n{'='*60}")
    print(f"SEMANTIC INTER-MODEL DIVERGENCE")
    print(f"  method: cosine similarity on {MODEL_NAME}")
    print(f"  threshold: {threshold}")
    print(f"  articles: {total}")
    print(f"\noverall similarity: mean={results['similarity_stats']['mean']:.3f}, "
          f"median={results['similarity_stats']['median']:.3f}, "
          f"std={results['similarity_stats']['std']:.3f}")

    print(f"\nconfidence distribution:")
    cd = results["confidence_distribution"]
    print(f"  HIGH     (all 3 agree):   {cd['high']:>4} ({cd['high_pct']:.1%})")
    print(f"  MEDIUM   (2 of 3 agree):  {cd['medium']:>4} ({cd['medium_pct']:.1%})")
    print(f"  CONTESTED (genuine split): {cd['contested']:>4} ({cd['contested_pct']:.1%})")

    print(f"\nsimilarity histogram:")
    for bin_label, count in histogram.items():
        bar = "█" * (count // 2)
        print(f"  {bin_label}: {count:>4} {bar}")

    print(f"\nper-language agreement (mean cosine similarity):")
    print(f"  {'language':<20} {'n':>4} {'mean_sim':>8} {'high':>5} {'med':>5} {'cont':>5} {'agree%':>7}")
    print(f"  {'─'*60}")
    for row in lang_table:
        print(f"  {row['language']:<20} {row['total']:>4} {row['mean_similarity']:>8.3f} "
              f"{row['high']:>5} {row['medium']:>5} {row['contested']:>5} "
              f"{row['agreement_rate']:>7.1%}")

    print(f"\nmodel pair mean similarities:")
    for p in pair_table:
        print(f"  {p['pair']}: mean={p['mean_similarity']:.3f}, "
              f"median={p['median_similarity']:.3f}, "
              f">{threshold}: {p['pct_above_threshold']:.1%}")

    if lowest_lang:
        print(f"\nlowest agreement: {lowest_lang['language']} "
              f"(mean sim={lowest_lang['mean_similarity']:.3f})")

    print(f"{'='*60}")

    # save
    os.makedirs("results", exist_ok=True)
    out_path = f"results/inter_model_divergence_semantic_{args.event_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")

    session.close()


if __name__ == "__main__":
    main()
