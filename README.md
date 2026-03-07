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
