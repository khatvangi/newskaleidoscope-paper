# Model Configurations

All LLM inference runs on boron (2x TITAN RTX 48GB total VRAM) via llama-server with OpenAI-compatible API at `http://boron:11434/v1/chat/completions`.

## LLM Models

### Qwen3-32B (Primary — Pass 1 and Council)

| Parameter | Value |
|-----------|-------|
| Model file | `qwen3-32b-q4km.gguf` |
| Quantization | Q4_K_M (4-bit, ~20GB) |
| Context size | 16384 tokens |
| GPU layers | 99 (all layers offloaded) |
| Tensor split | 0.5, 0.5 (equal across 2 GPUs) |
| Temperature (Pass 1) | 0.3 |
| Temperature (Council) | 0.1 |
| Max tokens (Pass 1) | 3072 |
| Max tokens (Council) | 2048 |
| Timeout (Pass 1) | 180 seconds |
| Timeout (Council) | 120 seconds |
| Training lineage | Alibaba — strong on Asian/Middle Eastern political text |

Source: `pipeline.py` lines 34, 155-164; `council.py` lines 42-46, 115-121, 159-168

### Gemma-3-27B-IT (Council Member)

| Parameter | Value |
|-----------|-------|
| Model file | `google_gemma-3-27b-it-Q4_K_M.gguf` |
| Quantization | Q4_K_M (4-bit, ~16.5GB) |
| Context size | 16384 tokens |
| GPU layers | 99 |
| Tensor split | 0.5, 0.5 |
| Temperature | 0.1 |
| Max tokens | 2048 |
| Timeout | 120 seconds |
| Parallel mode | 4 (for sample council) |
| Training lineage | Google — distinct training corpus from Qwen |

Source: `council.py` lines 42-46; `scripts/sample_council.py` lines 53-56, 93-100

### Mistral-Small-3.1-24B-Instruct (Council Member)

| Parameter | Value |
|-----------|-------|
| Model file | `Mistral-Small-3.1-24B-Instruct-2503-Q4_K_M.gguf` |
| Quantization | Q4_K_M (4-bit, ~14.3GB) |
| Context size | 16384 tokens (boron) or 4096 tokens (nitrogen RTX A4000) |
| GPU layers | 99 |
| Tensor split | 0.5, 0.5 (boron) |
| Temperature | 0.1 |
| Max tokens | 2048 |
| Timeout | 120 seconds |
| Training lineage | Mistral AI — European emphasis, diplomatic register |

Source: `council.py` lines 42-46

### llama-server Launch Command

```bash
llama-server \
  --model /storage/kiran-stuff/llama.cpp/models/<model.gguf> \
  --tensor-split 0.5,0.5 \
  --host 0.0.0.0 \
  --port 11434 \
  --ctx-size 16384 \
  --n-gpu-layers 99
```

With parallel mode (sample council):
```bash
llama-server \
  --model /storage/kiran-stuff/llama.cpp/models/<model.gguf> \
  --tensor-split 0.5,0.5 \
  --host 0.0.0.0 \
  --port 11434 \
  --ctx-size 16384 \
  --n-gpu-layers 99 \
  --parallel 4
```

## Sentence Embedding Model

| Parameter | Value |
|-----------|-------|
| Model | `all-MiniLM-L6-v2` |
| Library | `sentence-transformers` |
| Purpose | Council consensus measurement (cosine similarity between primary_frame outputs) |
| Runs on | nitrogen (CPU) |

Source: `council.py` lines 222-229; `scripts/sample_council.py` lines 267-270

## Translation Models

Translation runs locally on nitrogen (RTX A4000 16GB or CPU). LLMs are never used for translation.

### Tier 1: Helsinki-NLP MarianMT

| Parameter | Value |
|-----------|-------|
| Library | `transformers` (MarianMTModel, MarianTokenizer) |
| Speed | ~2 seconds per article |
| Max input length | 512 tokens per chunk |
| Chunk size | 400 characters (split on sentence boundaries) |
| Device | CUDA if available, else CPU |

**Direct language pair models (14):**

| Language | Model |
|----------|-------|
| Arabic | `Helsinki-NLP/opus-mt-ar-en` |
| Chinese | `Helsinki-NLP/opus-mt-zh-en` |
| Russian | `Helsinki-NLP/opus-mt-ru-en` |
| Turkish | `Helsinki-NLP/opus-mt-tr-en` |
| French | `Helsinki-NLP/opus-mt-fr-en` |
| German | `Helsinki-NLP/opus-mt-de-en` |
| Spanish | `Helsinki-NLP/opus-mt-es-en` |
| Indonesian | `Helsinki-NLP/opus-mt-id-en` |
| Urdu | `Helsinki-NLP/opus-mt-ur-en` |
| Korean | `Helsinki-NLP/opus-mt-ko-en` |
| Italian | `Helsinki-NLP/opus-mt-it-en` |
| Bulgarian | `Helsinki-NLP/opus-mt-bg-en` |
| Czech | `Helsinki-NLP/opus-mt-cs-en` |
| Slovak | `Helsinki-NLP/opus-mt-sk-en` |
| Albanian | `Helsinki-NLP/opus-mt-sq-en` |

**Group models (with source language prefix tokens):**

| Model | Languages | Prefix format |
|-------|-----------|---------------|
| `Helsinki-NLP/opus-mt-ROMANCE-en` | Portuguese (`>>pt<<`), Catalan (`>>ca<<`) | `>>lang<<` prepended |
| `Helsinki-NLP/opus-mt-roa-en` | Romanian (`>>ron<<`) | `>>lang<<` prepended |
| `Helsinki-NLP/opus-mt-sla-en` | Croatian (`>>hrv<<`), Lithuanian (`>>lit<<`), Serbian (`>>srp<<`), Slovenian (`>>slv<<`), Ukrainian (`>>ukr<<`), Bosnian (`>>bos<<`), Macedonian (`>>mkd<<`), Latvian (`>>lav<<`) | `>>lang<<` prepended |
| `Helsinki-NLP/opus-mt-grk-en` | Greek (`>>ell<<`) | `>>lang<<` prepended |
| `Helsinki-NLP/opus-mt-gmq-en` | Norwegian Bokmal (`>>nob<<`), Norwegian Nynorsk (`>>nno<<`) | `>>lang<<` prepended |

**Forced NLLB fallback:** Latvian (`lv`) and Catalan (`ca`) skip Helsinki group models and go directly to NLLB due to poor group model fit.

Source: `translate.py` lines 23-55, 59, 122-128

### Tier 2: NLLB-200 (Meta)

| Parameter | Value |
|-----------|-------|
| Model | `facebook/nllb-200-distilled-600M` |
| Library | `transformers` (AutoModelForSeq2SeqLM, AutoTokenizer) |
| Speed | ~4 seconds per article |
| Max input length | 512 tokens per chunk |
| Chunk size | 400 characters |
| Target language token | `eng_Latn` (forced BOS) |
| Languages covered | 200 (FLORES-200 language codes) |
| Device | CUDA if available, else CPU |

**Additional languages not covered by Helsinki (primary NLLB targets):**

Persian/Farsi (`pes_Arab`), Swahili (`swh_Latn`), Hausa (`hau_Latn`), Amharic (`amh_Ethi`), Yoruba (`yor_Latn`), Igbo (`ibo_Latn`), Zulu (`zul_Latn`), Hindi (`hin_Deva`), Bengali (`ben_Beng`), Japanese (`jpn_Jpan`), Thai (`tha_Thai`), Vietnamese (`vie_Latn`), Malay (`zsm_Latn`), Hebrew (`heb_Hebr`), Polish (`pol_Latn`), Dutch (`nld_Latn`), Swedish (`swe_Latn`), Danish (`dan_Latn`), Finnish (`fin_Latn`), Hungarian (`hun_Latn`), Estonian (`est_Latn`)

NLLB also serves as fallback for all Helsinki-supported languages.

Source: `translate.py` lines 63-118, 204-258

### Translation Hierarchy

1. Helsinki-NLP MarianMT (fast, high quality for supported pairs)
2. NLLB-200 fallback (slower, covers 200 languages)
3. Flagged as untranslated (if both fail)

LLMs are never used for translation.

Source: `translate.py` lines 260-309
