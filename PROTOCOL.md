# Analysis Protocol — NewsKaleidoscope

**Purpose**: prevent drift across sessions. Every step has a verification gate.

---

## Phase 1: Translation Verification

**Goal**: all non-English articles have English translations.

```bash
# check: zero untranslated (excluding flagged articles)
PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope -c "
SELECT event_id, COUNT(*) as untranslated
FROM articles
WHERE (translated_text IS NULL OR translated_text = '')
  AND raw_text IS NOT NULL AND raw_text != ''
  AND (needs_human_review IS NULL OR needs_human_review = false)
GROUP BY event_id;
"
# GATE: query returns 0 rows
```

**Scripts**: `scripts/translate_missing.py`, `scripts/retranslate_nllb.py`

---

## Phase 2: Pass 1 — Per-Article Framing (Qwen)

**Goal**: every analyzable article has a primary frame extraction via Qwen.

**Requires**: llama-server on boron with qwen3-32b-q4km.gguf

```bash
# run
python3 pipeline.py  # or pipeline.py N for test batch

# check: all analyzable articles have at least one analysis row
PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope -c "
SELECT
  (SELECT COUNT(*) FROM articles WHERE event_id = EVENT_ID
   AND (needs_human_review IS NULL OR needs_human_review = false)) as analyzable,
  (SELECT COUNT(DISTINCT article_id) FROM analyses WHERE event_id = EVENT_ID) as analyzed;
"
# GATE: analyzed >= analyzable
```

---

## Phase 3: Council Run (Gemma + Mistral + Qwen)

**Goal**: multi-model verdicts for all articles. 3 models x N articles.

**Requires**: llama-server on boron (council.py manages model swapping)

**Time estimate**: ~3 models × ~1,150 articles × ~15s/article ≈ 14 hours for CS1

```bash
# run (kills and restarts llama-server per model automatically)
python3 council.py --event-id EVENT_ID

# check
PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope -c "
SELECT confidence_level, COUNT(*) as cnt
FROM llm_council_verdicts v
JOIN articles a ON a.id = v.article_id
WHERE a.event_id = EVENT_ID
GROUP BY confidence_level ORDER BY cnt DESC;
"
# GATE: total verdicts ≈ total analyzable articles
# expected distribution: ~40-50% high, ~20% medium, ~30-35% contested
```

**Comparison baseline (CS1 previous 106-article run)**:
```sql
-- compare new vs old distribution
SELECT confidence_level, COUNT(*) FROM llm_council_verdicts
WHERE article_id IN (SELECT id FROM articles WHERE event_id = 2)
GROUP BY confidence_level;
```

---

## Phase 4: Pass 2 — Clustering

**Goal**: emergent clusters from full-corpus framing descriptions. New run_id, old clusters preserved.

**Requires**: llama-server on boron with qwen3 (for LLM clustering prompt)

```bash
# run with new run_id
python3 scripts/recluster.py --event-id EVENT_ID --run-id "full_corpus_YYYYMMDD"

# check
PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope -c "
SELECT run_id, COUNT(*) as clusters,
  (SELECT COUNT(*) FROM cluster_memberships cm WHERE cm.cluster_id IN
    (SELECT id FROM clusters c WHERE c.run_id = cl.run_id)) as memberships
FROM clusters cl
WHERE event_id = EVENT_ID
GROUP BY run_id ORDER BY run_id;
"
# GATE: new run_id present, old run_ids untouched
# GATE: memberships ≈ total analyzed articles (every article assigned)
```

---

## Phase 5: Cluster Stability

**Goal**: measure how stable clusters are across methods/runs.

```bash
python3 scripts/cluster_stability_full.py --event-id EVENT_ID

# GATE: global ARI reported, per-cluster stability table generated
# expect: ARI > 0.3 is acceptable, > 0.5 is good
# named clusters with stability >= 50% are "real"
```

---

## Phase 6: Inter-Model Divergence

**Goal**: measure where models disagree — these are the interesting epistemic fault lines.

```bash
python3 scripts/inter_model_divergence_semantic.py --event-id EVENT_ID

# check output: agreement distribution
# GATE: report generated with high/medium/contested percentages
# compare to CS1 baseline: 45.3% high, 20.8% medium, 34.0% contested
```

---

## Phase 7: Absence Report

**Goal**: identify structurally missing perspectives, voiceless populations, unspeakable positions.

```bash
python3 absence_report.py --event-id EVENT_ID

# GATE: absence report written to analysis/ with new timestamp
# must identify: missing actors, unrepresented regions, taboo positions
```

---

## Phase 8: HTML Report Generation

**Goal**: static page for Cloudflare Pages deployment.

```bash
python3 generate_report.py --event-id EVENT_ID

# CS1: docs/events/iran-march-2026/index.html
# CS2: docs/events/tariffs-april-2026/index.html

# GATE: page loads in browser, clusters render, absence section present
```

---

## Phase 9: Human Validation

**Goal**: ground-truth annotation of stratified 30-article sample.

```bash
# generate sample (already done for CS1)
python3 scripts/human_validation_scaffold.py --event-id EVENT_ID

# GATE: CSV with annotations for agreement, disputed, singleton articles
# compute: annotator-vs-pipeline agreement rate (target > 70%)
```

---

## Immutability Checks (run before AND after each phase)

```bash
# row counts snapshot
PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope -c "
SELECT 'articles' as tbl, COUNT(*) FROM articles WHERE event_id = EVENT_ID
UNION ALL SELECT 'analyses', COUNT(*) FROM analyses WHERE event_id = EVENT_ID
UNION ALL SELECT 'verdicts', COUNT(*) FROM llm_council_verdicts v
  JOIN articles a ON a.id = v.article_id WHERE a.event_id = EVENT_ID
UNION ALL SELECT 'clusters', COUNT(*) FROM clusters WHERE event_id = EVENT_ID
UNION ALL SELECT 'memberships', COUNT(*) FROM cluster_memberships cm
  JOIN clusters c ON c.id = cm.cluster_id WHERE c.event_id = EVENT_ID;
"
# RULE: counts can only go UP between phases. if any count drops, STOP.
```

---

## Execution Order

| # | Phase | Depends On | GPU | Duration |
|---|-------|-----------|-----|----------|
| 1 | Translation | — | nitrogen (local) | minutes |
| 2 | Pass 1 | translation | boron (qwen) | hours |
| 3 | Council | Pass 1 | boron (3 models) | ~14h CS1, ~5h CS2 |
| 4 | Clustering | Pass 1 | boron (qwen) | ~30 min |
| 5 | Stability | Phase 4 | nitrogen (CPU) | minutes |
| 6 | Divergence | Phase 3 | nitrogen (CPU) | minutes |
| 7 | Absence | Phase 4 | boron (qwen) | ~30 min |
| 8 | HTML report | Phases 4-7 | — | seconds |
| 9 | Validation | Phase 8 | human | days |

---

## CS1 vs CS2 Sequence

Run CS1 fully through Phase 6 first (comparison to existing 106-article baseline).
Then CS2 Phases 2-8 (fresh, no baseline to compare against).

**Do not interleave** — boron can only run one model at a time.
