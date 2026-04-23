#!/usr/bin/env python3
"""
cluster_event6.py — simple chunked clustering for epstein intellectual corpus.
runs pass2_cluster on chunks of 30, then merges hierarchically.
writes results to DB and JSON artifact.
"""
import sys, os, json, time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import (
    find_best_model, pass2_cluster, generate_absence_report,
    load_existing_results_from_db, write_clusters_to_db, write_json_artifact, log
)
from db import get_session, Event

EVENT_ID = 6
CHUNK_SIZE = 30
RUN_ID = f"epstein_intellectual_{time.strftime('%Y%m%d_%H%M%S')}"
METHOD = "llm_pass2_chunked"


def article_summary(result):
    analysis = result.get("analysis", {})
    desc = analysis.get("one_sentence_summary", "") or analysis.get("framing_description", "")
    desc = (desc or "").replace("\n", " ").strip()
    return desc[:240] if desc else "No summary available."


def cluster_chunk(model, chunk_results, event_context, chunk_id, max_retries=3):
    """cluster a single chunk with retries."""
    for attempt in range(max_retries):
        data = pass2_cluster(model, chunk_results, event_context=event_context)
        if data and not data.get("raw_response"):
            return data
        log.warning(f"  chunk {chunk_id} attempt {attempt+1}/{max_retries} failed, retrying...")
        time.sleep(2)
    log.error(f"  chunk {chunk_id} failed after {max_retries} attempts")
    return None


def main():
    session = get_session()
    event = session.get(Event, EVENT_ID)
    event_context = event.prompt_context or event.title
    print(f"event: {event.title} (id={EVENT_ID})")
    print(f"run_id: {RUN_ID}")

    model = find_best_model()
    print(f"model: {model}")

    # load results
    results_map = load_existing_results_from_db(session, EVENT_ID)
    results = list(results_map.values())
    print(f"results: {len(results)}")

    # stage 1: cluster each chunk of 30
    stage1_clusters = []
    n_chunks = (len(results) + CHUNK_SIZE - 1) // CHUNK_SIZE

    for ci in range(n_chunks):
        start = ci * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, len(results))
        chunk = results[start:end]

        # build pseudo results for this chunk
        pseudo = []
        for i, r in enumerate(chunk):
            pseudo.append({
                "url": r.get("url", f"article://{start+i}"),
                "domain": r.get("domain", "unknown"),
                "sourcecountry": r.get("sourcecountry", "unknown"),
                "analysis": {
                    "one_sentence_summary": article_summary(r),
                    "framing_description": article_summary(r),
                },
            })

        print(f"  chunk {ci+1}/{n_chunks}: articles {start}-{end-1}")
        data = cluster_chunk(model, pseudo, event_context, ci+1)

        if data:
            clusters = data.get("emergent_clusters", [])
            # remap indices to global
            for c in clusters:
                c["member_indices"] = [start + idx for idx in c.get("member_indices", [])]
            stage1_clusters.extend(clusters)

            singletons = data.get("singletons", [])
            for s in singletons:
                idx = s.get("index", -1)
                if 0 <= idx < len(chunk):
                    stage1_clusters.append({
                        "cluster_name": f"Singleton: {article_summary(chunk[idx])[:80]}",
                        "description": s.get("why_unique", ""),
                        "member_indices": [start + idx],
                        "geographic_pattern": chunk[idx].get("sourcecountry", "unknown"),
                        "maps_to_conventional_category": None,
                    })
            print(f"    → {len(clusters)} clusters, {len(singletons)} singletons")
        else:
            # fallback: keep each article as its own singleton
            for i in range(start, end):
                stage1_clusters.append({
                    "cluster_name": f"Unclustered: {article_summary(results[i])[:80]}",
                    "description": "",
                    "member_indices": [i],
                    "geographic_pattern": results[i].get("sourcecountry", "unknown"),
                    "maps_to_conventional_category": None,
                })
            print(f"    → FAILED, kept {end-start} as singletons")

    print(f"\nstage 1 complete: {len(stage1_clusters)} items")

    # stage 2: merge stage 1 clusters (if manageable, <120 items)
    if len(stage1_clusters) <= 120:
        print(f"\nstage 2: merging {len(stage1_clusters)} items...")
        # build pseudo results from stage 1 clusters
        merge_pseudo = []
        for i, c in enumerate(stage1_clusters):
            merge_pseudo.append({
                "url": f"cluster://{i}",
                "domain": "stage1_cluster",
                "sourcecountry": c.get("geographic_pattern", "mixed"),
                "analysis": {
                    "one_sentence_summary": f"{c['cluster_name']}: {c.get('description', '')}"[:220],
                    "framing_description": f"{c['cluster_name']}: {c.get('description', '')}"[:220],
                },
            })

        # cluster in chunks of 30 again
        stage2_clusters = []
        n_merge_chunks = (len(merge_pseudo) + CHUNK_SIZE - 1) // CHUNK_SIZE
        for ci in range(n_merge_chunks):
            start = ci * CHUNK_SIZE
            end = min(start + CHUNK_SIZE, len(merge_pseudo))
            chunk = merge_pseudo[start:end]
            print(f"  merge chunk {ci+1}/{n_merge_chunks}")
            data = cluster_chunk(model, chunk, event_context, f"merge_{ci+1}")
            if data:
                for c in data.get("emergent_clusters", []):
                    # remap: indices point to stage1_clusters, collect all article indices
                    article_indices = []
                    for idx in c.get("member_indices", []):
                        global_idx = start + idx
                        if 0 <= global_idx < len(stage1_clusters):
                            article_indices.extend(stage1_clusters[global_idx].get("member_indices", []))
                    c["member_indices"] = sorted(set(article_indices))
                    stage2_clusters.append(c)
                for s in data.get("singletons", []):
                    idx = s.get("index", -1)
                    global_idx = start + idx
                    if 0 <= global_idx < len(stage1_clusters):
                        sc = stage1_clusters[global_idx].copy()
                        stage2_clusters.append(sc)
                print(f"    → {len(data.get('emergent_clusters',[]))} clusters")
            else:
                # keep stage1 items
                for j in range(start, end):
                    stage2_clusters.append(stage1_clusters[j])
                print(f"    → FAILED, kept {end-start} as-is")

        final_clusters = stage2_clusters
    else:
        final_clusters = stage1_clusters

    # build final output
    emergent = [c for c in final_clusters if len(c.get("member_indices", [])) > 1]
    singletons_out = [{"index": c["member_indices"][0], "why_unique": c.get("description", "")}
                      for c in final_clusters if len(c.get("member_indices", [])) == 1]

    cluster_data = {
        "emergent_clusters": emergent,
        "singletons": singletons_out,
        "meta_observation": f"Hierarchical chunked clustering of {len(results)} articles in chunks of {CHUNK_SIZE}.",
    }

    print(f"\nFINAL: {len(emergent)} clusters, {len(singletons_out)} singletons")
    for c in emergent:
        print(f"  [{len(c.get('member_indices',[]))} articles] {c.get('cluster_name','?')}")

    # write to DB — need url_to_article_id mapping
    url_to_article_id = {}
    for r in results:
        url = r.get("url", "")
        aid = r.get("article_id")
        if url and aid:
            url_to_article_id[url] = aid
    write_clusters_to_db(session, EVENT_ID, cluster_data, results, url_to_article_id, run_id=RUN_ID, method=METHOD)
    session.commit()

    # write JSON artifact
    write_json_artifact("analysis/emergent_clusters", cluster_data, run_id=RUN_ID, event_id=EVENT_ID)
    print(f"\nwritten to DB (run_id={RUN_ID}) and analysis/")

    # absence report
    print("\ngenerating absence report...")
    absence = generate_absence_report(model, results, cluster_data, event_context=event_context)
    if absence:
        write_json_artifact("analysis/absence_report", absence, run_id=RUN_ID, event_id=EVENT_ID)
        print("absence report written")


if __name__ == "__main__":
    main()
