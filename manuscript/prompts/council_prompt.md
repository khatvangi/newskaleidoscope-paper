# Council: Multi-Model Validation Prompt

Source: `council.py` (COUNCIL_SYSTEM_PROMPT, line 49) and `scripts/sample_council.py` (COUNCIL_SYSTEM_PROMPT, line 60)

Both files contain identical prompts. The council prompt is delivered as a **system message**, unlike the Pass 1 prompt which uses only a user message.

## Exact System Prompt Text

```
You are an analyst mapping epistemic frames in global media.
Analyze the article and extract the following as JSON only.
No preamble. No explanation. JSON only.
Do not reference what other analysts might conclude.
Analyze only what is in the text.

{
  "primary_frame": "one sentence describing the dominant frame",
  "positions": ["array", "of", "positions", "taken"],
  "absence_flags": ["what is notably absent from this text"],
  "internal_tensions": ["contradictions held within the article"],
  "unspeakable_positions": ["positions the article cannot state directly"],
  "confidence_score": 0.0-1.0,
  "frame_category": "justified_action|illegal_escalation|diplomatic|self_defense|humanitarian|economic|other"
}
```

## User Message Format

The user message for each article is:

```
Analyze this article:

{text[:3000]}
```

Article text is truncated to 3000 characters.

## LLM Call Parameters (Council)

- `temperature`: 0.1 (lower than Pass 1's 0.3 for more deterministic output)
- `max_tokens`: 2048
- `timeout`: 120 seconds
- Message structure: system prompt + user message (two-message conversation)
- API: OpenAI-compatible `/v1/chat/completions`

## Council Execution Strategy

### Full Council (CS1 — Iran)
- Three models run sequentially, each processing all articles
- Models are swapped by stopping/restarting llama-server on boron
- All three models see identical system prompt and article text

### Sample Council (CS1-RU — Ukraine, CS2 — Tariffs)
- Qwen Pass 1 analysis already exists from the pipeline
- Gemma-27B runs on a stratified sample of ~300 articles
- Comparison is Qwen primary_frame vs Gemma primary_frame via cosine similarity
- llama-server runs with `--parallel 4` for 4x throughput
