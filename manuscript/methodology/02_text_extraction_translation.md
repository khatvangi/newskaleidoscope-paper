# Text Extraction and Translation

## Text Extraction

Article text was extracted from source URLs using a three-tier strategy implemented in `pipeline.py` (function `fetch_article_text()`) and the standalone `scripts/fetch_text_cs1ru.py`:

1. **Trafilatura** (preferred): The trafilatura library was used as the primary extraction engine, invoked with `include_comments=False` and `include_tables=False` to isolate article body text. Trafilatura's heuristic-based extraction handles diverse HTML structures across international news sites.

2. **newspaper3k** (fallback): When trafilatura failed (e.g., sites with unusual JavaScript rendering or anti-scraping measures), the newspaper3k library served as a secondary extractor. The `Article` class was used to download, parse, and extract the `.text` property.

3. **Wayback Machine** (archival fallback): For articles whose URLs were no longer accessible -- particularly relevant for CS1-RU (Ukraine 2022), where articles were four years old -- an `archive_fetcher` module queried the Internet Archive's Wayback CDX API. Archived HTML snapshots were retrieved and text was extracted from the cached versions.

Extracted text was cached to the filesystem using an MD5 hash of the article URL as the filename (e.g., `cache/{md5(url)}.txt`). On subsequent pipeline runs, cached text was loaded directly without re-extraction. This cache-by-URL-hash scheme was shared across all data sources (GDELT, World News API, Reddit), providing a uniform text retrieval interface.

### Extraction Success Rates

For CS1-RU, text extraction succeeded for 1,456 out of 1,689 articles requiring extraction (86.2%). The Wayback Machine was critical for this case study, recovering articles from domains that had restructured or gone offline since February 2022. For CS1 and CS2, which involved contemporaneous articles, extraction success rates were higher as original URLs remained live.

## Language Detection

Language detection was performed using the `langdetect` library (a Python port of Google's language-detection library). The `TranslationEngine.detect_language()` method applied detection to the first 1,000 characters of each article's text, which provides more reliable detection than shorter snippets while remaining computationally efficient. For articles with fewer than 20 characters of text, English was assumed as a default.

The GDELT API and World News API both provide language metadata with article records; however, these were used as hints rather than ground truth. The `langdetect`-based verification caught cases where GDELT metadata was incorrect (e.g., articles labeled as one language that were actually written in another).

A mapping from GDELT's language names (e.g., "Arabic", "Chinese", "French") to ISO 639-1 codes was maintained in `translate.py` (`LANGUAGE_NAME_TO_CODE` dictionary, 44 language mappings).

## Translation Pipeline

All non-English articles were translated to English prior to LLM-based framing analysis. Translation was performed locally on the nitrogen machine (RTX A4000 16GB) using open-source neural machine translation models. No cloud translation APIs were used.

### Translation Hierarchy

The `TranslationEngine` class (`translate.py`) implemented a two-tier translation hierarchy:

**Tier 1: Helsinki-NLP MarianMT** -- Fast (~2 seconds per article), high quality for supported language pairs. The implementation used the HuggingFace `transformers` library to load `MarianMTModel` and `MarianTokenizer` from pretrained checkpoints. Models were lazy-loaded and cached in memory to avoid redundant initialization across articles in the same language.

Twenty-six language pairs were registered in the `HELSINKI_MODELS` dictionary, including both direct models and group models:

- **Direct models** (e.g., `Helsinki-NLP/opus-mt-ar-en` for Arabic, `Helsinki-NLP/opus-mt-zh-en` for Chinese): 16 languages with dedicated bilingual translation models.
- **Group models** (e.g., `Helsinki-NLP/opus-mt-ROMANCE-en` for Portuguese and Catalan, `Helsinki-NLP/opus-mt-sla-en` for Croatian, Serbian, Slovenian, Ukrainian, etc., `Helsinki-NLP/opus-mt-gmq-en` for Norwegian): 10 additional languages served by multilingual group models. Group models required a source-language prefix token (e.g., `>>pt<<` for Portuguese in the ROMANCE group model, `>>ukr<<` for Ukrainian in the Slavic group model).

Two languages (Latvian and Catalan) were flagged in a `FORCE_NLLB` set to skip Helsinki entirely, as the Slavic and ROMANCE group models respectively produced poor-quality translations for these languages.

**Tier 2: Meta NLLB-200** (`facebook/nllb-200-distilled-600M`) -- Slower (~4 seconds per article) but covering 200 languages. Used as a fallback when Helsinki-NLP did not have a suitable model for a given language, and as the primary engine for languages such as Persian, Swahili, Hausa, Amharic, Hindi, Bengali, Japanese, Thai, Vietnamese, Hebrew, Polish, Dutch, Swedish, Danish, and Finnish. The NLLB model used FLORES-200 language codes (e.g., `pes_Arab` for Persian, `swh_Latn` for Swahili, `hin_Deva` for Hindi). Target language was set to `eng_Latn` via `forced_bos_token_id`.

In total, the NLLB fallback covered 38 language codes (including backup coverage for all Helsinki-supported languages).

### Text Chunking

Both translation tiers used a sentence-level chunking strategy to stay within model context limits. The `_split_into_chunks()` method split text into segments of at most 400 characters at sentence boundaries (splitting on `(?<=[.!?])\s+`). Each chunk was translated independently, and results were joined with newlines to preserve paragraph structure. The maximum tokenizer input length was set to 512 tokens with truncation enabled.

### Quality Check

A length-ratio check was applied to detect content loss during translation. If the translated text was substantially shorter than expected relative to the source text length, a warning was logged. This heuristic caught cases where the translation model truncated or failed to process portions of the input.

### Original-Language Framing Preservation

Before translation, key framing terms were extracted from the original-language text. The `TranslationEngine.extract_original_terms()` method used regex-based extraction to identify:

- Quoted terms (using Unicode quotation mark variants including guillemets)
- Capitalized multi-word phrases (likely proper nouns and named entities, for Latin-script languages)
- Arabic/Persian script sequences (3+ character runs, for `ar`, `fa`, `ur`)
- CJK character sequences (2-8 character runs, for `zh`, `ja`, `ko`)

These original-language terms were stored in the `original_language_terms` JSONB column of the `articles` table and later available during framing analysis.

Additionally, a separate LLM-based original-language framing extraction step was performed for non-English articles (see Section 3). The `FRAMING_EXTRACT_PROMPT` in `pipeline.py` instructed the LLM to identify 5-8 framing terms in the original language, provide English approximations, flag contested translations where meaning was lost, and classify the emotional register (neutral_analytical, alarmed, triumphant, mournful, ironic, propagandistic, diplomatic).

### Translation Success Rate

Translation succeeded for 99.9% of non-English articles across all case studies. A single Gujarati article in the CS1-RU corpus could not be translated by either Helsinki-NLP or NLLB-200, as Gujarati was not covered by the available model configurations. This article was flagged as untranslated and excluded from framing analysis.

For CS1-RU specifically, 1,006 out of 1,007 non-English articles were successfully translated.
