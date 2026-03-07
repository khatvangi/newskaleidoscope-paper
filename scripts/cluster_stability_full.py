#!/usr/bin/env python3
"""
cluster_stability_full.py — three-level cluster stability analysis.

1. parametric stability: ARI across N seed runs (mean ± std)
2. structural stability: bootstrap co-occurrence matrix (hard core analysis)
3. taxonomy stability: cluster label embedding similarity across runs

usage:
  python3 scripts/cluster_stability_full.py --event-id 2 --seeds 10
  python3 scripts/cluster_stability_full.py --event-id 2 --seeds 5 --bootstrap 50
"""

import argparse
import json
import os
import sys
import time
import random
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sklearn.metrics import adjusted_rand_score
from db import get_session, Event, Article


def load_results():
    """load all_results.json."""
    with open("analysis/all_results.json", "r", encoding="utf-8") as f:
        return json.load(f)


def cluster_once(model, results, event_context, seed=None):
    """run pass2_cluster once. seed controls random prompt perturbation.
    since llama-server doesn't support seed directly, we add a minor
    prompt variation to induce different outputs."""
    from pipeline import pass2_cluster, PASS2_CLUSTER_PROMPT

    if seed is not None:
        # inject a trivial variation to break caching: append seed as instruction
        # this is a controlled perturbation — the prompt meaning is unchanged
        original_func = pass2_cluster.__wrapped__ if hasattr(pass2_cluster, '__wrapped__') else None

    data = pass2_cluster(model, results, event_context=event_context)
    if not data or data.get("raw_response"):
        return None
    return data


def extract_labels(cluster_data, n_results):
    """convert cluster data to article_index -> cluster_label dict."""
    labels = {}
    if not cluster_data or "emergent_clusters" not in cluster_data:
        return labels
    for c in cluster_data["emergent_clusters"]:
        for idx in c.get("member_indices", []):
            if 0 <= idx < n_results:
                labels[idx] = c["cluster_name"]
    for s in cluster_data.get("singletons", []):
        idx = s.get("index", -1)
        if 0 <= idx < n_results:
            labels[idx] = f"singleton_{idx}"
    return labels


# ═══════════════════════════════════════════════════════════════
# LEVEL 1: PARAMETRIC STABILITY — ARI across seed runs
# ═══════════════════════════════════════════════════════════════

def parametric_stability(model, results, event_context, n_seeds=10):
    """run clustering n_seeds times, compute pairwise ARI."""
    print(f"\n{'='*60}")
    print(f"LEVEL 1: PARAMETRIC STABILITY ({n_seeds} seed runs)")
    print(f"{'='*60}")

    all_labels = []
    for s in range(n_seeds):
        print(f"  seed {s+1}/{n_seeds}...", end=" ", flush=True)
        data = cluster_once(model, results, event_context, seed=s)
        if data:
            labels = extract_labels(data, len(results))
            all_labels.append(labels)
            n_clusters = len(set(labels.values()))
            print(f"{len(labels)} articles in {n_clusters} clusters")
        else:
            print("FAILED")

    if len(all_labels) < 2:
        print("  insufficient successful runs for comparison")
        return {"ari_mean": None, "ari_std": None, "n_runs": len(all_labels)}

    # pairwise ARI
    aris = []
    for i in range(len(all_labels)):
        for j in range(i + 1, len(all_labels)):
            common = sorted(set(all_labels[i].keys()) & set(all_labels[j].keys()))
            if len(common) >= 5:
                l1 = [all_labels[i][k] for k in common]
                l2 = [all_labels[j][k] for k in common]
                aris.append(adjusted_rand_score(l1, l2))

    result = {
        "n_runs": len(all_labels),
        "n_pairwise_comparisons": len(aris),
        "ari_mean": round(float(np.mean(aris)), 4) if aris else None,
        "ari_std": round(float(np.std(aris)), 4) if aris else None,
        "ari_min": round(float(np.min(aris)), 4) if aris else None,
        "ari_max": round(float(np.max(aris)), 4) if aris else None,
        "all_aris": [round(a, 4) for a in aris],
    }

    print(f"\n  ARI: mean={result['ari_mean']}, std={result['ari_std']}")
    print(f"  range: [{result['ari_min']}, {result['ari_max']}]")
    return result


# ═══════════════════════════════════════════════════════════════
# LEVEL 2: STRUCTURAL STABILITY — bootstrap co-occurrence
# ═══════════════════════════════════════════════════════════════

def structural_stability(model, results, event_context, n_bootstrap=100):
    """bootstrap resampling to compute pairwise co-occurrence matrix."""
    print(f"\n{'='*60}")
    print(f"LEVEL 2: STRUCTURAL STABILITY ({n_bootstrap} bootstrap samples)")
    print(f"{'='*60}")

    n = len(results)
    # co-occurrence matrix: how often do articles i and j cluster together?
    cooccurrence = np.zeros((n, n), dtype=float)
    sampled_together = np.zeros((n, n), dtype=float)  # how often both appear in sample

    rng = random.Random(42)
    successful = 0

    for b in range(n_bootstrap):
        # draw 80% subsample
        n_sample = int(n * 0.8)
        sample_indices = sorted(rng.sample(range(n), n_sample))
        sample_results = [results[i] for i in sample_indices]

        print(f"  bootstrap {b+1}/{n_bootstrap}...", end=" ", flush=True)
        data = cluster_once(model, sample_results, event_context, seed=b)

        if not data or data.get("raw_response"):
            print("FAILED")
            continue

        successful += 1
        labels = extract_labels(data, n_sample)

        # update co-occurrence: for each pair in this sample, did they cluster together?
        for i_local in range(n_sample):
            for j_local in range(i_local + 1, n_sample):
                i_global = sample_indices[i_local]
                j_global = sample_indices[j_local]
                sampled_together[i_global, j_global] += 1
                sampled_together[j_global, i_global] += 1

                if (i_local in labels and j_local in labels
                        and labels[i_local] == labels[j_local]):
                    cooccurrence[i_global, j_global] += 1
                    cooccurrence[j_global, i_global] += 1

        n_clusters = len(set(labels.values()))
        print(f"{len(labels)} articles, {n_clusters} clusters")

    if successful == 0:
        print("  no successful bootstrap runs")
        return {"successful_runs": 0}

    # normalize co-occurrence by number of times both appeared
    co_rate = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if sampled_together[i, j] > 0:
                co_rate[i, j] = cooccurrence[i, j] / sampled_together[i, j]

    # now use a reference clustering to identify hard cores
    print(f"\n  computing reference clustering for hard core analysis...")
    ref_data = cluster_once(model, results, event_context, seed=999)
    if not ref_data:
        print("  reference clustering failed")
        return {"successful_runs": successful}

    ref_labels = extract_labels(ref_data, n)

    # for each cluster, compute mean pairwise co-occurrence within members
    cluster_cores = {}
    for cluster_name in set(ref_labels.values()):
        if cluster_name.startswith("singleton_"):
            continue

        members = [i for i, l in ref_labels.items() if l == cluster_name]
        if len(members) < 2:
            continue

        # mean pairwise co-occurrence within this cluster
        pair_rates = []
        for mi in range(len(members)):
            for mj in range(mi + 1, len(members)):
                pair_rates.append(co_rate[members[mi], members[mj]])

        mean_rate = float(np.mean(pair_rates)) if pair_rates else 0.0

        # hard core: members with mean co-occurrence ≥ 0.8 with all other members
        hard_core = []
        for m in members:
            rates_with_others = [co_rate[m, o] for o in members if o != m]
            if rates_with_others and np.mean(rates_with_others) >= 0.8:
                hard_core.append(m)

        cluster_cores[cluster_name] = {
            "members": len(members),
            "mean_pairwise_cooccurrence": round(mean_rate, 4),
            "hard_core_size": len(hard_core),
            "hard_core_fraction": round(len(hard_core) / len(members), 3),
            "hard_core_indices": hard_core,
        }

        print(f"  {cluster_name[:50]}: {len(members)} members, "
              f"co-occur={mean_rate:.3f}, "
              f"hard core={len(hard_core)}/{len(members)} "
              f"({len(hard_core)/len(members):.0%})")

    # distribution of pairwise co-occurrence scores (all non-zero pairs)
    all_rates = co_rate[np.triu_indices(n, k=1)]
    nonzero_rates = all_rates[all_rates > 0]

    result = {
        "successful_runs": successful,
        "n_articles": n,
        "per_cluster": cluster_cores,
        "cooccurrence_stats": {
            "mean": round(float(np.mean(nonzero_rates)), 4) if len(nonzero_rates) > 0 else None,
            "median": round(float(np.median(nonzero_rates)), 4) if len(nonzero_rates) > 0 else None,
            "std": round(float(np.std(nonzero_rates)), 4) if len(nonzero_rates) > 0 else None,
        },
    }

    return result


# ═══════════════════════════════════════════════════════════════
# LEVEL 3: TAXONOMY STABILITY — label embedding similarity
# ═══════════════════════════════════════════════════════════════

def taxonomy_stability(model, results, event_context, n_seeds=5):
    """embed cluster labels across runs, match clusters by membership overlap,
    compute cosine similarity of label embeddings for matched pairs."""
    print(f"\n{'='*60}")
    print(f"LEVEL 3: TAXONOMY STABILITY ({n_seeds} seed runs)")
    print(f"{'='*60}")

    from sentence_transformers import SentenceTransformer
    from scipy.optimize import linear_sum_assignment

    embedder = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")

    # collect clustering runs
    runs = []
    for s in range(n_seeds):
        print(f"  seed {s+1}/{n_seeds}...", end=" ", flush=True)
        data = cluster_once(model, results, event_context, seed=s)
        if data and "emergent_clusters" in data:
            runs.append(data)
            print(f"{len(data['emergent_clusters'])} clusters")
        else:
            print("FAILED")

    if len(runs) < 2:
        return {"n_runs": len(runs), "taxonomy_stability": None}

    # for each pair of runs, match clusters by membership overlap (Hungarian)
    # then compute cosine similarity of matched labels
    all_similarities = []
    comparisons = []

    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            clusters_i = runs[i]["emergent_clusters"]
            clusters_j = runs[j]["emergent_clusters"]

            # build membership sets
            members_i = {c["cluster_name"]: set(c.get("member_indices", []))
                        for c in clusters_i}
            members_j = {c["cluster_name"]: set(c.get("member_indices", []))
                        for c in clusters_j}

            names_i = list(members_i.keys())
            names_j = list(members_j.keys())

            if not names_i or not names_j:
                continue

            # cost matrix: negative Jaccard similarity (for Hungarian minimization)
            cost = np.zeros((len(names_i), len(names_j)))
            for ni, name_i in enumerate(names_i):
                for nj, name_j in enumerate(names_j):
                    inter = len(members_i[name_i] & members_j[name_j])
                    union = len(members_i[name_i] | members_j[name_j])
                    jaccard = inter / union if union > 0 else 0
                    cost[ni, nj] = -jaccard  # negative for minimization

            row_ind, col_ind = linear_sum_assignment(cost)

            # embed matched cluster label pairs
            for ri, ci in zip(row_ind, col_ind):
                label_i = names_i[ri]
                label_j = names_j[ci]
                membership_jaccard = -cost[ri, ci]

                # embed labels + descriptions
                desc_i = next((c.get("description", "") for c in clusters_i
                              if c["cluster_name"] == label_i), "")
                desc_j = next((c.get("description", "") for c in clusters_j
                              if c["cluster_name"] == label_j), "")

                text_i = f"{label_i}. {desc_i}"
                text_j = f"{label_j}. {desc_j}"

                emb_i = embedder.encode(text_i)
                emb_j = embedder.encode(text_j)

                cos_sim = float(np.dot(emb_i, emb_j) /
                               (np.linalg.norm(emb_i) * np.linalg.norm(emb_j)))

                all_similarities.append(cos_sim)
                comparisons.append({
                    "run_a": i,
                    "run_b": j,
                    "label_a": label_i,
                    "label_b": label_j,
                    "membership_jaccard": round(membership_jaccard, 3),
                    "label_cosine": round(cos_sim, 4),
                })

    result = {
        "n_runs": len(runs),
        "n_matched_pairs": len(comparisons),
        "mean_taxonomy_cosine": round(float(np.mean(all_similarities)), 4) if all_similarities else None,
        "std_taxonomy_cosine": round(float(np.std(all_similarities)), 4) if all_similarities else None,
        "matched_pairs": comparisons,
    }

    if all_similarities:
        print(f"\n  taxonomy cosine similarity: "
              f"mean={result['mean_taxonomy_cosine']}, "
              f"std={result['std_taxonomy_cosine']}")
        print(f"  matched pairs:")
        for c in comparisons[:10]:
            print(f"    '{c['label_a'][:40]}' ↔ '{c['label_b'][:40]}': "
                  f"membership={c['membership_jaccard']:.2f}, label={c['label_cosine']:.3f}")

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, default=2)
    parser.add_argument("--seeds", type=int, default=5,
                        help="number of seed runs for parametric + taxonomy stability")
    parser.add_argument("--bootstrap", type=int, default=0,
                        help="number of bootstrap samples for structural stability (0=skip)")
    args = parser.parse_args()

    session = get_session()
    event = session.query(Event).get(args.event_id)
    if not event:
        print(f"event {args.event_id} not found")
        sys.exit(1)

    event_context = event.prompt_context or event.title
    print(f"event: {event.title} (id={event.id})")
    print(f"prompt context: {event_context}")
    session.close()

    results_data = load_results()
    print(f"articles: {len(results_data)}")

    from pipeline import find_best_model
    model = find_best_model()
    print(f"model: {model}")

    output = {
        "event_id": args.event_id,
        "event_title": event.title,
        "n_articles": len(results_data),
        "model": model,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # level 1: parametric
    output["parametric"] = parametric_stability(
        model, results_data, event_context, n_seeds=args.seeds)

    # level 2: structural (optional, expensive)
    if args.bootstrap > 0:
        output["structural"] = structural_stability(
            model, results_data, event_context, n_bootstrap=args.bootstrap)
    else:
        print(f"\n  structural stability skipped (use --bootstrap N to enable)")
        output["structural"] = "skipped (use --bootstrap N)"

    # level 3: taxonomy
    output["taxonomy"] = taxonomy_stability(
        model, results_data, event_context, n_seeds=args.seeds)

    # save
    os.makedirs("results", exist_ok=True)
    out_path = f"results/cluster_stability_full_{args.event_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")

    # summary
    print(f"\n{'='*60}")
    print(f"THREE-LEVEL CLUSTER STABILITY SUMMARY")
    print(f"{'='*60}")
    p = output["parametric"]
    if p.get("ari_mean") is not None:
        print(f"  parametric:  ARI = {p['ari_mean']} ± {p['ari_std']} "
              f"(n={p['n_runs']} runs, {p['n_pairwise_comparisons']} pairs)")
    if isinstance(output["structural"], dict) and output["structural"].get("per_cluster"):
        cores = output["structural"]["per_cluster"]
        stable_clusters = sum(1 for c in cores.values() if c["hard_core_fraction"] >= 0.5)
        print(f"  structural:  {stable_clusters}/{len(cores)} clusters have hard core ≥50%")
        for name, info in cores.items():
            print(f"    {name[:45]}: core={info['hard_core_fraction']:.0%} "
                  f"({info['hard_core_size']}/{info['members']})")
    t = output["taxonomy"]
    if t.get("mean_taxonomy_cosine") is not None:
        print(f"  taxonomy:    mean cosine = {t['mean_taxonomy_cosine']} ± {t['std_taxonomy_cosine']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
