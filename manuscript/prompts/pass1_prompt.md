# Pass 1: Per-Article Framing Extraction Prompt

Source: `pipeline.py` (PASS1_PROMPT, line 324) and `scripts/pass1_runner.py` (PASS1_PROMPT, line 42)

Both files contain identical prompts. The standalone `pass1_runner.py` is used for event-specific batch runs.

## Template Variables

- `{event_context}` — from `events.prompt_context` DB field (e.g., "the US military strikes on Iranian nuclear facilities in March 2026")
- `{country_context}` — from `country_contexts.json`, 2-3 sentence bias compensation per source country
- `{article_text}` — translated text (if non-English) or raw text, truncated to first 3000 characters

## Exact Prompt Text

```
You are analyzing a news article about {event_context}.

{country_context}

Describe how this article frames this event. Do NOT use predefined political categories.
Instead, answer these questions using the article's own conceptual vocabulary:

1. AUTHORITY: Who does this article treat as having legitimate authority to act? Who is implicitly denied legitimacy?
2. HISTORY: What historical context does the article invoke? What does it assume the reader already knows?
3. RESPONSE: What does the article present as the appropriate response to the situation? What responses are implicitly ruled out?
4. ASSUMPTIONS: What unstated assumptions underlie the article's framing? What would someone from a completely different political tradition notice as strange or arbitrary?
5. SOURCES: Who is quoted or cited? Whose voice is absent?
6. TENSION: Does the article hold positions that are in tension with each other? (e.g., invoking sovereignty principles while supporting selective intervention, or endorsing diplomacy while naturalizing military buildup)

Also extract:
7. FACTUAL CLAIMS: List specific verifiable claims.
8. ABSENCE: What obviously relevant frames, actors, or contexts does this article NOT engage with at all?
9. KEY LANGUAGE: 3-5 specific words or phrases (in English, from the translated text) that most reveal the frame.

Output JSON:
{
  "framing_description": "2-4 sentences describing how this article frames the event, using the article's own conceptual vocabulary — not external political labels",
  "authority_structure": "who is granted/denied legitimacy to act",
  "historical_context_invoked": ["specific historical events or periods referenced"],
  "assumed_appropriate_response": "what the article implies should happen",
  "unstated_assumptions": ["assumptions a reader from a different tradition would notice"],
  "who_is_quoted": ["authorities cited"],
  "whose_voice_is_absent": ["relevant actors not quoted or referenced"],
  "internal_tensions": "describe any contradictions within the article's own framing, or null if coherent",
  "factual_claims": ["specific verifiable claims"],
  "absence_flags": ["frames or contexts the article does not engage with"],
  "key_framing_language": ["3-5 English words/phrases that reveal the frame"],
  "one_sentence_summary": "single sentence capturing this outlet's essential position"
}

IMPORTANT: Output ONLY valid JSON, no other text.

Article:
{article_text}
```

## Pre-Translation Step: Original-Language Framing Extraction

Source: `pipeline.py` (FRAMING_EXTRACT_PROMPT, line 282)

This prompt runs BEFORE translation on non-English articles to preserve original-language framing terms. English articles skip this step.

### Template Variables

- `{language}` — detected source language name (e.g., "Arabic", "Russian")
- `{event_context}` — same as Pass 1
- `{text}` — raw article text in original language, truncated to first 2000 characters

### Exact Prompt Text

```
You are analyzing a news article written in {language} about {event_context}.

Extract ONLY the key framing language — the specific words and phrases that reveal how this source frames the event. Return them in the ORIGINAL language, not translated. Also provide approximate English translations.

Output JSON:
{
  "original_framing_terms": ["5-8 specific words or phrases from the article in their original {language}"],
  "english_approximations": ["approximate English translation of each term above, in same order"],
  "contested_translations": ["any terms where the English translation significantly loses meaning — explain what's lost"],
  "emotional_register": "one of: neutral_analytical, alarmed, triumphant, mournful, ironic, propagandistic, diplomatic"
}

IMPORTANT: Output ONLY valid JSON, no other text.

Article excerpt:
{text}
```

## LLM Call Parameters (Pass 1)

- `temperature`: 0.3
- `max_tokens`: 3072
- `timeout`: 180 seconds
- Input text truncated to 3000 characters
- API: OpenAI-compatible `/v1/chat/completions`
- Message role: `user` (no system prompt for Pass 1)
