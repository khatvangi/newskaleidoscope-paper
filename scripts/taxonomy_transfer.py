#!/usr/bin/env python3
"""
taxonomy_transfer.py — formal taxonomy transfer metric between events.

measures whether the cluster structure discovered in event A generalizes
to event B. uses cluster centroid embedding similarity and Hungarian
matching.

outputs:
- matched cluster pairs with similarity scores
- unmatched clusters from A (didn't transfer)
- novel clusters in B (no A analogue)
- overall transfer rate

usage:
  python3 scripts/taxonomy_transfer.py --event-a 2 --event-b 3
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_session, Event, Article, Analysis, Cluster, ClusterMembership

TRANSFER_THRESHOLD = 0.70  # cosine ≥ 0.70 = cluster present in target event


def load_cluster_framings(session, event_id):
    """load cluster names and member article framing descriptions.
    returns {cluster_label: {"description": str, "framings": [str], "members": int}}"""
    clusters = (
        session.query(Cluster)
        .filter_by(event_id=event_id)
        .order_by(Cluster.created_at.desc())
        .all()
    )

    # deduplicate by label (use most recent run)
    seen = set()
    cluster_data = {}

    for cluster in clusters:
        if cluster.label in seen or cluster.label.startswith("Singleton"):
            continue
        seen.add(cluster.label)

        # get member article framings
        framings = []
        for membership in cluster.memberships:
            analysis = (
                session.query(Analysis)
                .filter_by(article_id=membership.article_id)
                .first()
            )
            if analysis and analysis.primary_frame:
                framings.append(analysis.primary_frame)

        cluster_data[cluster.label] = {
            "description": cluster.description or "",
            "framings": framings,
            "members": cluster.article_count or len(framings),
            "maps_to_conventional": cluster.maps_to_conventional,
        }

    return cluster_data


def compute_cluster_centroid(embedder, cluster_info):
    """compute centroid embedding from member article framings."""
    if not cluster_info["framings"]:
        # fall back to cluster label + description
        text = f"{cluster_info.get('label', '')}. {cluster_info['description']}"
        return embedder.encode(text)

    embeddings = embedder.encode(cluster_info["framings"])
    return np.mean(embeddings, axis=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-a", type=int, required=True,
                        help="source event ID (e.g., CS1)")
    parser.add_argument("--event-b", type=int, required=True,
                        help="target event ID (e.g., CS2)")
    parser.add_argument("--threshold", type=float, default=TRANSFER_THRESHOLD)
    args = parser.parse_args()

    session = get_session()

    event_a = session.query(Event).get(args.event_a)
    event_b = session.query(Event).get(args.event_b)
    if not event_a or not event_b:
        print(f"events not found: a={args.event_a}, b={args.event_b}")
        sys.exit(1)

    print(f"source event (A): {event_a.title} (id={event_a.id})")
    print(f"target event (B): {event_b.title} (id={event_b.id})")
    print(f"transfer threshold: {args.threshold}")

    # load cluster data
    clusters_a = load_cluster_framings(session, args.event_a)
    clusters_b = load_cluster_framings(session, args.event_b)

    print(f"\nclusters in A: {len(clusters_a)}")
    for name, info in clusters_a.items():
        print(f"  {name[:60]}: {info['members']} members, {len(info['framings'])} framings")

    print(f"\nclusters in B: {len(clusters_b)}")
    for name, info in clusters_b.items():
        print(f"  {name[:60]}: {info['members']} members, {len(info['framings'])} framings")

    if not clusters_a or not clusters_b:
        print("\none or both events have no clusters — cannot compute transfer")
        session.close()
        sys.exit(1)

    # load sentence transformer
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")

    # compute centroids
    print(f"\ncomputing cluster centroids...")
    centroids_a = {}
    for name, info in clusters_a.items():
        info["label"] = name
        centroids_a[name] = compute_cluster_centroid(embedder, info)

    centroids_b = {}
    for name, info in clusters_b.items():
        info["label"] = name
        centroids_b[name] = compute_cluster_centroid(embedder, info)

    # compute all-pairs cosine similarity
    names_a = list(centroids_a.keys())
    names_b = list(centroids_b.keys())

    similarity_matrix = np.zeros((len(names_a), len(names_b)))
    for i, na in enumerate(names_a):
        for j, nb in enumerate(names_b):
            ca = centroids_a[na]
            cb = centroids_b[nb]
            similarity_matrix[i, j] = float(
                np.dot(ca, cb) / (np.linalg.norm(ca) * np.linalg.norm(cb)))

    # Hungarian matching (maximize similarity = minimize negative)
    from scipy.optimize import linear_sum_assignment
    row_ind, col_ind = linear_sum_assignment(-similarity_matrix)

    # classify matches
    matched = []
    unmatched_a = set(range(len(names_a)))
    unmatched_b = set(range(len(names_b)))

    for ri, ci in zip(row_ind, col_ind):
        sim = similarity_matrix[ri, ci]
        unmatched_a.discard(ri)
        unmatched_b.discard(ci)

        match_type = "transferred" if sim >= args.threshold else "weak_analogue"
        matched.append({
            "cluster_a": names_a[ri],
            "cluster_b": names_b[ci],
            "cosine_similarity": round(float(sim), 4),
            "transferred": sim >= args.threshold,
            "members_a": clusters_a[names_a[ri]]["members"],
            "members_b": clusters_b[names_b[ci]]["members"],
            "conventional_a": clusters_a[names_a[ri]].get("maps_to_conventional"),
            "conventional_b": clusters_b[names_b[ci]].get("maps_to_conventional"),
        })

    # clusters that didn't transfer
    untransferred = [names_a[i] for i in unmatched_a]
    # also include matched pairs below threshold
    for m in matched:
        if not m["transferred"]:
            untransferred.append(m["cluster_a"])

    # novel clusters in B (no A analogue)
    novel_b = [names_b[i] for i in unmatched_b]
    for m in matched:
        if not m["transferred"]:
            novel_b.append(m["cluster_b"])

    transferred_count = sum(1 for m in matched if m["transferred"])
    transfer_rate = transferred_count / len(names_a) if names_a else 0

    # results
    results = {
        "event_a": {"id": args.event_a, "title": event_a.title, "clusters": len(names_a)},
        "event_b": {"id": args.event_b, "title": event_b.title, "clusters": len(names_b)},
        "threshold": args.threshold,
        "transfer_rate": round(transfer_rate, 3),
        "transferred_count": transferred_count,
        "total_a_clusters": len(names_a),
        "matched_pairs": matched,
        "untransferred_from_a": untransferred,
        "novel_in_b": novel_b,
        "similarity_matrix": {
            "rows": names_a,
            "cols": names_b,
            "values": [[round(float(v), 4) for v in row] for row in similarity_matrix],
        },
    }

    # print summary
    print(f"\n{'='*60}")
    print(f"TAXONOMY TRANSFER: {event_a.title} → {event_b.title}")
    print(f"{'='*60}")
    print(f"  transfer rate: {transferred_count}/{len(names_a)} "
          f"({transfer_rate:.0%}) at threshold {args.threshold}")

    print(f"\n  matched pairs:")
    for m in sorted(matched, key=lambda x: -x["cosine_similarity"]):
        tag = "✓ TRANSFERRED" if m["transferred"] else "✗ weak"
        print(f"    {m['cluster_a'][:35]:<35} ↔ {m['cluster_b'][:35]:<35} "
              f"cos={m['cosine_similarity']:.3f} {tag}")

    if untransferred:
        print(f"\n  did NOT transfer from A:")
        for name in untransferred:
            print(f"    {name}")

    if novel_b:
        print(f"\n  NOVEL in B (no A analogue):")
        for name in novel_b:
            print(f"    {name}")

    print(f"{'='*60}")

    # save
    os.makedirs("results", exist_ok=True)
    out_path = f"results/taxonomy_transfer_{args.event_a}_{args.event_b}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")

    session.close()


if __name__ == "__main__":
    main()
