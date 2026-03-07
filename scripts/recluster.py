#!/usr/bin/env python3
"""
recluster.py — re-run Pass 2 clustering on existing all_results.json.

uses the updated pass2_cluster() with no 120-char truncation.
saves under a new run_id and preserves old clusters per immutability rules.

usage:
  python3 scripts/recluster.py                    # CS1 (event_id=2)
  python3 scripts/recluster.py --event-id 3       # CS2
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import pass2_cluster, generate_absence_report, find_best_model, log
from db import get_session, Event, Cluster, ClusterMembership

ANALYSIS_DIR = "analysis"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, default=2)
    args = parser.parse_args()

    # load event from DB
    session = get_session()
    event = session.query(Event).get(args.event_id)
    if not event:
        print(f"event_id {args.event_id} not found")
        sys.exit(1)

    event_context = event.prompt_context or event.title
    absence_examples = event.absence_examples or ""
    print(f"event: {event.title} (id={event.id})")
    print(f"prompt context: {event_context}")

    # load existing results
    results_path = os.path.join(ANALYSIS_DIR, "all_results.json")
    with open(results_path, "r", encoding="utf-8") as f:
        results = json.load(f)
    print(f"loaded {len(results)} article results")

    # check model
    model = find_best_model()
    print(f"model: {model}")

    # generate run_id
    run_id = f"recluster_{time.strftime('%Y%m%d_%H%M%S')}"
    print(f"run_id: {run_id}")

    # preview what clustering will see (first 3 articles)
    print("\npreview (first 3 descriptions fed to clustering):")
    for i, r in enumerate(results[:3]):
        analysis = r.get("analysis", {})
        desc = analysis.get("one_sentence_summary", "") or analysis.get("framing_description", "")[:300]
        country = r.get("sourcecountry", "unknown")
        domain = r.get("domain", "unknown")
        print(f"  [{i}] {domain} ({country}): {desc[:100]}...")

    # run pass 2 clustering with expanded input
    print(f"\nrunning pass 2 clustering on {len(results)} articles...")
    cluster_data = pass2_cluster(model, results, event_context=event_context)

    if not cluster_data or cluster_data.get("raw_response"):
        print("clustering failed — raw response saved")
        fail_path = os.path.join(ANALYSIS_DIR, f"recluster_failed_{run_id}.json")
        with open(fail_path, "w", encoding="utf-8") as f:
            json.dump(cluster_data, f, indent=2, ensure_ascii=False)
        sys.exit(1)

    # save to file with run_id (never overwrite emergent_clusters.json)
    out_path = os.path.join(ANALYSIS_DIR, f"emergent_clusters_{run_id}.json")
    cluster_data["run_id"] = run_id
    cluster_data["article_count"] = len(results)
    cluster_data["method"] = "llm_pass2_full_desc"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cluster_data, f, indent=2, ensure_ascii=False)
    print(f"saved: {out_path}")

    # write to DB with run_id and method tag
    clusters_written = 0
    memberships_written = 0

    # build url -> article_id mapping from DB
    from db import Article
    url_to_article_id = {}
    for a in session.query(Article).filter_by(event_id=event.id).all():
        url_to_article_id[a.url] = a.id

    for c in cluster_data.get("emergent_clusters", []):
        indices = c.get("member_indices", [])
        geo_sig = {}
        for idx in indices:
            if 0 <= idx < len(results):
                country = results[idx].get("sourcecountry", "unknown")
                geo_sig[country] = geo_sig.get(country, 0) + 1

        cluster = Cluster(
            event_id=event.id,
            run_id=run_id,
            method="llm_pass2_full_desc",
            label=c.get("cluster_name", ""),
            description=c.get("description", ""),
            article_count=len(indices),
            geographic_signature=geo_sig,
            maps_to_conventional=c.get("maps_to_conventional_category"),
        )
        session.add(cluster)
        session.flush()
        clusters_written += 1

        for idx in indices:
            if 0 <= idx < len(results):
                url = results[idx].get("url", "")
                article_id = url_to_article_id.get(url)
                if article_id:
                    session.add(ClusterMembership(
                        article_id=article_id,
                        cluster_id=cluster.id,
                    ))
                    memberships_written += 1

    # singletons
    for s in cluster_data.get("singletons", []):
        idx = s.get("index", -1)
        if 0 <= idx < len(results):
            url = results[idx].get("url", "")
            article_id = url_to_article_id.get(url)
            title_frag = results[idx].get("title", "")[:60]
            cluster = Cluster(
                event_id=event.id,
                run_id=run_id,
                method="llm_pass2_full_desc",
                label=f"Singleton: {title_frag}",
                article_count=1,
                is_singleton=True,
                geographic_signature={results[idx].get("sourcecountry", "unknown"): 1},
            )
            session.add(cluster)
            session.flush()
            clusters_written += 1
            if article_id:
                session.add(ClusterMembership(
                    article_id=article_id, cluster_id=cluster.id,
                ))
                memberships_written += 1

    session.commit()

    # summary
    print(f"\n{'='*50}")
    print(f"RECLUSTERING COMPLETE")
    print(f"  run_id: {run_id}")
    print(f"  method: llm_pass2_full_desc (no 120-char truncation)")
    print(f"  clusters: {clusters_written}")
    print(f"  memberships: {memberships_written}")
    if "emergent_clusters" in cluster_data:
        for c in cluster_data["emergent_clusters"]:
            conv = c.get("maps_to_conventional_category")
            tag = f" (= {conv})" if conv else " [NOVEL]"
            print(f"    {c['cluster_name']}{tag}: {len(c.get('member_indices', []))} articles")
    if cluster_data.get("singletons"):
        print(f"  singletons: {len(cluster_data['singletons'])}")
    print(f"  meta: {cluster_data.get('meta_observation', '')[:200]}")
    print(f"{'='*50}")

    session.close()


if __name__ == "__main__":
    main()
