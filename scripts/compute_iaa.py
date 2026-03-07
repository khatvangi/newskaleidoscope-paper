#!/usr/bin/env python3
"""
compute_iaa.py — inter-annotator agreement for human validation.

takes completed annotation CSVs from 2+ annotators and computes:
- Krippendorff's alpha per dimension (register, position_types)
- BERTScore distribution for framing_description
- LLM-vs-human faithfulness rate per language
- bootstrap 95% confidence intervals on all metrics

no DB dependency — runs from CSVs alone.

usage:
  python3 scripts/compute_iaa.py \
    --annotations validation/annotations_A.csv validation/annotations_B.csv \
    [--llm-column llm_primary_frame]

input CSV columns expected per annotator:
  article_id, framing_description, position_types, register,
  embedded_assumptions, human_agrees_with_llm, annotator_notes

position_types and embedded_assumptions are semicolon-delimited strings.
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_annotations(csv_path):
    """load annotation CSV into list of dicts, keyed by article_id."""
    annotations = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            art_id = int(row["article_id"])
            # parse semicolon-delimited set fields
            position_types = set()
            if row.get("position_types", "").strip():
                position_types = {s.strip() for s in row["position_types"].split(";")}
            assumptions = set()
            if row.get("embedded_assumptions", "").strip():
                assumptions = {s.strip() for s in row["embedded_assumptions"].split(";")}

            annotations[art_id] = {
                "article_id": art_id,
                "framing_description": row.get("framing_description", "").strip(),
                "position_types": position_types,
                "register": row.get("register", "").strip(),
                "embedded_assumptions": assumptions,
                "human_agrees_with_llm": row.get("human_agrees_with_llm", "").strip(),
                "language": row.get("language", "").strip(),
            }
    return annotations


def masi_distance(set_a, set_b):
    """MASI (Measuring Agreement on Set-valued Items) distance.
    returns value in [0, 1] where 0 = identical sets.
    used with Krippendorff's alpha for multi-label annotations."""
    if not set_a and not set_b:
        return 0.0
    if not set_a or not set_b:
        return 1.0

    intersection = set_a & set_b
    union = set_a | set_b

    if set_a == set_b:
        return 0.0
    elif set_a.issubset(set_b) or set_b.issubset(set_a):
        jaccard = len(intersection) / len(union) if union else 0
        return 1.0 - jaccard * (2.0 / 3.0)
    elif intersection:
        jaccard = len(intersection) / len(union) if union else 0
        return 1.0 - jaccard * (1.0 / 3.0)
    else:
        return 1.0


def compute_krippendorff_alpha_nominal(all_annotations, dimension):
    """Krippendorff's alpha for nominal (single-label) dimension."""
    import krippendorff

    # find common articles
    common_ids = set(all_annotations[0].keys())
    for ann in all_annotations[1:]:
        common_ids &= set(ann.keys())
    common_ids = sorted(common_ids)

    if len(common_ids) < 5:
        return None, 0

    # build reliability data matrix: annotators × items
    # encode as integers for nominal alpha
    label_to_int = {}
    reliability_data = []

    for ann in all_annotations:
        row = []
        for art_id in common_ids:
            label = ann[art_id].get(dimension, "")
            if not label:
                row.append(np.nan)
            else:
                if label not in label_to_int:
                    label_to_int[label] = len(label_to_int)
                row.append(label_to_int[label])
        reliability_data.append(row)

    reliability_data = np.array(reliability_data, dtype=float)

    try:
        alpha = krippendorff.alpha(reliability_data=reliability_data,
                                   level_of_measurement="nominal")
        return alpha, len(common_ids)
    except Exception as e:
        print(f"  krippendorff alpha failed for {dimension}: {e}")
        return None, len(common_ids)


def compute_krippendorff_alpha_masi(all_annotations, dimension):
    """Krippendorff's alpha with MASI distance for set-valued dimensions."""
    # find common articles
    common_ids = set(all_annotations[0].keys())
    for ann in all_annotations[1:]:
        common_ids &= set(ann.keys())
    common_ids = sorted(common_ids)

    if len(common_ids) < 5:
        return None, 0

    # compute observed disagreement
    n_annotators = len(all_annotations)
    n_items = len(common_ids)

    # pairwise MASI distances
    total_distance = 0.0
    n_pairs = 0

    for art_id in common_ids:
        for i in range(n_annotators):
            for j in range(i + 1, n_annotators):
                set_i = all_annotations[i][art_id].get(dimension, set())
                set_j = all_annotations[j][art_id].get(dimension, set())
                if set_i or set_j:  # skip if both empty
                    total_distance += masi_distance(set_i, set_j)
                    n_pairs += 1

    if n_pairs == 0:
        return None, n_items

    observed_disagreement = total_distance / n_pairs

    # expected disagreement: pool all sets, compute average MASI between random pairs
    all_sets = []
    for ann in all_annotations:
        for art_id in common_ids:
            s = ann[art_id].get(dimension, set())
            if s:
                all_sets.append(s)

    if len(all_sets) < 2:
        return None, n_items

    # sample expected disagreement (full computation is O(n^2))
    rng = np.random.default_rng(42)
    n_samples = min(10000, len(all_sets) * (len(all_sets) - 1) // 2)
    expected_total = 0.0
    for _ in range(n_samples):
        i, j = rng.choice(len(all_sets), size=2, replace=False)
        expected_total += masi_distance(all_sets[i], all_sets[j])
    expected_disagreement = expected_total / n_samples

    if expected_disagreement == 0:
        return 1.0, n_items  # perfect agreement

    alpha = 1.0 - observed_disagreement / expected_disagreement
    return alpha, n_items


def compute_bertscore_iaa(all_annotations, dimension="framing_description"):
    """BERTScore between annotator framing descriptions."""
    from bert_score import score as bert_score

    common_ids = set(all_annotations[0].keys())
    for ann in all_annotations[1:]:
        common_ids &= set(ann.keys())
    common_ids = sorted(common_ids)

    # collect all pairwise (annotator_i, annotator_j) description pairs
    refs = []
    cands = []
    pair_meta = []  # (art_id, annotator_i, annotator_j)

    for art_id in common_ids:
        for i in range(len(all_annotations)):
            for j in range(i + 1, len(all_annotations)):
                text_i = all_annotations[i][art_id].get(dimension, "")
                text_j = all_annotations[j][art_id].get(dimension, "")
                if text_i.strip() and text_j.strip():
                    refs.append(text_i)
                    cands.append(text_j)
                    pair_meta.append((art_id, i, j))

    if not refs:
        return None, []

    # compute BERTScore
    P, R, F1 = bert_score(cands, refs, lang="en", verbose=False,
                          model_type="microsoft/deberta-xlarge-mnli")

    f1_scores = F1.numpy().tolist()
    return {
        "mean": float(np.mean(f1_scores)),
        "median": float(np.median(f1_scores)),
        "std": float(np.std(f1_scores)),
        "min": float(np.min(f1_scores)),
        "max": float(np.max(f1_scores)),
        "n_pairs": len(f1_scores),
    }, f1_scores


def compute_llm_faithfulness(all_annotations):
    """LLM-vs-human faithfulness rate per language."""
    by_lang = defaultdict(lambda: {"total": 0, "agree": 0, "partial": 0, "disagree": 0, "unclear": 0})
    overall = {"total": 0, "agree": 0, "partial": 0, "disagree": 0, "unclear": 0}

    for ann in all_annotations:
        for art_id, data in ann.items():
            verdict = data.get("human_agrees_with_llm", "").lower().strip()
            lang = data.get("language", "Unknown")

            if verdict not in ("agree", "partial", "disagree", "unclear"):
                continue

            by_lang[lang]["total"] += 1
            by_lang[lang][verdict] += 1
            overall["total"] += 1
            overall[verdict] += 1

    return overall, dict(by_lang)


def bootstrap_ci(values, n_bootstrap=1000, ci=0.95):
    """bootstrap confidence interval for a statistic."""
    if not values:
        return None, None
    rng = np.random.default_rng(42)
    boot_means = []
    for _ in range(n_bootstrap):
        sample = rng.choice(values, size=len(values), replace=True)
        boot_means.append(np.mean(sample))

    lower = np.percentile(boot_means, (1 - ci) / 2 * 100)
    upper = np.percentile(boot_means, (1 + ci) / 2 * 100)
    return float(lower), float(upper)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", nargs="+", required=True,
                        help="paths to annotator CSV files")
    parser.add_argument("--skip-bertscore", action="store_true",
                        help="skip BERTScore computation (slow)")
    args = parser.parse_args()

    # load all annotations
    all_annotations = []
    for path in args.annotations:
        ann = load_annotations(path)
        print(f"loaded {len(ann)} annotations from {path}")
        all_annotations.append(ann)

    print(f"\n{len(all_annotations)} annotators loaded")

    # find common articles
    common_ids = set(all_annotations[0].keys())
    for ann in all_annotations[1:]:
        common_ids &= set(ann.keys())
    print(f"common articles: {len(common_ids)}")

    results = {
        "n_annotators": len(all_annotations),
        "n_common_articles": len(common_ids),
    }

    # 1. Krippendorff's alpha for register (nominal)
    print(f"\n--- register (Krippendorff's alpha, nominal) ---")
    alpha_register, n_register = compute_krippendorff_alpha_nominal(
        all_annotations, "register")
    if alpha_register is not None:
        print(f"  alpha = {alpha_register:.4f} (n={n_register})")
        interpretation = ("substantial" if alpha_register >= 0.67
                         else "moderate" if alpha_register >= 0.33
                         else "low")
        print(f"  interpretation: {interpretation}")
    results["register_alpha"] = alpha_register

    # 2. Krippendorff's alpha with MASI for position_types
    print(f"\n--- position_types (Krippendorff's alpha, MASI distance) ---")
    alpha_positions, n_positions = compute_krippendorff_alpha_masi(
        all_annotations, "position_types")
    if alpha_positions is not None:
        print(f"  alpha = {alpha_positions:.4f} (n={n_positions})")
    results["position_types_alpha_masi"] = alpha_positions

    # 3. Krippendorff's alpha with MASI for embedded_assumptions
    print(f"\n--- embedded_assumptions (Krippendorff's alpha, MASI distance) ---")
    alpha_assumptions, n_assumptions = compute_krippendorff_alpha_masi(
        all_annotations, "embedded_assumptions")
    if alpha_assumptions is not None:
        print(f"  alpha = {alpha_assumptions:.4f} (n={n_assumptions})")
    results["assumptions_alpha_masi"] = alpha_assumptions

    # 4. BERTScore for framing_description
    if not args.skip_bertscore:
        print(f"\n--- framing_description (BERTScore F1) ---")
        bertscore_stats, bertscore_values = compute_bertscore_iaa(all_annotations)
        if bertscore_stats:
            print(f"  mean F1 = {bertscore_stats['mean']:.4f}")
            print(f"  median F1 = {bertscore_stats['median']:.4f}")
            print(f"  std = {bertscore_stats['std']:.4f}")
            print(f"  range = [{bertscore_stats['min']:.4f}, {bertscore_stats['max']:.4f}]")

            # bootstrap CI
            ci_lower, ci_upper = bootstrap_ci(bertscore_values)
            if ci_lower is not None:
                print(f"  95% CI: [{ci_lower:.4f}, {ci_upper:.4f}]")
                bertscore_stats["ci_95_lower"] = ci_lower
                bertscore_stats["ci_95_upper"] = ci_upper

            results["framing_bertscore"] = bertscore_stats
        else:
            print("  no valid pairs for BERTScore")
            results["framing_bertscore"] = None
    else:
        results["framing_bertscore"] = "skipped"

    # 5. LLM-vs-human faithfulness
    print(f"\n--- LLM faithfulness (human_agrees_with_llm) ---")
    overall_faith, by_lang_faith = compute_llm_faithfulness(all_annotations)
    if overall_faith["total"] > 0:
        agree_rate = (overall_faith["agree"] + overall_faith["partial"]) / overall_faith["total"]
        print(f"  overall: {overall_faith}")
        print(f"  agree+partial rate: {agree_rate:.1%}")

        print(f"\n  per-language:")
        for lang, stats in sorted(by_lang_faith.items(), key=lambda x: -x[1]["total"]):
            rate = (stats["agree"] + stats["partial"]) / stats["total"] if stats["total"] > 0 else 0
            print(f"    {lang}: {stats['total']} articles, "
                  f"agree+partial={rate:.1%}, disagree={stats['disagree']}")

        # bootstrap CI on faithfulness
        faith_values = []
        for ann in all_annotations:
            for art_id, data in ann.items():
                v = data.get("human_agrees_with_llm", "").lower().strip()
                if v in ("agree", "partial"):
                    faith_values.append(1.0)
                elif v == "disagree":
                    faith_values.append(0.0)
        ci_lower, ci_upper = bootstrap_ci(faith_values)
        if ci_lower is not None:
            print(f"\n  faithfulness 95% CI: [{ci_lower:.4f}, {ci_upper:.4f}]")
            overall_faith["ci_95_lower"] = ci_lower
            overall_faith["ci_95_upper"] = ci_upper

    results["llm_faithfulness_overall"] = overall_faith
    results["llm_faithfulness_by_language"] = by_lang_faith

    # save
    os.makedirs("results", exist_ok=True)
    out_path = "results/iaa_results.json"
    # convert sets to lists for JSON serialization
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nsaved: {out_path}")


if __name__ == "__main__":
    main()
