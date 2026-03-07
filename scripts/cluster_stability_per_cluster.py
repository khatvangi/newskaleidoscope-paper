#!/usr/bin/env python3
"""
cluster_stability_per_cluster.py — per-cluster stability across runs.

for each cluster in run A, compute what fraction of its member articles
appear in the same cluster in run B. flags clusters below 0.5 as unstable.

specifically checks the "China Realpolitik" cluster.

usage:
  python3 scripts/cluster_stability_per_cluster.py
  python3 scripts/cluster_stability_per_cluster.py --event-id 3
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session, Event, Cluster, ClusterMembership


def load_cluster_runs_detailed(session, event_id):
    """load cluster runs with full cluster->articles mapping."""
    clusters = session.query(Cluster).filter_by(event_id=event_id).all()

    # group by run_id: {run_id: {cluster_label: set(article_ids)}}
    runs = defaultdict(lambda: defaultdict(set))
    # also: {run_id: {article_id: cluster_label}}
    article_to_cluster = defaultdict(dict)

    for cluster in clusters:
        run_id = cluster.run_id or "legacy"
        for membership in cluster.memberships:
            runs[run_id][cluster.label].add(membership.article_id)
            if membership.article_id not in article_to_cluster[run_id]:
                article_to_cluster[run_id][membership.article_id] = cluster.label

    return dict(runs), dict(article_to_cluster)


def compute_per_cluster_stability(runs_detailed, article_to_cluster, run_a, run_b):
    """for each cluster in run_a, compute stability against run_b."""
    results = []
    common_articles = set(article_to_cluster[run_a].keys()) & set(article_to_cluster[run_b].keys())

    for cluster_label, members_a in sorted(runs_detailed[run_a].items(), key=lambda x: -len(x[1])):
        # only consider members that exist in both runs
        members_in_common = members_a & common_articles
        if not members_in_common:
            continue

        # where do these articles end up in run_b?
        destinations = defaultdict(int)
        for art_id in members_in_common:
            dest = article_to_cluster[run_b].get(art_id, "not_assigned")
            destinations[dest] += 1

        # stability = fraction that land in the single most common destination
        most_common_dest = max(destinations, key=destinations.get)
        most_common_count = destinations[most_common_dest]
        stability = most_common_count / len(members_in_common) if members_in_common else 0.0

        is_singleton = cluster_label.startswith("Singleton")

        results.append({
            "cluster": cluster_label,
            "members_total": len(members_a),
            "members_in_common": len(members_in_common),
            "stability": round(stability, 3),
            "most_common_destination": most_common_dest[:80],
            "destination_count": most_common_count,
            "all_destinations": {k[:60]: v for k, v in sorted(destinations.items(), key=lambda x: -x[1])},
            "is_singleton": is_singleton,
            "stable": stability >= 0.5,
        })

    return results


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

    runs_detailed, article_to_cluster = load_cluster_runs_detailed(session, args.event_id)
    run_ids = sorted(runs_detailed.keys())
    print(f"found {len(run_ids)} runs: {run_ids}")

    # identify the two LLM-based runs with most common articles for comparison
    # (skip embedding-based runs for LLM-to-LLM stability)
    llm_runs = [r for r in run_ids if "embedding" not in r]
    print(f"LLM-based runs: {llm_runs}")

    if len(llm_runs) < 2:
        print("need at least 2 LLM-based runs for per-cluster stability")
        sys.exit(1)

    # find pair with most common articles
    best_pair = None
    best_common = 0
    for i in range(len(llm_runs)):
        for j in range(i + 1, len(llm_runs)):
            common = len(set(article_to_cluster[llm_runs[i]].keys()) &
                        set(article_to_cluster[llm_runs[j]].keys()))
            if common > best_common:
                best_common = common
                best_pair = (llm_runs[i], llm_runs[j])

    run_a, run_b = best_pair
    print(f"\ncomparing: {run_a} vs {run_b} ({best_common} common articles)")

    # per-cluster stability for run_a against run_b
    print(f"\nper-cluster stability (run A = {run_a}):")
    per_cluster_a = compute_per_cluster_stability(runs_detailed, article_to_cluster, run_a, run_b)

    # per-cluster stability for run_b against run_a
    print(f"\nper-cluster stability (run A = {run_b}):")
    per_cluster_b = compute_per_cluster_stability(runs_detailed, article_to_cluster, run_b, run_a)

    # print results
    print(f"\n{'='*70}")
    print(f"PER-CLUSTER STABILITY: {run_a}")
    print(f"{'='*70}")
    print(f"  {'cluster':<55} {'n':>3} {'stab':>6} {'→ destination'}")
    print(f"  {'─'*80}")

    stable_count = 0
    unstable_count = 0
    china_cluster = None

    for r in per_cluster_a:
        if r["is_singleton"]:
            continue
        flag = "✓" if r["stable"] else "⚠ UNSTABLE"
        print(f"  {r['cluster'][:55]:<55} {r['members_in_common']:>3} "
              f"{r['stability']:>6.1%} {flag}")
        if r["stable"]:
            stable_count += 1
        else:
            unstable_count += 1

        # check for China/Realpolitik cluster
        if "china" in r["cluster"].lower() or "realpolitik" in r["cluster"].lower():
            china_cluster = r

    print(f"\n  stable (≥0.5): {stable_count}")
    print(f"  unstable (<0.5): {unstable_count}")

    print(f"\n{'='*70}")
    print(f"PER-CLUSTER STABILITY: {run_b}")
    print(f"{'='*70}")
    print(f"  {'cluster':<55} {'n':>3} {'stab':>6} {'→ destination'}")
    print(f"  {'─'*80}")

    for r in per_cluster_b:
        if r["is_singleton"]:
            continue
        flag = "✓" if r["stable"] else "⚠ UNSTABLE"
        print(f"  {r['cluster'][:55]:<55} {r['members_in_common']:>3} "
              f"{r['stability']:>6.1%} {flag}")

        if "china" in r["cluster"].lower() or "realpolitik" in r["cluster"].lower():
            china_cluster = china_cluster or r

    # china realpolitik cluster specifically
    if china_cluster:
        print(f"\n{'='*70}")
        print(f"CHINA REALPOLITIK CLUSTER")
        print(f"  cluster: {china_cluster['cluster']}")
        print(f"  members in comparison: {china_cluster['members_in_common']}")
        print(f"  stability: {china_cluster['stability']:.1%}")
        print(f"  destinations: {json.dumps(china_cluster['all_destinations'], indent=4)}")
        print(f"  assessment: {'STABLE' if china_cluster['stable'] else 'UNSTABLE — treat as tentative'}")
    else:
        print(f"\nno China/Realpolitik cluster found in either run")

    # save
    all_results = {
        "event_id": args.event_id,
        "run_a": run_a,
        "run_b": run_b,
        "common_articles": best_common,
        "per_cluster_run_a": per_cluster_a,
        "per_cluster_run_b": per_cluster_b,
        "stable_count_a": stable_count,
        "unstable_count_a": unstable_count,
        "china_realpolitik": china_cluster,
    }

    os.makedirs("results", exist_ok=True)
    out_path = f"results/cluster_stability_per_cluster_{args.event_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")

    session.close()


if __name__ == "__main__":
    main()
