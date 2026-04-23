# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**This is NOT the NewsKaleidoscope epistemic clustering project.** The parent `/storage/news/` does epistemic framing analysis (GDELT → LLM framing → emergent clustering). This subdirectory is a different kind of investigation.

**This project**: DOJ document forensics + global media forensics for the "Academic Reckoning" report.

What we do here:
1. **Mine the DOJ Epstein document dump** (3.5M pages) — extract what intellectuals actually did, said, and knew
2. **Track global media coverage** — how outlets around the world cover (or suppress) those facts
3. **Build the analytical argument** — five-layer capture framework + knowledge gradient, backed by corpus evidence

The method is investigative, not epistemic. We don't cluster framings — we compare **primary documents vs media coverage** to find what's suppressed, amplified, or distorted.

**Start of session**: Read `SESSION.md` for active jobs, DB state, and next steps.

## Theoretical Framework (Data-Derived)

See memory files for full details. The report is structured around:

**Five Layers of Intellectual Capture** (how they got pulled in):
1. Structural dependency — funding lifeline (junior faculty survival)
2. Intellectual flattery — "Jeffrey was interested in interesting people" (established names)
3. Willful blindness — "nerd tunnel vision" (research leaders)
4. Status transgression — "the lucrative and louche" (administrators)
5. Moral exceptionalism — "an ethicist is someone who has a problem" (inner circle)

**Knowledge Gradient** (they knew and stayed):
- SAW → reframed → joked about it → rationalized → actively enabled

**Funding Correlation** (the empirical backbone):
- 0% funding at name_drop → 4.7% at social_contact → 40% at visited_properties → 57% at facilitated_access

Each claim backed by direct quotes from the `epstein_entity_contexts` corpus.

## Data Ownership

- **event_id=6** — this project's intellectual corruption corpus (954 articles)
- **event_id=5** — parent Epstein Global project (6,167 articles) — **DO NOT MODIFY**
- DB: `postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope`
- DB shortcut: `PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope`

## Directory Structure

This directory contains symlinks to parent scripts. **Run all scripts from `/storage/news/`** (the parent).

| Symlink | Script | Purpose |
|---------|--------|---------|
| `entity_context_extractor.py` | `scripts/entity_context_extractor.py` | per-entity involvement extraction via LLM |
| `epstein_intellectuals.py` | `scripts/epstein_intellectuals.py` | entity DB, article tagging, suppression index |
| `epstein_primary_docs.py` | `scripts/epstein_primary_docs.py` | primary doc fetching from Investigation API |
| `epstein-intellectual-corruption-v2.yaml` | `topics/...` | 37 GDELT queries, 3 time windows, 16 subreddits |

Pipeline orchestrator: `scripts/topic_runner.py` (phases: ingest → extract → translate → analyze → council → cluster → report)

## Commands

```bash
cd /storage/news

# status checks
python3 scripts/entity_context_extractor.py --status --event-id 6
python3 scripts/topic_runner.py topics/epstein-intellectual-corruption-v2.yaml --status
python3 scripts/epstein_primary_docs.py compare

# DB row counts
PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope \
  -c "SELECT COUNT(*) FROM analyses WHERE event_id = 6;"
PGPASSWORD=newskal_dev psql -h localhost -U newskal newskaleidoscope \
  -c "SELECT COUNT(*) FROM epstein_entity_contexts;"

# run pipeline phases individually
python3 scripts/topic_runner.py topics/epstein-intellectual-corruption-v2.yaml --phase extract
python3 scripts/topic_runner.py topics/epstein-intellectual-corruption-v2.yaml --phase translate
python3 scripts/topic_runner.py topics/epstein-intellectual-corruption-v2.yaml --phase analyze

# entity context extraction (requires llama-server on boron)
python3 scripts/entity_context_extractor.py --event-id 6 --llm-url http://boron:11434

# primary doc comparison
python3 scripts/epstein_primary_docs.py fetch     # download from Investigation API
python3 scripts/epstein_primary_docs.py compare   # docs vs media suppression index

# entity DB management
python3 scripts/epstein_intellectuals.py build    # populate entity DB
python3 scripts/epstein_intellectuals.py status   # show stats
python3 scripts/epstein_intellectuals.py export   # export tagged articles

# check/kill GPU jobs
ssh boron "pkill llama-server"   # kill boron inference
pkill llama-server               # kill nitrogen inference
```

## Three-Layer Analysis Architecture

The core innovation: comparing **what documents say** vs **how media frames** the same individuals.

1. **Primary Documents** (`sources/epstein_primary/`) — DOJ docs, flight logs, Investigation API entities
2. **Media Corpus** (event_id=6) — 954 articles from GDELT/WorldNews/Reddit across 3 time windows
3. **Gap Analysis** — suppression index (doc_mentions / media_mentions ratio)

## Graduated Involvement Model

Entity context extraction captures graduated involvement depth, not binary mention/no-mention:

```
name_drop → social_contact → received_funding → visited_properties → facilitated_access → deep_complicity
```

Stored in `epstein_entity_contexts` table with: entity_role, institution, involvement_level, money_received, money_amount, consequences, institutional_response, direct_quotes (JSONB), article_framing, systemic_analysis.

## Entity-Specific DB Tables

- **`epstein_entities`** — 106 entities (23 intellectuals + 96 API + known associates)
- **`epstein_entity_contexts`** — per-article entity involvement extractions (the core data)
- **`epstein_connections`** — entity-to-entity relationship network
- **`epstein_media_mentions`** — article-level mention counts per entity

## Infrastructure

- **LLM inference**: llama-server on boron (`http://boron:11434`), OpenAI-compatible API
- **Models**: qwen3-32b (primary), gemma-27b (council), mistral-24b (council/nitrogen)
- **IMPORTANT**: kill llama-server when not in use — pegs CPU at 99.9%
- **GPU conflict**: tier 3 Whisper and Ollama/llama-server compete for VRAM — don't run simultaneously

## Immutability Rules

Inherited from parent project — **NEVER overwrite or delete analytical data**:
- analysis/ files: rename with timestamp before creating new versions
- DB: only additive INSERTs, never UPDATE/DELETE on analytical tables
- Every run gets a `run_id` — old data stays for methodology comparison
