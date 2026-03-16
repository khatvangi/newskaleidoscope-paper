# Pass 1: Open-Ended Framing Extraction

## Rationale: Why Open-Ended

Conventional content analysis of media framing typically begins with a predefined codebook -- categories such as "conflict frame," "human interest frame," "economic consequences frame" (Semetko and Valkenburg, 2000) -- and trains coders to classify articles into these categories. This approach has well-known limitations: it can only find what it is looking for, it imposes Western political science taxonomies on non-Western media, and it collapses genuinely novel framing patterns into the nearest predefined category.

NewsKaleidoscope's Pass 1 analysis inverts this approach. Each article is analyzed independently using an open-ended prompt that asks the LLM to describe how the article frames the event *in the article's own conceptual vocabulary*, without reference to predefined political categories. The taxonomy emerges from the data in Pass 2 (clustering), rather than being imposed upon it.

This design choice has specific methodological consequences:

- Framing patterns that do not correspond to any standard political science category can surface (e.g., a framing that treats the event primarily through the lens of technological capability rather than moral legitimacy).
- Articles from non-Western media ecosystems are not forced into categories derived from Western analytical traditions.
- Internal tensions within a single article's framing are preserved rather than flattened by categorical assignment.
- The discovery of the clustering step (Pass 2) is genuinely emergent: some clusters will map to conventional categories, and the ones that do not are the most analytically valuable findings.

## Country Context Injection

A persistent challenge in using LLMs for cross-cultural media analysis is the models' training-data bias toward Western (and particularly Anglophone) media frames. An article from Iranian state media or a Pakistani newspaper may employ framing conventions that a Western-trained LLM systematically misinterprets or flattens.

To partially compensate for this bias, a country context injection system was implemented. The file `country_contexts.json` contains 2-3 sentence context entries for 58 countries, each describing:

- The country's relationship to US military action (adversarial, allied, complicated, neutral)
- Regional geopolitical position
- Domestic media landscape and known framing factors

For example, the entry for Iran reads:

> "Direct target of US military threats and covert operations since the 1953 CIA-backed coup and 1979 hostage crisis. State-controlled media frames all US military action as imperialist aggression, with nuclear program presented as sovereign right. Revolutionary Guard ideology treats resistance to US hegemony as foundational national identity."

Each entry also includes a list of key framing factors (e.g., for Pakistan: "drone strike civilian casualties," "anti-American public sentiment," "military-ISI influence on coverage," "China pivot via CPEC," "nuclear state identity").

During Pass 1 analysis, the country context for the article's source country was injected into the prompt as a `COUNTRY CONTEXT` block. This provided the LLM with baseline knowledge about the media ecosystem producing the article, reducing the likelihood of misinterpreting framing conventions unfamiliar from a Western perspective. The `get_country_context()` function in `pipeline.py` retrieved the appropriate context string and appended the key framing factors.

## Model and Infrastructure

Pass 1 analysis was performed using Qwen3-32B (Alibaba), quantized to Q4_K_M format (`qwen3-32b-q4km.gguf`, approximately 20 GB). The model was served via llama-server (from the llama.cpp project) on a dedicated inference machine (boron) equipped with two NVIDIA TITAN RTX GPUs (48 GB VRAM total). The model was loaded with `--tensor-split 0.5,0.5` to distribute layers evenly across both GPUs, `--ctx-size 16384` for sufficient context window, and `--n-gpu-layers 99` to ensure full GPU offloading.

The LLM was accessed via an OpenAI-compatible `/v1/chat/completions` API endpoint at `http://boron:11434`. Each Pass 1 call used `temperature=0.3` and `max_tokens=3072`, with a timeout of 180 seconds. Article text was truncated to 3,000 characters before inclusion in the prompt.

For CS1-RU, a standalone `scripts/pass1_runner.py` script was used to process articles from the database, allowing the Pass 1 pipeline to target specific events and LLM endpoints independently.

## The Pass 1 Prompt

The Pass 1 prompt (`PASS1_PROMPT` in `pipeline.py`) instructed the model to analyze nine dimensions of each article's framing:

1. **AUTHORITY**: Who the article treats as having legitimate authority to act, and who is implicitly denied legitimacy.
2. **HISTORY**: What historical context is invoked, and what the article assumes the reader already knows.
3. **RESPONSE**: What the article presents as the appropriate response, and what responses are implicitly ruled out.
4. **ASSUMPTIONS**: Unstated assumptions that someone from a different political tradition would notice as strange or arbitrary.
5. **SOURCES**: Who is quoted or cited, and whose voice is absent.
6. **TENSION**: Whether the article holds positions in tension with each other (e.g., invoking sovereignty while supporting selective intervention).
7. **FACTUAL CLAIMS**: Specific verifiable claims made in the article.
8. **ABSENCE**: Frames, actors, or contexts the article does not engage with at all.
9. **KEY LANGUAGE**: 3-5 specific English words or phrases that most reveal the frame.

The model was instructed to output a JSON object with the following fields:

- `framing_description`: 2-4 sentences using the article's own conceptual vocabulary
- `authority_structure`: who is granted/denied legitimacy
- `historical_context_invoked`: array of referenced historical events
- `assumed_appropriate_response`: what the article implies should happen
- `unstated_assumptions`: array of assumptions a different-tradition reader would notice
- `who_is_quoted`: array of cited authorities
- `whose_voice_is_absent`: array of relevant but unquoted actors
- `internal_tensions`: description of contradictions, or null if coherent
- `factual_claims`: array of verifiable claims
- `absence_flags`: array of unengaged frames or contexts
- `key_framing_language`: 3-5 English words/phrases revealing the frame
- `one_sentence_summary`: single sentence capturing the outlet's essential position

The full prompt text is identical in `pipeline.py` and `scripts/pass1_runner.py`.

## Non-English Article Processing Pipeline

For non-English articles, the pipeline executed three LLM/model calls in sequence:

1. **Original-language framing extraction** (LLM call #1): The `FRAMING_EXTRACT_PROMPT` instructed the LLM to extract 5-8 framing terms in the original language, provide English approximations, flag contested translations, and classify the emotional register. This step preserved culturally specific framing vocabulary before any translation occurred.

2. **Translation** (model call #2): The article was translated to English using the Helsinki-NLP / NLLB-200 pipeline described in Section 2. This was a neural machine translation call, not an LLM call.

3. **Pass 1 framing extraction** (LLM call #3): The translated text was analyzed using the standard Pass 1 prompt with country context injection.

English-language articles skipped steps 1-2 and proceeded directly to Pass 1 framing extraction.

## Output and Storage

Pass 1 results were stored in two locations:

- The `analyses` table in PostgreSQL, with fields for `article_id`, `event_id`, `model_used` (recording the specific model, e.g., "qwen3-32b"), `primary_frame`, `frame_confidence`, `positions` (JSONB), `internal_tensions` (JSONB), `absence_flags` (JSONB), `unspeakable_positions` (JSONB), and `raw_llm_output` (JSONB containing the complete parsed JSON response).
- The `analysis/` directory as JSON artifacts, versioned by run_id.

JSON parsing of LLM output used a robust extraction procedure (`parse_llm_json()` in `pipeline.py`): first attempting direct `json.loads()`, then stripping markdown code fences if present, then extracting the substring between the first `{` and last `}`. Unparseable responses were stored with a `raw_response` key for later inspection.

## Processing Statistics

For CS1 (Iran), Pass 1 analysis processed 1,267 articles. For CS1-RU (Ukraine), 1,863 articles were analyzed (the remaining 233 of the 2,096 total lacked extractable text). Processing was performed in continuous runs, with the pipeline skipping articles that already had analysis records in the database, allowing interrupted runs to resume without re-processing.

The pipeline logged all progress to `logs/pipeline.log` with timestamped entries. Failures (network timeouts, JSON parse errors, empty LLM responses) were logged and skipped rather than halting the pipeline, consistent with a fault-tolerant design for large-scale corpus processing.
