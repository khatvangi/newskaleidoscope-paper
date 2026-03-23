#!/usr/bin/env python3
"""
embedding_cluster.py — fast embedding-based clustering (no GPU LLM needed).

uses sentence-transformers to embed framing descriptions, then HDBSCAN
for density-based clustering. runs on CPU. produces emergent clusters
comparable to LLM pass 2 but in minutes instead of hours.

usage:
  python3 scripts/embedding_cluster.py --event-id 5
  python3 scripts/embedding_cluster.py --event-id 5 --min-cluster 5
  python3 scripts/embedding_cluster.py --event-id 5 --label  # auto-label clusters via LLM
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime

import numpy as np
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("embed_cluster")


def get_conn():
    return psycopg2.connect(DB_URL)


def load_framings(event_id):
    """load all primary_frame descriptions from analyses."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT an.article_id, an.primary_frame, a.original_language, a.title
        FROM analyses an
        JOIN articles a ON an.article_id = a.id
        WHERE an.event_id = %s
          AND an.primary_frame IS NOT NULL
          AND an.primary_frame != ''
        ORDER BY an.article_id
    """, (event_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    log.info(f"loaded {len(rows)} framings for event_id={event_id}")
    return rows


def embed_framings(framings):
    """embed all framing descriptions using sentence-transformers."""
    from sentence_transformers import SentenceTransformer

    log.info("loading sentence-transformers model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    texts = [f[1] for f in framings]
    log.info(f"embedding {len(texts)} framings...")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=128)
    log.info(f"embeddings shape: {embeddings.shape}")
    return embeddings


def cluster_embeddings(embeddings, min_cluster_size=5, min_samples=3):
    """reduce dimensions with UMAP, then cluster with HDBSCAN."""
    import hdbscan

    # step 1: UMAP to ~15 dimensions (separates sub-topics in embedding space)
    try:
        import umap
        log.info("reducing dimensions with UMAP (384 → 15)...")
        reducer = umap.UMAP(
            n_components=15,
            n_neighbors=30,
            min_dist=0.0,
            metric="cosine",
            random_state=42,
        )
        reduced = reducer.fit_transform(embeddings)
        log.info(f"UMAP reduced to {reduced.shape}")
    except ImportError:
        log.warning("umap not available, using L2-normalized embeddings")
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        reduced = embeddings / norms

    # step 2: HDBSCAN on reduced embeddings
    log.info(f"clustering with HDBSCAN (min_cluster={min_cluster_size}, min_samples={min_samples})...")
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(reduced)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = list(labels).count(-1)
    log.info(f"found {n_clusters} clusters, {n_noise} noise points (singletons)")
    return labels


def auto_label_cluster(framings_in_cluster, max_examples=10):
    """generate a descriptive label from the cluster's framing texts."""
    # take a sample of framings
    sample = framings_in_cluster[:max_examples]
    texts = [f[1][:200] for f in sample]

    # find common words (simple TF approach)
    all_words = []
    stop_words = {
        "the", "a", "an", "of", "in", "to", "and", "is", "are", "was", "were",
        "that", "this", "for", "on", "with", "as", "by", "it", "its", "from",
        "at", "be", "has", "have", "had", "not", "but", "or", "which", "their",
        "they", "he", "she", "his", "her", "who", "what", "how", "about",
        "article", "frames", "framing", "coverage", "news", "media",
    }
    for text in texts:
        words = text.lower().split()
        words = [w.strip(".,;:!?\"'()[]") for w in words if len(w) > 3]
        words = [w for w in words if w not in stop_words]
        all_words.extend(words)

    # top keywords
    counter = Counter(all_words)
    top_words = [w for w, _ in counter.most_common(8)]

    # build label from first framing + keywords
    first_frame = framings_in_cluster[0][1][:100]
    keywords = ", ".join(top_words[:5])

    return first_frame, keywords


def analyze_clusters(framings, labels, embeddings):
    """analyze cluster composition and generate descriptions."""
    clusters = defaultdict(list)
    for i, label in enumerate(labels):
        clusters[label].append(framings[i])

    # sort by size (excluding noise = -1)
    sorted_clusters = sorted(
        [(k, v) for k, v in clusters.items() if k != -1],
        key=lambda x: -len(x[1])
    )

    results = []
    for cluster_id, members in sorted_clusters:
        # language distribution
        langs = Counter([m[2] for m in members])
        top_langs = langs.most_common(5)

        # auto-label
        first_frame, keywords = auto_label_cluster(members)

        results.append({
            "cluster_id": cluster_id,
            "size": len(members),
            "pct": len(members) / len(framings) * 100,
            "representative_frame": first_frame,
            "keywords": keywords,
            "top_languages": top_langs,
            "article_ids": [m[0] for m in members],
        })

    # noise stats
    noise_count = len(clusters.get(-1, []))

    return results, noise_count


def write_to_db(event_id, results, noise_count, run_id):
    """write clusters to DB."""
    conn = get_conn()
    cur = conn.cursor()

    written = 0
    for r in results:
        cur.execute("""
            INSERT INTO clusters (event_id, label, article_count, description,
                                  method, run_id, is_singleton, valid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, true)
            RETURNING id
        """, (
            event_id,
            r["representative_frame"][:500],
            r["size"],
            f"Keywords: {r['keywords']}. Top languages: {', '.join(f'{l}({n})' for l,n in r['top_languages'])}",
            "sentence_embedding_hdbscan",
            run_id,
            r["size"] == 1,
        ))
        cluster_db_id = cur.fetchone()[0]

        # write memberships
        for article_id in r["article_ids"]:
            cur.execute("""
                INSERT INTO cluster_memberships (cluster_id, article_id)
                VALUES (%s, %s)
            """, (cluster_db_id, article_id))

        written += 1

    conn.commit()
    cur.close()
    conn.close()
    log.info(f"wrote {written} clusters to DB (run_id={run_id})")


def print_results(results, noise_count, total):
    """print cluster analysis."""
    print(f"\n{'='*80}")
    print(f"EMERGENT FRAMING CLUSTERS (embedding-based)")
    print(f"{'='*80}")
    print(f"  total framings: {total}")
    print(f"  clusters found: {len(results)}")
    print(f"  noise/singletons: {noise_count} ({noise_count/total*100:.1f}%)")
    print(f"\n{'Rank':>4} {'Size':>5} {'%':>6}  {'Keywords':40s}  {'Top Languages'}")
    print(f"{'-'*90}")

    for i, r in enumerate(results[:30]):
        langs = ", ".join(f"{l}({n})" for l, n in r["top_languages"][:3])
        print(f"  {i+1:3d} {r['size']:5d} {r['pct']:5.1f}%  {r['keywords'][:40]:40s}  {langs}")

    # print top 10 with full representative frames
    print(f"\n{'='*80}")
    print(f"TOP 10 CLUSTERS — REPRESENTATIVE FRAMINGS")
    print(f"{'='*80}")
    for i, r in enumerate(results[:10]):
        langs = ", ".join(f"{l}({n})" for l, n in r["top_languages"][:5])
        print(f"\n  [{i+1}] {r['size']} articles ({r['pct']:.1f}%)")
        print(f"      {r['representative_frame']}")
        print(f"      keywords: {r['keywords']}")
        print(f"      languages: {langs}")


def main():
    parser = argparse.ArgumentParser(description="embedding-based clustering")
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--min-cluster", type=int, default=5)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--no-db", action="store_true", help="don't write to DB")
    args = parser.parse_args()

    # load
    framings = load_framings(args.event_id)
    if not framings:
        log.error("no framings found")
        return

    # embed
    embeddings = embed_framings(framings)

    # cluster
    labels = cluster_embeddings(embeddings, args.min_cluster, args.min_samples)

    # analyze
    results, noise_count = analyze_clusters(framings, labels, embeddings)

    # print
    print_results(results, noise_count, len(framings))

    # save to file
    run_id = f"embedding_hdbscan_{datetime.now().strftime('%Y%m%d_%H%M')}"
    outfile = f"analysis/embedding_clusters_event{args.event_id}_{run_id}.json"
    os.makedirs("analysis", exist_ok=True)

    export = {
        "event_id": args.event_id,
        "run_id": run_id,
        "method": "sentence_embedding_hdbscan_umap",
        "total_framings": len(framings),
        "n_clusters": len(results),
        "noise_count": int(noise_count),
        "clusters": [{
            "cluster_id": int(r["cluster_id"]),
            "size": int(r["size"]),
            "pct": round(r["pct"], 1),
            "representative_frame": r["representative_frame"],
            "keywords": r["keywords"],
            "top_languages": [(str(l), int(n)) for l, n in r["top_languages"]],
            "article_ids": [int(x) for x in r["article_ids"][:20]],
        } for r in results],
    }
    with open(outfile, "w") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    log.info(f"saved to {outfile}")

    # write to DB
    if not args.no_db:
        write_to_db(args.event_id, results, noise_count, run_id)


if __name__ == "__main__":
    main()
