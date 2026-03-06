#!/usr/bin/env python3
"""
cluster_stability.py — measure cluster stability via perturbation analysis.

runs clustering N times with small perturbations to frame embeddings.
measures: what fraction of article pairs co-cluster across runs?
stability_score = 1.0 means perfectly stable, 0.0 means random.
"""

import argparse
import logging
import json
import numpy as np
from collections import defaultdict

from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering

from db import get_session, Article, Analysis, Cluster, ClusterMembership

log = logging.getLogger("cluster_stability")


def load_article_frames(session, event_id):
    """load council or single-model frames for all articles in event."""
    articles = session.query(Article).filter_by(event_id=event_id).all()

    frames = []  # (article_id, frame_text)
    for art in articles:
        # prefer council consensus, fall back to single-model analysis
        analysis = session.query(Analysis).filter(
            Analysis.article_id == art.id,
            Analysis.model_used.like("council_%"),
        ).first()
        if not analysis:
            analysis = session.query(Analysis).filter_by(
                article_id=art.id
            ).first()
        if analysis and analysis.primary_frame:
            frames.append((art.id, analysis.primary_frame))
        else:
            log.warning(f"  no frame for article {art.id}, skipping")

    return frames


def embed_frames(frames, model_name="all-MiniLM-L6-v2"):
    """embed frame descriptions using sentence-transformers."""
    model = SentenceTransformer(model_name)
    texts = [f for _, f in frames]
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings


def cluster_embeddings(embeddings, n_clusters):
    """run agglomerative clustering on embeddings."""
    clustering = AgglomerativeClustering(
        n_clusters=n_clusters,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)
    return labels


def score_stability(frames, embeddings, n_clusters, n_runs=5, noise_sigma=0.01):
    """measure cluster stability via perturbation analysis.

    for each run: add gaussian noise to embeddings, re-cluster, record assignments.
    compute pairwise co-clustering rate across runs.
    """
    n = len(frames)
    if n < n_clusters:
        return {}

    # matrix: co_cluster[i][j] = count of runs where i and j are in same cluster
    co_cluster = np.zeros((n, n), dtype=int)

    for run in range(n_runs):
        # add small noise to embeddings
        noise = np.random.normal(0, noise_sigma, embeddings.shape)
        perturbed = embeddings + noise

        labels = cluster_embeddings(perturbed, n_clusters)

        # count co-clustering
        for i in range(n):
            for j in range(i + 1, n):
                if labels[i] == labels[j]:
                    co_cluster[i][j] += 1
                    co_cluster[j][i] += 1

    # also run the unperturbed baseline
    baseline_labels = cluster_embeddings(embeddings, n_clusters)

    # compute per-cluster stability
    cluster_stability = {}
    for c in range(n_clusters):
        members = [i for i in range(n) if baseline_labels[i] == c]
        if len(members) < 2:
            # singleton — stable by definition
            cluster_stability[c] = 1.0
            continue

        # average pairwise co-clustering rate
        pair_rates = []
        for i_idx in range(len(members)):
            for j_idx in range(i_idx + 1, len(members)):
                i, j = members[i_idx], members[j_idx]
                rate = co_cluster[i][j] / n_runs
                pair_rates.append(rate)

        cluster_stability[c] = float(np.mean(pair_rates)) if pair_rates else 1.0

    return baseline_labels, cluster_stability


def write_stability_scores(session, event_id, frames, baseline_labels,
                           cluster_stability, n_clusters):
    """write new stability-scored clusters to DB.

    creates new cluster records with stability scores and links articles.
    """
    # group articles by cluster label
    cluster_groups = defaultdict(list)
    for i, label in enumerate(baseline_labels):
        article_id = frames[i][0]
        frame_text = frames[i][1]
        cluster_groups[label].append((article_id, frame_text))

    # delete old clusters for this event (we're replacing them)
    old_clusters = session.query(Cluster).filter_by(event_id=event_id).all()
    for oc in old_clusters:
        session.query(ClusterMembership).filter_by(cluster_id=oc.id).delete()
        session.delete(oc)
    session.flush()

    # create new clusters with stability scores
    clusters_written = 0
    for label in range(n_clusters):
        members = cluster_groups.get(label, [])
        if not members:
            continue

        # build geographic signature
        geo_sig = {}
        for aid, _ in members:
            art = session.get(Article, aid)
            if art and art.source:
                code = art.source.country_code or "??"
                geo_sig[code] = geo_sig.get(code, 0) + 1

        stability = cluster_stability.get(label, None)
        is_singleton = len(members) == 1

        # use the most common frame as provisional label
        cluster_label = f"Cluster {label + 1} ({len(members)} articles)"

        cluster = Cluster(
            event_id=event_id,
            label=cluster_label,
            article_count=len(members),
            geographic_signature=geo_sig,
            stability_score=stability,
            is_singleton=is_singleton,
        )
        session.add(cluster)
        session.flush()

        for aid, _ in members:
            session.add(ClusterMembership(
                article_id=aid,
                cluster_id=cluster.id,
            ))

        clusters_written += 1

    session.commit()
    return clusters_written


def main():
    parser = argparse.ArgumentParser(description="compute cluster stability scores")
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--n-clusters", type=int, default=5,
                        help="number of clusters (default: 5, matching existing)")
    parser.add_argument("--n-runs", type=int, default=5,
                        help="perturbation runs for stability measurement")
    parser.add_argument("--noise", type=float, default=0.01,
                        help="gaussian noise sigma")
    parser.add_argument("--write", action="store_true",
                        help="write new clusters to DB (default: report only)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    session = get_session()

    # load frames
    frames = load_article_frames(session, args.event_id)
    log.info(f"loaded {len(frames)} article frames for event_id={args.event_id}")

    if len(frames) < args.n_clusters:
        log.error(f"not enough articles ({len(frames)}) for {args.n_clusters} clusters")
        session.close()
        return

    # embed
    log.info("embedding frames...")
    embeddings = embed_frames(frames)
    log.info(f"  embeddings shape: {embeddings.shape}")

    # stability analysis
    log.info(f"running stability analysis ({args.n_runs} runs, sigma={args.noise})...")
    baseline_labels, cluster_stability = score_stability(
        frames, embeddings, args.n_clusters,
        n_runs=args.n_runs, noise_sigma=args.noise,
    )

    # report
    print(f"\n{'='*60}")
    print(f"CLUSTER STABILITY REPORT")
    print(f"  event_id: {args.event_id}")
    print(f"  articles: {len(frames)}")
    print(f"  clusters: {args.n_clusters}")
    print(f"  perturbation runs: {args.n_runs}")
    print(f"{'='*60}")

    # group by cluster for reporting
    cluster_groups = defaultdict(list)
    for i, label in enumerate(baseline_labels):
        cluster_groups[label].append(frames[i])

    for c_label in sorted(cluster_stability.keys()):
        score = cluster_stability[c_label]
        members = cluster_groups.get(c_label, [])
        stability_bar = "=" * int(score * 20)
        print(f"\n  cluster {c_label + 1} ({len(members)} articles) stability={score:.3f} [{stability_bar}]")
        # show a few member frames
        for aid, frame in members[:3]:
            print(f"    article {aid}: {frame[:80]}")
        if len(members) > 3:
            print(f"    ... and {len(members) - 3} more")

    # identify iranian cluster
    print(f"\n  IRANIAN CLUSTER:")
    for c_label, members in cluster_groups.items():
        ir_articles = []
        for aid, frame in members:
            art = session.get(Article, aid)
            if art and art.source and art.source.country_code == "IR":
                ir_articles.append((aid, frame))
        if ir_articles:
            score = cluster_stability.get(c_label, 0)
            print(f"    cluster {c_label + 1}: {len(ir_articles)}/{len(members)} Iranian articles, stability={score:.3f}")
            for aid, frame in ir_articles:
                print(f"      article {aid}: {frame[:80]}")

    if args.write:
        log.info("writing stability-scored clusters to DB...")
        n_written = write_stability_scores(
            session, args.event_id, frames, baseline_labels,
            cluster_stability, args.n_clusters,
        )
        log.info(f"  {n_written} clusters written to DB")

    session.close()
    print(f"\n{'='*60}")


if __name__ == "__main__":
    main()
