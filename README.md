# NewsKaleidoscope

**Epistemic Mapping of Global News Coverage**

An open-source system that takes a single geopolitical event and produces a structured map of how different regions, cultures, and institutions frame that event — using multilingual corpus analysis, LLM-based framing extraction, and emergent clustering.

## What This Does

Given an event (e.g., military strikes on Iran, US tariff announcements), NewsKaleidoscope:

1. **Ingests** articles from 6+ APIs across 25+ languages and 80+ countries
2. **Extracts** original-language framing before translation (preserving epistemic vocabulary)
3. **Analyzes** each article's framing using a 3-model LLM council (no predefined categories)
4. **Clusters** framings into emergent positions that arise from the data itself
5. **Reports** structural absences: who isn't being heard, and what positions are unspeakable

## Case Studies

| # | Event | Type | Articles | Languages | Countries |
|---|-------|------|----------|-----------|-----------|
| CS1 | US-Israeli Strikes on Iran (Mar 2026) | Military | 1,700+ | 25+ | 60+ |
| CS2 | US Reciprocal Tariffs (Apr 2025) | Economic | 1,500+ | 27+ | 84+ |
| CS3 | US Midterm Elections (Nov 2026) | Political | Planned | — | — |

## Corpus Versioning

Each case study's corpus grows incrementally as new APIs and languages are added. Pipeline runs are tagged with a `corpus_version` to ensure reproducibility.

| CS | Version | Date | Articles | Sources | Notes |
|----|---------|------|----------|---------|-------|
| CS1 | v1 | 2026-03-01 | 121 | GDELT only | initial GDELT pull, 18 languages |
| CS1 | v2 | 2026-03-05 | 1,317 | GDELT + World News + Reddit | multilingual expansion: Arabic, Persian, Hindi, French, etc. |
| CS1 | v3 | 2026-03-07 | ~1,700 | + overnight cron pulls | ongoing daily ingestion |
| CS2 | v1 | 2026-03-06 | 441 | GDELT (5 windows) | 84 countries, 29 languages |
| CS2 | v2 | 2026-03-06 | ~1,010 | + MarketAux + Reddit | financial layer (212 articles, 424 tickers) |
| CS2 | v3 | 2026-03-07 | ~1,500 | + World News multilingual | ongoing daily ingestion |

**Important**: Analysis results (clusters, absence reports) are always tagged with the corpus version and run_id they were produced from. Old runs are never overwritten — they stay in the DB alongside new ones for comparison. See the Immutability Rules in CLAUDE.md.

## Architecture

```
ingestion (6 APIs)          analysis (LLM on GPU)        output
─────────────────           ─────────────────────        ──────
gdelt_pull.py        ─┐
worldnews_ingest.py   │    pipeline.py                   docs/index.html
newsdata_ingest.py    ├──► (pass 1: per-article framing  (static HTML,
marketaux_ingest.py   │     pass 2: emergent clustering   Cloudflare Pages)
reddit_ingest.py      │     absence report)
archive_fetcher.py   ─┘
```

## Data Sources

| Source | Coverage | API Key Required | Notes |
|--------|----------|-----------------|-------|
| GDELT | 65 languages, global | No | Gap-fill, machine-translated metadata |
| World News API | 80+ languages, 210+ countries | Yes (free tier) | Returns full article text |
| API League | Same backend as World News | Yes (free tier) | Separate quota, auto-failover |
| NewsData.io | 89 languages | Yes (free tier) | 48h lookback on free tier |
| MarketAux | Financial news, ticker-tagged | Yes (free tier) | CS2 only, different epistemic layer |
| Reddit | Country-specific subreddits | No | Vernacular discourse |
| archive.org | Historical web pages | No | Wayback Machine fallback for failed fetches |

## Reproducing the Analysis

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Two-GPU server for LLM inference (we use 2x TITAN RTX 48GB with llama.cpp)
- API keys (free tiers sufficient): World News API, NewsData.io, MarketAux

### Setup

```bash
git clone https://github.com/khatvangi/newskaleidoscope-paper.git
cd newskaleidoscope-paper

pip install trafilatura psycopg2-binary sentence-transformers

export WORLDNEWS_API_KEY="your_key"
export NEWSDATA_API_KEY="your_key"
export MARKETAUX_API_KEY="your_key"

# set up PostgreSQL (see db.py for schema)
createdb newskaleidoscope
python3 -c "from db import Base, engine; Base.metadata.create_all(engine)"
```

### Ingestion

```bash
python3 gdelt_pull.py                        # GDELT articles
python3 worldnews_ingest.py cs1_iran         # multilingual (World News API)
python3 marketaux_ingest.py cs2_tariffs      # financial layer (CS2)
python3 reddit_ingest.py cs1_iran            # vernacular discourse
```

### Analysis

```bash
# start LLM server (requires llama.cpp + 32B+ model)
llama-server --model qwen3-32b-q4km.gguf --tensor-split 0.5,0.5 \
  --host 0.0.0.0 --port 11434 --ctx-size 16384 --n-gpu-layers 99

python3 pipeline.py --event-id 2    # CS1: Iran
python3 pipeline.py --event-id 3    # CS2: Tariffs
python3 output_generator.py         # generate HTML report
```

## Methods

### Prompt Parameterization

All LLM prompts are event-agnostic templates. Event-specific context (e.g., "US-Israel military action against Iran" or "US reciprocal tariffs on trading partners") is stored in the `events` table and injected at runtime via `{event_context}`. No prompt contains hardcoded event references. New case studies require only an INSERT into `events` with `prompt_context` and `absence_examples` — no code changes.

### Two-Pass Analysis

**Pass 1** (per-article): Open-ended framing description using the article's own conceptual vocabulary. Extracts authority structure, historical context, unstated assumptions, internal tensions, and absence flags. Non-English articles get original-language framing terms extracted before Helsinki-NLP translation.

**Pass 2** (post-corpus): Full framing descriptions (not truncated) are fed to the clustering prompt. The LLM identifies emergent clusters from the data itself — no predefined categories. Singletons (articles that resist clustering) are preserved.

### LLM Council

Three models — Qwen3-32B, Gemma-27B-IT, Mistral-Small-24B — independently analyze each article. Agreement is measured by cosine similarity on sentence embeddings (`paraphrase-multilingual-mpnet-base-v2`), not exact string match. Threshold: mean pairwise cosine similarity ≥ 0.75.

| Confidence | CS1 Count | Description |
|------------|-----------|-------------|
| High | 48 (45.3%) | All 3 model pairs above threshold |
| Medium | 22 (20.8%) | 2 of 3 pairs above threshold |
| Contested | 36 (34.0%) | Genuine semantic divergence across models |

Mean pairwise similarity: 0.785 (median 0.801). Model pair alignment: Qwen-Gemma (0.795) > Qwen-Mistral (0.782) > Gemma-Mistral (0.778). Agreement is lowest for Arabic (0.670) and Romanian (0.570) articles, likely reflecting training data gaps for non-Western political text in smaller models.

### Cluster Stability

Cluster assignments are method-sensitive. Pairwise comparison of clustering runs on CS1 (106 articles):

| Comparison | Common Articles | ARI | Interpretation |
|------------|----------------|-----|----------------|
| LLM full-desc vs LLM truncated | 45 | 0.45 | Moderate — core clusters stable, boundary articles shift |
| LLM full-desc vs embedding | 53 | 0.03 | Near-zero — "similar topic" ≠ "similar framing" |
| LLM truncated vs embedding | 57 | 0.07 | Near-zero — validates LLM over embedding for framing |

The near-zero ARI between embedding-based and LLM-based clustering validates the methodological choice: sentence embeddings capture topical similarity, not epistemic framing.

### Human Validation

A stratified sample of 60 articles is provided for human annotation (`results/human_validation_sample_2.csv`). The sample overrepresents contested articles and non-English articles to stress-test the pipeline's weakest points.

**Annotation protocol:** A formal annotation schema (`validation/annotation_schema.md`) operationalizes four dimensions — framing_description, position_types, register, embedded_assumptions — with definitions, positive/negative examples, and conflict resolution rules. A 5-article pilot with two annotators precedes the main round to validate the schema and calibrate annotator understanding (`validation/pilot_protocol.md`).

**Agreement metrics:** Krippendorff's alpha (nominal) for register, Krippendorff's alpha with MASI distance for set-valued position_types and embedded_assumptions, BERTScore F1 for free-text framing_description. All metrics include bootstrap 95% confidence intervals. Computed via `scripts/compute_iaa.py` from annotator CSVs with no DB dependency.

### Cross-Event Validation

A taxonomy transfer protocol (`scripts/taxonomy_transfer.py`) formally measures whether the cluster structure discovered in CS1 generalizes to CS2. The protocol:

1. **Pre-registration** (`results/cs2_preregistration.md`): predictions about which CS1 cluster types will appear in CS2, written before any CS2 analysis runs. Forces CS2 to function as a hypothesis test, not just another run.
2. **Centroid matching**: cluster centroids (mean of member article framing embeddings) from both events are matched using the Hungarian algorithm on cosine similarity. Transfer threshold: cosine ≥ 0.70 = cluster present in target event.
3. **Transfer rate**: fraction of CS1 clusters with a CS2 analogue above threshold. Novel CS2 clusters with no CS1 analogue are separately reported — these demonstrate the framework's ability to discover new frames, not just reproduce existing ones.

CS2 analysis results pending. The pre-registration predicts 3 of 5 CS1 clusters will have structural analogues in CS2, 2 will be absent, and at least 2 novel clusters will emerge from the financial press layer.

### Cluster Stability (Three-Level Analysis)

Cluster stability is decomposed into three distinct types, each with different methodological implications:

1. **Parametric stability**: ARI across N seed runs (mean ± std). Measures sensitivity to LLM non-determinism.
2. **Structural stability**: Bootstrap resampling (100× at 80% corpus). For each cluster, identifies the "hard core" — members with pairwise co-occurrence ≥ 0.8 across subsamples. Hard core fraction = structural robustness of the cluster.
3. **Taxonomy stability**: Cluster labels embedded via sentence transformer, matched across runs by membership overlap (Hungarian algorithm), cosine similarity of label embeddings for matched pairs. Measures whether the LLM's verbal characterization is consistent even when cluster membership shifts.

Full results computed via `scripts/cluster_stability_full.py`. Reported in `results/cluster_stability_full_{event_id}.json`.

### Known Limitations

**Cluster stability:** Three-level analysis on CS1 (106 articles, 5 seed runs):

| Level | Metric | Value | Interpretation |
|-------|--------|-------|----------------|
| Parametric | ARI across seeds | 0.32 ± 0.04 | Article-to-cluster assignment is moderately sensitive to LLM non-determinism |
| Taxonomy | Label embedding cosine | 0.77 ± 0.13 | Cluster verbal characterization is substantially more stable than membership |

The gap between parametric stability (0.32) and taxonomy stability (0.77) is the key finding: the LLM discovers consistent epistemic categories across runs even when it assigns individual boundary articles inconsistently. 32% of cluster membership is structurally stable across corpus subsampling (hard core analysis pending full bootstrap run). Cluster labels should be treated as robust epistemic categories whose membership boundaries are fuzzy — analogous to prototype-based categories in cognitive science, not crisp partitions. Structural stability (bootstrap co-occurrence) is pending and will determine hard core fractions per cluster.

**Inter-model agreement:** Under semantic similarity metric (cosine ≥ 0.75 on `paraphrase-multilingual-mpnet-base-v2`), 45.3% of articles show three-model agreement, 20.8% show two-of-three agreement, 34.0% are genuinely contested. Agreement rates are lowest for Arabic (mean cosine 0.670) and Romanian (0.570) articles, likely reflecting training data gaps for non-Western political text in smaller models (Gemma-27B, Mistral-24B).

**LLM-to-embedding divergence:** ARI = 0.03 between LLM-based clustering and sentence-embedding clustering. This is a finding, not a failure: sentence embeddings capture topical similarity ("articles about Iran negotiations"), while LLM clustering captures epistemic framing ("articles that treat US military authority as legitimate"). These are different structures in the same data.

**Single-event validation:** All quantitative results derive from one event corpus (CS1: Iran strikes, 106 analyzed articles). CS2 pre-registration written (`results/cs2_preregistration.md`); formal taxonomy transfer protocol prepared (`scripts/taxonomy_transfer.py`). Cross-event stability is untested pending CS2 pipeline completion. Claims about "global epistemic patterns" should be read as hypotheses pending replication.

**GDELT text extraction:** ~50% failure rate on non-English articles. Partially mitigated by archive.org Wayback Machine fallback (~75% recovery).

**Free-tier API quotas:** World News API and NewsData.io impose daily limits. Corpus expansion relies on overnight cron pulls across multiple days.

**Translation artifacts:** Helsinki-NLP models vary in quality by language pair. Length-ratio check flags severe content loss but does not catch subtle mistranslation.

## Key Design Decisions

1. **No predefined categories.** Framing taxonomy emerges from data, not imposed on it.
2. **Original-language extraction first.** Non-English articles get framing terms extracted in their source language before translation — preserving epistemic vocabulary that translation flattens.
3. **Country context injection.** Each article's analysis includes 2-3 sentences of country context to compensate for LLM Western training bias.
4. **3-model council.** Qwen3-32B + Gemma-27B + Mistral-24B. Disagreement is the finding, not noise.
5. **Absence is data.** After clustering, a meta-prompt identifies structurally absent positions, unrepresented actors, and "unspeakable" framings.

## File Structure

```
pipeline.py              # two-pass analysis (framing extraction -> clustering)
gdelt_pull.py            # GDELT DOC API ingestion
worldnews_ingest.py      # World News API + API League (auto-failover)
newsdata_ingest.py       # NewsData.io (credit-budgeted)
marketaux_ingest.py      # financial news with ticker metadata
reddit_ingest.py         # Reddit public JSON API
archive_fetcher.py       # Wayback Machine fallback
overnight_ingest.sh      # cron script for daily API pulls
news_sources.json        # master registry of 67 sources
articles.json            # merged article metadata (no full text)
sources/                 # per-API article metadata
docs/                    # static HTML output (Cloudflare Pages)
```

## Live Demo

[news.thebeakers.com](https://news.thebeakers.com) — CS1 Iran report live

## Citation

Paper in preparation. Target: Digital Journalism / Computational Communication Research.

## License

Code: MIT. Article metadata: fair use for research. Full article text not included (copyright).
