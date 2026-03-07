#!/usr/bin/env python3
"""
cluster_stability.py — measure cluster stability across runs using ARI.

compares clustering runs from the DB (different run_ids) to assess how stable
the emergent clusters are. high ARI = clusters are reproducible. low ARI =
clusters are method-sensitive artifacts.

also computes bootstrap stability by re-sampling 80% of articles and re-clustering.

usage:
  python3 scripts/cluster_stability.py                    # compare all runs for CS1
  python3 scripts/cluster_stability.py --event-id 3       # CS2
  python3 scripts/cluster_stability.py --bootstrap 5      # run 5 bootstrap samples
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from db import get_session, Event, Cluster, ClusterMembership, Article


def load_cluster_runs(session, event_id):
    """load all clustering runs for an event, returning {run_id: {article_id: cluster_label}}."""
    clusters = session.query(Cluster).filter_by(event_id=event_id).all()

    # group by run_id
    runs = defaultdict(dict)  # run_id -> {article_id -> cluster_label}
    for cluster in clusters:
        run_id = cluster.run_id or "legacy"
        for membership in cluster.memberships:
            # if article is in multiple clusters, use first assignment
            if membership.article_id not in runs[run_id]:
                runs[run_id][membership.article_id] = cluster.label

    return dict(runs)


def compare_runs(runs):
    """compute pairwise ARI and NMI between all clustering runs."""
    run_ids = sorted(runs.keys())
    if len(run_ids) < 2:
        print("need at least 2 clustering runs to compare")
        return []

    comparisons = []
    for i in range(len(run_ids)):
        for j in range(i + 1, len(run_ids)):
            r1, r2 = run_ids[i], run_ids[j]
            # find common articles
            common_articles = sorted(set(runs[r1].keys()) & set(runs[r2].keys()))
            if len(common_articles) < 5:
                print(f"  {r1} vs {r2}: only {len(common_articles)} common articles, skipping")
                continue

            labels1 = [runs[r1][a] for a in common_articles]
            labels2 = [runs[r2][a] for a in common_articles]

            ari = adjusted_rand_score(labels1, labels2)
            nmi = normalized_mutual_info_score(labels1, labels2)

            comparisons.append({
                "run_a": r1,
                "run_b": r2,
                "common_articles": len(common_articles),
                "ari": round(ari, 4),
                "nmi": round(nmi, 4),
                "clusters_a": len(set(labels1)),
                "clusters_b": len(set(labels2)),
            })

            print(f"  {r1} vs {r2}:")
            print(f"    common articles: {len(common_articles)}")
            print(f"    ARI:  {ari:.4f}  {'(strong)' if ari > 0.6 else '(moderate)' if ari > 0.3 else '(weak)'}")
            print(f"    NMI:  {nmi:.4f}")
            print(f"    clusters: {len(set(labels1))} vs {len(set(labels2))}")

    return comparisons


def run_bootstrap(event_id, n_samples=5):
    """bootstrap stability: re-cluster random 80% subsets, compare to full run."""
    import random

    # load full results
    results_path = "analysis/all_results.json"
    if not os.path.exists(results_path):
        print(f"no {results_path} found — cannot bootstrap")
        return []

    with open(results_path, "r", encoding="utf-8") as f:
        full_results = json.load(f)

    session = get_session()
    event = session.query(Event).get(event_id)
    event_context = event.prompt_context or event.title if event else "a major geopolitical event"
    session.close()

    from pipeline import pass2_cluster, find_best_model
    model = find_best_model()

    # run full clustering first as reference
    print(f"\nbootstrap reference: clustering all {len(full_results)} articles...")
    ref_data = pass2_cluster(model, full_results, event_context=event_context)
    if not ref_data or ref_data.get("raw_response"):
        print("reference clustering failed")
        return []

    # build reference label map: index -> cluster_name
    ref_labels = {}
    for c in ref_data.get("emergent_clusters", []):
        for idx in c.get("member_indices", []):
            ref_labels[idx] = c["cluster_name"]

    bootstrap_aris = []
    for s in range(n_samples):
        # sample 80% of articles
        n_sample = int(len(full_results) * 0.8)
        sample_indices = sorted(random.sample(range(len(full_results)), n_sample))
        sample_results = [full_results[i] for i in sample_indices]

        print(f"\nbootstrap {s+1}/{n_samples}: {n_sample} articles...")
        sample_data = pass2_cluster(model, sample_results, event_context=event_context)

        if not sample_data or sample_data.get("raw_response"):
            print(f"  bootstrap {s+1} failed")
            continue

        # build sample label map: original_index -> cluster_name
        sample_labels = {}
        for c in sample_data.get("emergent_clusters", []):
            for local_idx in c.get("member_indices", []):
                if local_idx < len(sample_indices):
                    original_idx = sample_indices[local_idx]
                    sample_labels[original_idx] = c["cluster_name"]

        # compute ARI on common articles
        common = sorted(set(ref_labels.keys()) & set(sample_labels.keys()))
        if len(common) < 5:
            print(f"  only {len(common)} common articles, skipping")
            continue

        labels_ref = [ref_labels[i] for i in common]
        labels_sample = [sample_labels[i] for i in common]
        ari = adjusted_rand_score(labels_ref, labels_sample)
        bootstrap_aris.append(ari)
        print(f"  ARI vs reference: {ari:.4f}")

    if bootstrap_aris:
        mean_ari = sum(bootstrap_aris) / len(bootstrap_aris)
        print(f"\nbootstrap stability ({len(bootstrap_aris)} samples):")
        print(f"  mean ARI: {mean_ari:.4f}")
        print(f"  range: [{min(bootstrap_aris):.4f}, {max(bootstrap_aris):.4f}]")
        stability = "high" if mean_ari > 0.6 else "moderate" if mean_ari > 0.3 else "low"
        print(f"  assessment: {stability} stability")

    return bootstrap_aris


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, default=2)
    parser.add_argument("--bootstrap", type=int, default=0,
                        help="number of bootstrap samples (each takes ~2min)")
    args = parser.parse_args()

    session = get_session()
    event = session.query(Event).get(args.event_id)
    if not event:
        print(f"event_id {args.event_id} not found")
        sys.exit(1)

    print(f"event: {event.title} (id={event.id})")

    # load all clustering runs
    runs = load_cluster_runs(session, args.event_id)
    print(f"found {len(runs)} clustering run(s): {list(runs.keys())}")
    for run_id, assignments in runs.items():
        n_clusters = len(set(assignments.values()))
        print(f"  {run_id}: {len(assignments)} articles in {n_clusters} clusters")

    # pairwise comparison
    if len(runs) >= 2:
        print(f"\npairwise comparisons:")
        comparisons = compare_runs(runs)
    else:
        print("\nonly 1 run found — need at least 2 for ARI comparison")
        print("run recluster.py with different parameters to create more runs")
        comparisons = []

    # bootstrap if requested
    bootstrap_aris = []
    if args.bootstrap > 0:
        bootstrap_aris = run_bootstrap(args.event_id, args.bootstrap)

    # save results
    results = {
        "event_id": args.event_id,
        "event_title": event.title,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runs": {
            rid: {"articles": len(assignments), "clusters": len(set(assignments.values()))}
            for rid, assignments in runs.items()
        },
        "pairwise_comparisons": comparisons,
        "bootstrap_aris": bootstrap_aris,
        "bootstrap_mean_ari": sum(bootstrap_aris) / len(bootstrap_aris) if bootstrap_aris else None,
    }

    os.makedirs("results", exist_ok=True)
    out_path = f"results/cluster_stability_{args.event_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")

    session.close()


if __name__ == "__main__":
    main()
