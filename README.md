# NewsKaleidoscope

Epistemic mapping system that shows how different regions, cultures, and institutions frame major world events.

## How It Works

1. **gdelt_pull.py** — Queries GDELT 2.0 DOC API for event coverage, enforces geographic diversity (max 5 articles per country)
2. **outlet_curator.py** — Generates a curated registry of 40 global outlets across 7 regions with bias metadata
3. **pipeline.py** — Fetches article text, translates non-English via Ollama (boron), extracts epistemic positions via LLM
4. **output_generator.py** — Renders analysis into static HTML for Cloudflare Pages deployment

## Run

```bash
# install dependencies
pip install trafilatura

# pull articles from GDELT
python3 gdelt_pull.py

# generate outlet registry
python3 outlet_curator.py

# run analysis pipeline (10 articles for test, or omit limit for all)
python3 pipeline.py 10

# generate HTML output
python3 output_generator.py
```

## Requirements

- Python 3.8+
- trafilatura (article extraction)
- Ollama running on boron (LAN) with qwen3:32b or larger

## Architecture

- **LLM inference**: All calls go to `http://boron:11434` (Ollama API) — no external LLM APIs
- **Output**: `docs/index.html` — deployed via Cloudflare Pages
- **Cache**: Raw articles cached in `cache/` to avoid re-fetching
- **Logs**: Pipeline activity logged to `logs/pipeline.log`

## Position Types

The system classifies coverage into 8 epistemic positions:
- endorsement, procedural_objection, sovereignty_opposition
- great_power_framing, non_aligned_ambiguity, religious_framing
- whataboutism_cynical, whataboutism_legitimate
