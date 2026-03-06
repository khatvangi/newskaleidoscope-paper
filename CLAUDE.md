# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NewsKaleidoscope** is an epistemic mapping system that visualizes how different regions, cultures, and institutions frame major world events. It ingests global news coverage via GDELT + curated RSS, extracts epistemic positions via LLM analysis, and renders a static HTML map.

## Architecture

```
# tier 1+2: text sources
gdelt_pull.py → articles.json     (GDELT + geographic diversity)
rss_supplement.py → articles.json (appends curated outlet articles)
outlet_curator.py → outlets.json

# tier 3: oral/informal sources
youtube_ingest.py → articles.json (YouTube → Whisper transcription on boron)
podcast_ingest.py → articles.json (podcast RSS → Whisper transcription)
telegram_ingest.py → articles.json (public Telegram channels via web preview)
sermon_harvester.py → articles.json (Friday sermon archives)
radio_ingest.py → articles.json   (international broadcast transcripts)

# analysis + output
pipeline.py → analysis/*.json     (two-pass: framing → clustering)
output_generator.py → docs/index.html (Cloudflare Pages)
```

- **All LLM inference** goes to Ollama on boron (`http://boron:11434`). Never use external LLM APIs.
- **Model preference**: qwen2.5:72b → qwen3:32b → largest available. Check `/api/tags` first.
- **Article text extraction**: trafilatura (preferred) → newspaper3k (fallback)
- **Static output**: `docs/index.html` is the Cloudflare Pages entry point

## Infrastructure

| Machine | Role | GPU | Address |
|---------|------|-----|---------|
| nitrogen | Pipeline orchestration, web serving, deployment | RTX A4000 16GB | localhost |
| boron | LLM inference via Ollama | 2x TITAN RTX 48GB | `http://boron:11434` |

## Commands

```bash
# tier 1+2 ingestion
python3 gdelt_pull.py                 # fetch GDELT articles → articles.json
python3 rss_supplement.py             # add curated outlet articles → articles.json
python3 outlet_curator.py             # generate outlet registry → outlets.json

# tier 3 ingestion (run AFTER pipeline completes — shares boron GPU)
python3 youtube_ingest.py             # YouTube channels → Whisper → articles.json
python3 podcast_ingest.py             # podcast RSS → Whisper → articles.json
python3 telegram_ingest.py            # Telegram public channels → articles.json
python3 sermon_harvester.py           # religious institution archives → articles.json
python3 radio_ingest.py               # broadcast service transcripts → articles.json

# analysis
python3 pipeline.py 10                # analyze 10 articles (test run)
python3 pipeline.py                   # analyze all articles (~3-5 hours)
python3 output_generator.py           # render HTML → docs/index.html

# verify boron connectivity
curl http://boron:11434/api/tags      # list available models

# deployment
# push to git → Cloudflare Pages auto-deploys from docs/
```

## Key Directories

- `cache/` — raw article text + Whisper transcripts (auto-cached by URL hash, excluded from git)
- `analysis/` — per-article JSON results + `all_results.json` + `emergent_clusters.json` + `absence_report.json` + `coverage_gaps.json`
- `docs/` — static HTML output for deployment
- `logs/` — `pipeline.log` with timestamped progress
- `sources/tier3/audio/` — downloaded audio files for Whisper transcription
- `sources/tier3/transcripts/` — cached Whisper transcript JSONs

## Two-Pass Analysis Pipeline

**Pass 1 (per-article):** Open-ended framing description using the article's own conceptual vocabulary. No predefined categories. Extracts: authority structure, historical context, unstated assumptions, internal tensions, absence flags.

**Pass 2 (post-corpus):** Clusters all framing descriptions into emergent categories. Some map to conventional political science labels; the ones that don't are the discovery. Singletons (articles that resist clustering) are preserved.

**Corpus-level absence report:** After clustering, a meta-prompt identifies structurally absent positions, unrepresented actors, voiceless populations, and "unspeakable" positions.

## Pipeline Flow (non-English articles)

1. Fetch article text → cache by URL hash
2. **Extract original-language framing** (LLM call #1) — terms + English approximations + contested translations
3. **Translate** (LLM call #2) — with length-ratio check for content loss
4. **Pass 1 framing extraction** (LLM call #3) — with country context injection from `country_contexts.json`

English articles skip steps 2-3. Pass 2 clustering and absence report run once after all articles.

## Country Context Injection

`country_contexts.json` contains 2-3 sentence context per country (58 countries) covering: relationship to US military action, regional position, domestic media framing factors. Injected into Pass 1 prompts to compensate for LLM Western training bias.

## Immutability Rules (MANDATORY — every session)

**NEVER overwrite or delete analytical data. The DB is a lab notebook, not a dashboard.**

### Files
- **analysis/** — NEVER overwrite. Append or version only.
- Before touching any existing JSON in analysis/, rename it with timestamp:
  `emergent_clusters.json` → `emergent_clusters_20260305.json`
- New output gets new filename with run_id or timestamp.

### Database
- **NEVER UPDATE or DELETE rows** in: articles, analyses, llm_council_verdicts, clusters, cluster_memberships
- Only additive INSERTs allowed. New analytical runs produce NEW rows alongside old ones.
- Every analytical run gets a `run_id` (timestamp or session-based, e.g. "session_001").
- All DB inserts include run_id where the schema supports it.
- Comparison between runs is a feature, not a problem.

### Clusters specifically
- New clustering run = new cluster rows with new run_id and method label.
- Old clusters stay. Mark them with method ("llm_pass2", "sentence_embedding", etc.).
- NEVER replace old clusters with new ones.

### Before touching existing data
1. Report what currently exists (row counts, file names).
2. State explicitly what you will ADD vs. what you will PRESERVE.
3. Wait for confirmation if any destructive action is needed.

### Why
Every run, attempt, and failure is part of the research record. The sentence embedding
mega-cluster failure belongs in the methodology paper as "what we tried and why it failed."
Deleting it loses that evidence. Analytical progress is cumulative.

## Constraints

- GDELT API: rate limited to 1 request per 5 seconds, retry with backoff. Falls back to fetching via boron if nitrogen IP is blocked.
- Ollama timeout: 180 seconds per call (32B+ models need headroom)
- Pipeline logs everything to `logs/pipeline.log`; failures are skipped, not fatal
- Geographic diversity: round-robin selection, max 3 articles per country, target 60 total
- RSS supplement adds ~30-40 curated flagship outlet articles on top of GDELT pool
- Outlets have tier 1 (flagship) and tier 2 (religious/institutional) classification
- Tier 3 Whisper transcription: faster-whisper large-v3 on boron GPU. Do NOT run while Ollama pipeline is active — both compete for VRAM
- YouTube/podcast audio goes to `sources/tier3/audio/`, transcripts cached to `cache/` (same hash scheme as articles)
