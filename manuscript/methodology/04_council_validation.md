# Multi-Model Council Validation

## Rationale

A fundamental concern in LLM-based content analysis is the degree to which analytical outputs reflect genuine properties of the source text versus idiosyncratic biases of the model. If Qwen3-32B systematically frames Middle Eastern media as "propagandistic" due to training-data composition, this artifact would contaminate all downstream clustering and absence analysis.

The multi-model council protocol addresses this by having multiple LLMs with distinct training lineages independently analyze each article, then measuring inter-model agreement as a proxy for analytical reliability. The logic is analogous to inter-rater reliability in traditional content analysis: agreement across independent raters with different backgrounds increases confidence that the coded property exists in the text rather than in the rater's priors.

## Model Selection

Three models were selected for the council, chosen to maximize diversity of training data provenance, organizational origin, and linguistic emphasis:

| Model | Organization | GGUF File | Size | Emphasis |
|---|---|---|---|---|
| Qwen3-32B | Alibaba (China) | `qwen3-32b-q4km.gguf` | ~20 GB Q4_K_M | Strong on Asian and Middle Eastern political text |
| Gemma-3-27B-IT | Google (US) | `google_gemma-3-27b-it-Q4_K_M.gguf` | ~16.5 GB Q4_K_M | Distinct training corpus, instruction-tuned |
| Mistral-Small-3.1-24B | Mistral (France/EU) | `Mistral-Small-3.1-24B-Instruct-2503-Q4_K_M.gguf` | ~14.3 GB Q4_K_M | European emphasis, diplomatic register |

The Chinese, American, and European origins of these models provide meaningfully different training-data distributions, particularly for coverage of geopolitical events where framing varies systematically by region.

## Council Prompt

All three models received an identical system prompt (`COUNCIL_SYSTEM_PROMPT` in `council.py`), distinct from the Pass 1 prompt. The council prompt instructed the model to:

- Extract the dominant frame as a single sentence (`primary_frame`)
- List positions taken (`positions`)
- Identify notable absences (`absence_flags`)
- Identify internal contradictions (`internal_tensions`)
- Identify positions the article cannot state directly (`unspeakable_positions`)
- Self-assess confidence on a 0.0-1.0 scale (`confidence_score`)
- Classify into one of seven frame categories: `justified_action`, `illegal_escalation`, `diplomatic`, `self_defense`, `humanitarian`, `economic`, `other`

The council prompt was deliberately more structured than the Pass 1 prompt, as its purpose was comparative measurement rather than open-ended exploration. The `frame_category` field provided a coarse alignment check alongside the free-text `primary_frame` field used for similarity measurement.

Each model received the article text (truncated to 3,000 characters) with `temperature=0.1` and `max_tokens=2048`. The low temperature was chosen to minimize stochastic variation in outputs, isolating differences attributable to model training rather than sampling randomness.

## Sequential Model Loading

All three models were too large to load simultaneously on the available hardware (two TITAN RTX GPUs with 48 GB total VRAM). The council therefore operated sequentially: for each model, llama-server was started on boron via SSH with the appropriate GGUF file, all articles were processed, and then the server was stopped before loading the next model.

The `start_llama_server()` function in `council.py` managed this lifecycle:

1. Kill any running llama-server process via `ssh boron "pgrep -f llama-server"` and `kill`
2. Start the new model with `nohup llama-server --model <path> --tensor-split 0.5,0.5 --host 0.0.0.0 --port 11434 --ctx-size 16384 --n-gpu-layers 99`
3. Poll the `/v1/models` endpoint every 3 seconds for up to 180 seconds until the server reports readiness
4. Send a warmup prompt ("Say OK.") to force full model loading into GPU memory
5. Retry warmup once if the first attempt fails

After all models completed processing, `stop_llama_server()` was called to release GPU resources.

## Consensus Measurement

Inter-model agreement was measured using cosine similarity of sentence embeddings, computed via the `all-MiniLM-L6-v2` model from the sentence-transformers library (`council.py`, function `compute_similarity()`). For each article, the `primary_frame` text from each model's output was embedded into a 384-dimensional vector, and pairwise cosine similarity was computed.

The similarity threshold for agreement was set at 0.82 (`SIMILARITY_THRESHOLD = 0.82`).

### Classification Logic

The `determine_consensus()` function implemented the following decision logic:

- **HIGH confidence**: All pairwise similarities >= 0.82 (with at least 3 valid readings). The consensus frame was taken from the model with the highest self-assessed `confidence_score`.
- **MEDIUM confidence**: At least one pair of models agreed (similarity >= 0.82), with the third dissenting. The consensus frame was taken from the higher-confidence member of the agreeing pair. The dissenting model was recorded.
- **CONTESTED**: No pair of models achieved similarity >= 0.82. No consensus frame was assigned. For contested articles, separate analysis rows were written to the database for each model (prefixed `council_contested:<model_name>`), and the article was flagged with `needs_human_review = True`.
- **LOW**: Only one valid model reading (insufficient for consensus).
- **FAILED**: No valid model readings.

### Output Aggregation

For HIGH and MEDIUM articles, a single consensus analysis row was written to the `analyses` table, with `model_used` set to `council_high` or `council_medium`. Positions, absence flags, and internal tensions were aggregated via set union across all models (deduplicating identical entries).

For CONTESTED articles, individual per-model analysis rows were written (e.g., `council_contested:qwen3:32b`), preserving each model's distinct reading as part of the research record.

All council verdicts were additionally stored in the `llm_council_verdicts` table with fields for `article_id`, `models_agree` (boolean), `consensus_frame`, `confidence_level`, `model_readings` (JSONB containing complete outputs from all models), and `dissent_recorded` (boolean).

## CS1: Full Council

For CS1 (Iran strike), the full three-model council was run across all 1,267 articles. Results:

| Confidence Level | Count | Percentage |
|---|---|---|
| HIGH | 60 | 4.7% |
| MEDIUM | 476 | 37.6% |
| CONTESTED | 731 | 57.7% |

The high proportion of contested articles (57.7%) is itself an analytical finding: it suggests that the framing of the Iran strike event was genuinely ambiguous or polysemous, with different models (trained on different corpora) producing systematically different readings. This aligns with the expectation that a novel, rapidly evolving military event would resist stable interpretive consensus.

## CS1-RU: Stratified Sample Council

For CS1-RU (Ukraine 2022), a full three-model council across 1,863 articles would have required approximately 63 hours of GPU time. A methodological decision was made to use a stratified sample council instead, based on the following argument: the council measures *model reliability* (whether different LLMs produce convergent readings), not *article properties*. Once model reliability has been established on one case study (CS1, full council), a smaller sample suffices to confirm that reliability transfers to a new corpus.

### Sampling Strategy

The `draw_stratified_sample()` function in `scripts/sample_council.py` implemented proportional stratified sampling by language. All articles with completed Pass 1 analysis and available translated text were grouped by `original_language`. Each language stratum received a sample allocation proportional to its share of the total corpus, with a minimum of 1 article per language to ensure representation of low-frequency languages. The target sample size was 300 articles, with a random seed of 42 for reproducibility.

### Two-Model Comparison

Rather than loading all three models, the sample council compared the existing Qwen3-32B Pass 1 output against a new Gemma-3-27B-IT reading. Gemma was loaded with `--parallel 4` to enable concurrent request processing, providing approximately 4x throughput compared to sequential processing. The `run_gemma_parallel()` function used Python's `concurrent.futures.ThreadPoolExecutor` with 4 workers.

### Consensus Thresholds

The sample council used the same similarity model (all-MiniLM-L6-v2) and base threshold (0.82) as the full council, with an additional intermediate band:

- **HIGH**: similarity >= 0.82
- **MEDIUM**: 0.65 <= similarity < 0.82
- **CONTESTED**: similarity < 0.65

### Results

The sample council processed 307 articles (slightly above the 300 target due to the minimum-1-per-language rule):

| Confidence Level | Count | Percentage |
|---|---|---|
| HIGH | 41 | 13.4% |
| MEDIUM | 223 | 72.6% |
| CONTESTED | 43 | 14.0% |

### Cross-Case Comparison

The difference in agreement distributions between CS1 and CS1-RU constitutes a substantive finding:

| | CS1 (Iran) | CS1-RU (Ukraine) |
|---|---|---|
| HIGH | 4.7% | 13.4% |
| MEDIUM | 37.6% | 72.6% |
| CONTESTED | 57.7% | 14.0% |

The Ukraine 2022 corpus exhibited approximately four times greater inter-model agreement than the Iran 2026 corpus. This suggests that the Russia-Ukraine invasion, as the largest conventional military attack in Europe since World War II, produced a more globally legible framing landscape -- one where different models (and by extension, different training corpora) converged on similar readings. The Iran strike event, by contrast, was more epistemically contested, with framing varying more sharply across media ecosystems in ways that different models captured differently.

Per-language analysis of the CS1-RU sample revealed that Polish (average similarity 0.761), Turkish (0.755), and Arabic (0.767) articles showed the highest inter-model agreement, while English articles showed the lowest (0.715) -- consistent with the hypothesis that English-language media represents a more diverse range of perspectives on the Ukraine conflict than media in languages with stronger geopolitical alignment.
