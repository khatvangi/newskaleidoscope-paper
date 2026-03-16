# Computational Infrastructure

## Design Principle: Fully Local Inference

All LLM inference, translation, and embedding computation in the NewsKaleidoscope pipeline was performed on local hardware. No cloud-hosted APIs (OpenAI, Anthropic, Google, etc.) were used for any analytical step. This design choice was motivated by three considerations: (1) reproducibility -- the exact model weights and quantization used are specified and archived; (2) cost -- processing thousands of articles through commercial APIs would incur substantial expense; and (3) data sovereignty -- article texts from sensitive geopolitical coverage were not transmitted to third-party servers.

## Hardware

The pipeline operated across two networked machines:

| Machine | Role | GPU | CPU | RAM |
|---|---|---|---|---|
| boron | LLM inference (Pass 1, council, clustering) | 2x NVIDIA TITAN RTX (24 GB each, 48 GB total) | 64 cores | -- |
| nitrogen | Pipeline orchestration, text extraction, translation, embedding, web serving | NVIDIA RTX A4000 (16 GB) | -- | -- |

The two machines communicated over a local network, with llama-server on boron exposing an OpenAI-compatible API at `http://boron:11434`. Pipeline scripts on nitrogen issued HTTP requests to this endpoint. Server lifecycle management (starting, stopping, model swapping) was performed via SSH.

## LLM Serving: llama-server

LLM inference was served by llama-server from the llama.cpp project. Models were stored on boron at `/storage/kiran-stuff/llama.cpp/models/` in GGUF (GPT-Generated Unified Format) quantized format.

### Standard Configuration

The standard launch command for single-model inference (Pass 1, clustering):

```
llama-server \
  --model <path-to-gguf> \
  --tensor-split 0.5,0.5 \
  --host 0.0.0.0 \
  --port 11434 \
  --ctx-size 16384 \
  --n-gpu-layers 99
```

Key parameters:

- `--tensor-split 0.5,0.5`: Distributes model layers evenly across both TITAN RTX GPUs, enabling 32B-class models to fit in memory.
- `--ctx-size 16384`: Context window of 16,384 tokens, sufficient for the longest prompts (Pass 2 clustering with ~80 article summaries).
- `--n-gpu-layers 99`: Offloads all layers to GPU, eliminating CPU-based inference for maximum throughput.

### Parallel Configuration for Council

During the sample council phase, the `--parallel 4` flag was added to enable concurrent request processing:

```
llama-server \
  --model <path-to-gguf> \
  --tensor-split 0.5,0.5 \
  --host 0.0.0.0 \
  --port 11434 \
  --ctx-size 16384 \
  --n-gpu-layers 99 \
  --parallel 4
```

This allowed 4 simultaneous inference requests, providing approximately 4x throughput for the sample council's Gemma-27B pass. The client-side `concurrent.futures.ThreadPoolExecutor` with 4 workers matched the server's parallel capacity.

### Model Swapping

The council protocol required switching between models (Qwen, Gemma, Mistral). Since only one model could fit on the GPUs at a time, model swapping was performed by:

1. Killing the running llama-server process via `ssh boron "pkill -f llama-server"`
2. Waiting 2 seconds for GPU memory release
3. Starting a new llama-server instance with the next model's GGUF file
4. Polling the `/v1/models` endpoint every 3 seconds until the server reported ready (up to 180 seconds)
5. Sending a warmup prompt to force complete model loading

Model load times were approximately 30-60 seconds per model depending on file size.

## Translation Infrastructure

Translation was performed on nitrogen using the RTX A4000 GPU. Helsinki-NLP MarianMT models (~300 MB each) and the NLLB-200-distilled-600M model (~1.2 GB) were loaded into GPU memory via the HuggingFace `transformers` library with PyTorch. Models were lazy-loaded on first use for each language and cached in memory for the duration of the pipeline run.

Translation throughput was approximately 2 seconds per article for Helsinki-NLP models and 4 seconds per article for NLLB-200.

## Embedding Infrastructure

Sentence similarity for council consensus measurement used the `all-MiniLM-L6-v2` model from the sentence-transformers library (22 million parameters, ~80 MB). This model was loaded on nitrogen and produced 384-dimensional embeddings. Cosine similarity computation was performed via NumPy.

## Database

All analytical data was stored in a PostgreSQL database (`newskaleidoscope`) running on nitrogen. The database schema included tables for `events`, `sources`, `articles`, `analyses`, `llm_council_verdicts`, `clusters`, and `cluster_memberships`, with appropriate foreign key relationships and JSONB columns for flexible semi-structured data.

Connection string: `postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope`.

Key indexing: GIN indexes on JSONB columns (`absence_flags`, `positions`, `internal_tensions`, `unspeakable_positions`, `original_language_terms`) enabled efficient querying across analytical dimensions. A full-text search index (`ix_articles_fts`) was maintained on `translated_text` for corpus-wide text search.

## Approximate Compute Times

| Task | Case Study | Duration | Hardware |
|---|---|---|---|
| Pass 1 analysis (Qwen3-32B) | CS1 (1,267 articles) | ~15-20 hours | boron (2x TITAN RTX) |
| Pass 1 analysis (Qwen3-32B) | CS1-RU (1,863 articles) | ~20-25 hours | boron (2x TITAN RTX) |
| Full council (3 models x 1,267) | CS1 | ~45-50 hours | boron (2x TITAN RTX) |
| Sample council (Gemma, parallel 4, 307 articles) | CS1-RU | ~4-5 hours | boron (2x TITAN RTX) |
| Translation (MarianMT + NLLB) | CS1-RU (1,007 non-English) | ~1-2 hours | nitrogen (RTX A4000) |
| Text extraction | CS1-RU (1,689 articles) | ~3-4 hours | nitrogen (network-bound) |
| Chunked hierarchical clustering | Per event | ~2-3 hours | boron (2x TITAN RTX) |

Total compute time across all case studies was approximately 150-200 GPU-hours, spread across multiple sessions over a two-week period.

## Operational Notes

- **GPU contention**: Whisper transcription (for Tier 3 audio sources) and LLM inference both required boron's GPUs. These tasks were never run concurrently; the pipeline documentation explicitly warns against simultaneous Whisper and Ollama/llama-server usage.
- **Server idle behavior**: llama-server was observed to consume 99.9% CPU even when idle, necessitating manual shutdown after each analytical session.
- **Fault tolerance**: All pipeline components were designed to skip failures rather than halt. Network timeouts, JSON parse errors, and individual article failures were logged but did not terminate the pipeline. Resume logic checked for existing database records before re-processing.
- **Immutability**: Consistent with the project's research-record philosophy, no analytical data was ever overwritten or deleted. Each pipeline run produced new rows with timestamped `run_id` values. Previous results, including failed experiments, were preserved as part of the methodological record.
