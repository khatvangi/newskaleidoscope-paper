# Similarity Thresholds and Consensus Logic

Source: `council.py` (lines 245-297) and `scripts/sample_council.py` (lines 264-358)

## Similarity Threshold

```python
SIMILARITY_THRESHOLD = 0.82
```

Cosine similarity between sentence embeddings of `primary_frame` outputs from different models. Computed using `all-MiniLM-L6-v2` from `sentence-transformers`.

## Confidence Levels

### Full Council (3 models)

| Level | Condition |
|-------|-----------|
| **HIGH** | All pairwise similarities >= 0.82 (all 3 models agree) |
| **MEDIUM** | At least one pair has similarity >= 0.82 (2-of-3 agree, dissenter identified) |
| **CONTESTED** | No pair reaches similarity >= 0.82 (no agreement) |
| **LOW** | Only 1 valid reading (other models failed) |
| **FAILED** | 0 valid readings |

### Sample Council (2 models — Qwen vs Gemma)

| Level | Condition |
|-------|-----------|
| **HIGH** | similarity >= 0.82 |
| **MEDIUM** | 0.65 <= similarity < 0.82 |
| **CONTESTED** | similarity < 0.65, or missing frame from either model |

Source: `scripts/sample_council.py` lines 311-319

## Consensus Logic: `determine_consensus()`

Exact implementation from `council.py` lines 247-297:

```python
SIMILARITY_THRESHOLD = 0.82

def determine_consensus(readings):
    """determine consensus across model readings.

    readings: dict of model_name -> parsed JSON output

    returns: (confidence_level, consensus_frame, dissenting_model)
    """
    valid = {k: v for k, v in readings.items() if v is not None}
    if len(valid) < 2:
        # can't determine consensus with < 2 valid readings
        if len(valid) == 1:
            model_name, data = list(valid.items())[0]
            return ("low", data.get("primary_frame", ""), None)
        return ("failed", "", None)

    model_names = list(valid.keys())
    frames = {k: v.get("primary_frame", "") for k, v in valid.items()}

    # compute pairwise similarity
    pairs = {}
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            a, b = model_names[i], model_names[j]
            sim = compute_similarity(frames[a], frames[b])
            pairs[(a, b)] = sim

    # check for all-agree
    all_above = all(s >= SIMILARITY_THRESHOLD for s in pairs.values())
    if all_above and len(valid) >= 3:
        # pick frame from highest confidence model
        best_model = max(valid.keys(),
                         key=lambda k: valid[k].get("confidence_score", 0))
        return ("high", frames[best_model], None)

    # check for 2-of-3 agreement
    if len(valid) >= 3:
        for (a, b), sim in pairs.items():
            if sim >= SIMILARITY_THRESHOLD:
                # a and b agree, find the dissenter
                dissenter = [m for m in model_names if m != a and m != b]
                dissenter = dissenter[0] if dissenter else None
                # pick frame from higher-confidence model of the agreeing pair
                if valid[a].get("confidence_score", 0) >= valid[b].get("confidence_score", 0):
                    consensus = frames[a]
                else:
                    consensus = frames[b]
                return ("medium", consensus, dissenter)

    # no agreement
    return ("contested", "", None)
```

## Consensus Frame Selection

- **HIGH**: frame text taken from the model with the highest self-reported `confidence_score`
- **MEDIUM**: frame text taken from the higher-confidence model within the agreeing pair
- **CONTESTED**: no consensus frame; each model's reading is preserved as a separate analysis row in the DB, and the article is flagged for human review (`needs_human_review = True`)

## DB Handling by Confidence Level

| Level | Analysis rows written | Council verdict |
|-------|----------------------|-----------------|
| HIGH | 1 row, `model_used = "council_high"` | `models_agree = True` |
| MEDIUM | 1 row, `model_used = "council_medium"` | `models_agree = False`, `dissent_recorded = True` |
| CONTESTED | 1 row per model, `model_used = "council_contested:<model_name>"` | `models_agree = False` |

## Observed Distributions

### CS1 — Iran Strike (full council, 3 models, N=1,267)
- HIGH: 60 (4.7%)
- MEDIUM: 476 (37.6%)
- CONTESTED: 731 (57.7%)

### CS1-RU — Ukraine 2022 (sample council, 2 models, N=307)
- HIGH: 41 (13.4%)
- MEDIUM: 223 (72.6%)
- CONTESTED: 43 (14.0%)

Cross-case finding: Ukraine framing showed 4x higher inter-model agreement than Iran, suggesting geopolitical consensus correlates with framing consensus.
