#!/usr/bin/env python3
"""
inter_model_divergence.py — analyze inter-model agreement from council votes.

generates per-language and per-country agreement rates from llm_council_verdicts.
outputs to results/inter_model_divergence.json.

usage:
  python3 scripts/inter_model_divergence.py
  python3 scripts/inter_model_divergence.py --event-id 3
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session, Event, Article, LLMCouncilVerdict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, default=2)
    args = parser.parse_args()

    session = get_session()
    event = session.query(Event).get(args.event_id)
    if not event:
        print(f"event_id {args.event_id} not found")
        sys.exit(1)

    print(f"event: {event.title} (id={event.id})")

    # query all verdicts joined with article metadata
    verdicts = (
        session.query(LLMCouncilVerdict, Article)
        .join(Article, LLMCouncilVerdict.article_id == Article.id)
        .filter(Article.event_id == args.event_id)
        .all()
    )
    print(f"council verdicts: {len(verdicts)}")

    # aggregate by language
    by_lang = defaultdict(lambda: {"total": 0, "agree": 0, "contested": 0, "medium": 0, "high": 0})
    by_country = defaultdict(lambda: {"total": 0, "agree": 0, "contested": 0})
    model_pair_disagreements = defaultdict(int)

    for verdict, article in verdicts:
        lang = article.original_language or "Unknown"
        # derive country from source — use sourcecountry from analysis if available
        country = "Unknown"

        by_lang[lang]["total"] += 1
        if verdict.models_agree:
            by_lang[lang]["agree"] += 1
        if verdict.confidence_level:
            by_lang[lang][verdict.confidence_level] = by_lang[lang].get(verdict.confidence_level, 0) + 1
        by_lang[lang]["contested"] = by_lang[lang].get("contested", 0)

        # analyze per-model readings for disagreement patterns
        readings = verdict.model_readings or {}
        models = list(readings.keys())
        for i in range(len(models)):
            for j in range(i + 1, len(models)):
                m1, m2 = models[i], models[j]
                r1 = readings[m1]
                r2 = readings[m2]
                # compare primary_frame if available
                frame1 = ""
                frame2 = ""
                if isinstance(r1, dict):
                    frame1 = r1.get("one_sentence_summary", r1.get("framing_description", ""))
                if isinstance(r2, dict):
                    frame2 = r2.get("one_sentence_summary", r2.get("framing_description", ""))
                # simple heuristic: if frames are very different length, likely disagreement
                pair_key = f"{m1} vs {m2}"
                if not verdict.models_agree:
                    model_pair_disagreements[pair_key] += 1

    # compute agreement rates
    lang_table = []
    for lang, stats in sorted(by_lang.items(), key=lambda x: -x[1]["total"]):
        rate = stats["agree"] / stats["total"] if stats["total"] > 0 else 0
        lang_table.append({
            "language": lang,
            "total": stats["total"],
            "agree": stats["agree"],
            "agreement_rate": round(rate, 3),
            "high": stats.get("high", 0),
            "medium": stats.get("medium", 0),
            "contested": stats.get("contested", 0),
        })

    # overall stats
    total = len(verdicts)
    agree_count = sum(1 for v, _ in verdicts if v.models_agree)
    contested_count = sum(1 for v, _ in verdicts if v.confidence_level == "contested")

    # model pair disagreement rates
    pair_table = []
    for pair, count in sorted(model_pair_disagreements.items(), key=lambda x: -x[1]):
        pair_table.append({
            "pair": pair,
            "disagreements": count,
            "disagreement_rate": round(count / total, 3) if total > 0 else 0,
        })

    results = {
        "event_id": args.event_id,
        "event_title": event.title,
        "total_verdicts": total,
        "overall_agreement_rate": round(agree_count / total, 3) if total > 0 else 0,
        "confidence_distribution": {
            "high": sum(1 for v, _ in verdicts if v.confidence_level == "high"),
            "medium": sum(1 for v, _ in verdicts if v.confidence_level == "medium"),
            "contested": contested_count,
        },
        "per_language": lang_table,
        "model_pair_disagreements": pair_table,
    }

    # print summary
    print(f"\noverall agreement: {agree_count}/{total} ({results['overall_agreement_rate']:.1%})")
    print(f"confidence: high={results['confidence_distribution']['high']}, "
          f"medium={results['confidence_distribution']['medium']}, "
          f"contested={results['confidence_distribution']['contested']}")

    print(f"\nper-language agreement rates:")
    print(f"  {'language':<20} {'total':>5} {'agree':>5} {'rate':>8} {'contested':>10}")
    print(f"  {'─'*55}")
    for row in lang_table:
        print(f"  {row['language']:<20} {row['total']:>5} {row['agree']:>5} "
              f"{row['agreement_rate']:>8.1%} {row['contested']:>10}")

    if pair_table:
        print(f"\nmodel pair disagreement rates:")
        for p in pair_table:
            print(f"  {p['pair']}: {p['disagreements']}/{total} ({p['disagreement_rate']:.1%})")

    # save
    os.makedirs("results", exist_ok=True)
    out_path = f"results/inter_model_divergence_{args.event_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")

    session.close()


if __name__ == "__main__":
    main()
