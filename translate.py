#!/usr/bin/env python3
"""
translate.py — translation engine for NewsKaleidoscope.

translation hierarchy:
  1. Helsinki-NLP MarianMT — fast (~2s), high quality for 20+ European/Asian pairs
  2. NLLB-200 (Meta) — slower (~4s), covers 200 languages including Persian, Swahili, etc.
  3. flag as untranslated — only if both fail

qwen is NEVER used for translation. models are lazy-loaded and cached.
"""

import re
import time
import logging

from langdetect import detect, LangDetectException

log = logging.getLogger("translate")

# helsinki-nlp model registry: iso 639-1 code -> model name
# some languages use group models (ROMANCE, sla, gmq) with prefix tokens
HELSINKI_MODELS = {
    "ar": "Helsinki-NLP/opus-mt-ar-en",
    "zh": "Helsinki-NLP/opus-mt-zh-en",
    "ru": "Helsinki-NLP/opus-mt-ru-en",
    "tr": "Helsinki-NLP/opus-mt-tr-en",
    "fr": "Helsinki-NLP/opus-mt-fr-en",
    "de": "Helsinki-NLP/opus-mt-de-en",
    "es": "Helsinki-NLP/opus-mt-es-en",
    "id": "Helsinki-NLP/opus-mt-id-en",
    "ur": "Helsinki-NLP/opus-mt-ur-en",
    "ko": "Helsinki-NLP/opus-mt-ko-en",
    "it": "Helsinki-NLP/opus-mt-it-en",
    "bg": "Helsinki-NLP/opus-mt-bg-en",
    "cs": "Helsinki-NLP/opus-mt-cs-en",
    "sk": "Helsinki-NLP/opus-mt-sk-en",
    "sq": "Helsinki-NLP/opus-mt-sq-en",
    # group models for languages without direct pairs
    "pt": "Helsinki-NLP/opus-mt-ROMANCE-en",
    "ro": "Helsinki-NLP/opus-mt-roa-en",
    "hr": "Helsinki-NLP/opus-mt-sla-en",
    "no": "Helsinki-NLP/opus-mt-gmq-en",
    "nb": "Helsinki-NLP/opus-mt-gmq-en",  # norwegian bokmal
    "nn": "Helsinki-NLP/opus-mt-gmq-en",  # norwegian nynorsk
    "lt": "Helsinki-NLP/opus-mt-sla-en",  # lithuanian via slavic group (approximate)
    "el": "Helsinki-NLP/opus-mt-grk-en",  # greek (group model)
    "sr": "Helsinki-NLP/opus-mt-sla-en",  # serbian via slavic group
    "sl": "Helsinki-NLP/opus-mt-sla-en",  # slovenian via slavic group
    "ca": "Helsinki-NLP/opus-mt-ROMANCE-en",  # catalan via romance group
    "lv": "Helsinki-NLP/opus-mt-sla-en",  # latvian via slavic group (approximate)
    "uk": "Helsinki-NLP/opus-mt-sla-en",  # ukrainian via slavic group
    "bs": "Helsinki-NLP/opus-mt-sla-en",  # bosnian via slavic group
    "mk": "Helsinki-NLP/opus-mt-sla-en",  # macedonian via slavic group
}

# languages where Helsinki group models are a poor fit — skip straight to NLLB.
# latvian is Baltic (not Slavic), catalan gets confused in the ROMANCE group model.
FORCE_NLLB = {"lv", "ca"}

# NLLB-200 fallback for languages Helsinki doesn't cover
# uses FLORES-200 language codes
NLLB_MODEL = "facebook/nllb-200-distilled-600M"
NLLB_LANG_CODES = {
    "fa": "pes_Arab",   # persian/farsi
    "sw": "swh_Latn",   # swahili
    "ha": "hau_Latn",   # hausa
    "am": "amh_Ethi",   # amharic
    "yo": "yor_Latn",   # yoruba
    "ig": "ibo_Latn",   # igbo
    "zu": "zul_Latn",   # zulu
    "hi": "hin_Deva",   # hindi
    "bn": "ben_Beng",   # bengali
    "ja": "jpn_Jpan",   # japanese
    "th": "tha_Thai",   # thai
    "vi": "vie_Latn",   # vietnamese
    "ms": "zsm_Latn",   # malay
    "he": "heb_Hebr",   # hebrew
    "pl": "pol_Latn",   # polish
    "nl": "nld_Latn",   # dutch
    "sv": "swe_Latn",   # swedish
    "da": "dan_Latn",   # danish
    "fi": "fin_Latn",   # finnish
    # can also serve as backup for Helsinki languages
    "ar": "arb_Arab",
    "zh": "zho_Hans",
    "ru": "rus_Cyrl",
    "tr": "tur_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
    "ko": "kor_Hang",
    "it": "ita_Latn",
    "ro": "ron_Latn",
    "hr": "hrv_Latn",
    "bg": "bul_Cyrl",
    "cs": "ces_Latn",
    "sk": "slk_Latn",
    "sq": "sqi_Latn",
    "uk": "ukr_Cyrl",
    "no": "nob_Latn",
    "nb": "nob_Latn",
    "lt": "lit_Latn",
    "ur": "urd_Arab",
    "id": "ind_Latn",
    "el": "ell_Grek",   # greek
    "sr": "srp_Cyrl",   # serbian
    "sl": "slv_Latn",   # slovenian
    "ca": "cat_Latn",   # catalan
    "lv": "lvs_Latn",   # latvian
    "uk": "ukr_Cyrl",   # ukrainian
    "bs": "bos_Latn",   # bosnian
    "mk": "mkd_Cyrl",   # macedonian
    "hu": "hun_Latn",   # hungarian
    "et": "est_Latn",   # estonian
    "da": "dan_Latn",   # danish (already present but ensuring coverage)
}

# group models need a prefix token to specify source language
# format: >>lang<< prepended to input text
GROUP_MODEL_PREFIXES = {
    "Helsinki-NLP/opus-mt-ROMANCE-en": {"pt": ">>pt<<", "ro": ">>ron<<", "fr": ">>fr<<", "es": ">>es<<", "it": ">>it<<", "ca": ">>ca<<"},
    "Helsinki-NLP/opus-mt-roa-en": {"ro": ">>ron<<", "pt": ">>pt<<"},
    "Helsinki-NLP/opus-mt-sla-en": {"hr": ">>hrv<<", "lt": ">>lit<<", "bg": ">>bul<<", "cs": ">>ces<<", "sk": ">>slk<<", "sr": ">>srp<<", "sl": ">>slv<<", "lv": ">>lav<<", "uk": ">>ukr<<", "bs": ">>bos<<", "mk": ">>mkd<<"},
    "Helsinki-NLP/opus-mt-grk-en": {"el": ">>ell<<"},
    "Helsinki-NLP/opus-mt-gmq-en": {"no": ">>nob<<", "nb": ">>nob<<", "nn": ">>nno<<"},
}

# map common language names (from GDELT/articles.json) to iso 639-1
LANGUAGE_NAME_TO_CODE = {
    "english": "en", "arabic": "ar", "chinese": "zh", "french": "fr",
    "german": "de", "spanish": "es", "portuguese": "pt", "russian": "ru",
    "turkish": "tr", "korean": "ko", "japanese": "ja", "italian": "it",
    "persian": "fa", "farsi": "fa", "hindi": "hi", "urdu": "ur",
    "indonesian": "id", "malay": "ms", "bengali": "bn", "albanian": "sq",
    "bulgarian": "bg", "croatian": "hr", "czech": "cs", "norwegian": "no",
    "romanian": "ro", "slovak": "sk", "lithuanian": "lt", "hebrew": "he",
    "thai": "th", "vietnamese": "vi", "dutch": "nl", "polish": "pl",
    "swedish": "sv", "danish": "da", "finnish": "fi",
    "greek": "el", "serbian": "sr", "slovenian": "sl", "catalan": "ca",
    "latvian": "lv", "ukrainian": "uk", "bosnian": "bs", "macedonian": "mk",
    "hungarian": "hu", "estonian": "et",
}


class TranslationEngine:
    """helsinki-nlp translation engine with lazy model loading."""

    def __init__(self, device=None):
        # cache: model_name -> (model, tokenizer)
        self._models = {}
        if device is None:
            import torch
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self._device = device

    def _load_model(self, model_name):
        """lazy-load a MarianMT model and tokenizer."""
        if model_name in self._models:
            return self._models[model_name]

        log.info(f"loading translation model: {model_name}")
        t0 = time.time()

        from transformers import MarianMTModel, MarianTokenizer
        tokenizer = MarianTokenizer.from_pretrained(model_name)
        model = MarianMTModel.from_pretrained(model_name).to(self._device)
        model.eval()

        elapsed = time.time() - t0
        log.info(f"  loaded {model_name} in {elapsed:.1f}s")

        self._models[model_name] = (model, tokenizer)
        return model, tokenizer

    def detect_language(self, text):
        """detect language of text, return iso 639-1 code."""
        if not text or len(text.strip()) < 20:
            return "en"  # default for very short text
        try:
            # use first 1000 chars for detection (more reliable, faster)
            return detect(text[:1000])
        except LangDetectException:
            return "en"

    def lang_name_to_code(self, lang_name):
        """convert language name (e.g. 'Arabic') to iso 639-1 code."""
        if not lang_name:
            return "en"
        code = LANGUAGE_NAME_TO_CODE.get(lang_name.lower())
        if code:
            return code
        # if it's already a 2-letter code, return it
        if len(lang_name) <= 3:
            return lang_name.lower()
        return None

    def has_model(self, lang_code):
        """check if any translation model exists for this language -> english."""
        return lang_code in HELSINKI_MODELS or lang_code in NLLB_LANG_CODES

    def _load_nllb(self):
        """lazy-load NLLB-200 model for fallback translation."""
        if NLLB_MODEL in self._models:
            return self._models[NLLB_MODEL]

        log.info(f"loading NLLB-200 fallback model: {NLLB_MODEL}")
        t0 = time.time()

        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL).to(self._device)
        model.eval()

        elapsed = time.time() - t0
        log.info(f"  loaded {NLLB_MODEL} in {elapsed:.1f}s")

        self._models[NLLB_MODEL] = (model, tokenizer)
        return model, tokenizer

    def _translate_nllb(self, text, lang_code):
        """translate using NLLB-200. returns translated text or None."""
        flores_code = NLLB_LANG_CODES.get(lang_code)
        if not flores_code:
            return None

        try:
            model, tokenizer = self._load_nllb()
        except Exception as e:
            log.error(f"  failed to load NLLB model: {e}")
            return None

        import torch

        # set source language for tokenizer
        tokenizer.src_lang = flores_code

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        translated_parts = []

        for para in paragraphs:
            chunks = self._split_into_chunks(para, max_chars=400)
            for chunk in chunks:
                inputs = tokenizer(chunk, return_tensors="pt",
                                   max_length=512, truncation=True).to(self._device)
                with torch.no_grad():
                    outputs = model.generate(
                        **inputs,
                        forced_bos_token_id=tokenizer.convert_tokens_to_ids("eng_Latn"),
                        max_length=512,
                    )
                result = tokenizer.decode(outputs[0], skip_special_tokens=True)
                translated_parts.append(result)
            translated_parts.append("")

        return "\n".join(translated_parts).strip()

    def translate(self, text, source_lang=None):
        """translate text to english.

        hierarchy: Helsinki-NLP -> NLLB-200 -> None

        args:
            text: source text
            source_lang: iso 639-1 code or language name. auto-detected if None.

        returns:
            (translated_text, detected_lang_code)
            if both engines fail: (None, detected_lang_code)
        """
        if not text or not text.strip():
            return (None, "en")

        # resolve language code
        if source_lang and len(source_lang) > 3:
            lang_code = self.lang_name_to_code(source_lang)
        else:
            lang_code = source_lang

        if not lang_code:
            lang_code = self.detect_language(text)

        # english doesn't need translation
        if lang_code == "en":
            return (text, "en")

        # tier 1: try Helsinki-NLP (fast, high quality for supported pairs)
        # skip Helsinki for languages where group models produce poor results
        model_name = HELSINKI_MODELS.get(lang_code) if lang_code not in FORCE_NLLB else None
        if model_name:
            try:
                model, tokenizer = self._load_model(model_name)
                translated = self._translate_helsinki(text, lang_code, model, tokenizer, model_name)
                if translated:
                    return (translated, lang_code)
            except Exception as e:
                log.warning(f"  helsinki failed for {lang_code}: {e}, trying NLLB fallback")

        # tier 2: try NLLB-200 (slower, but covers 200 languages)
        if lang_code in NLLB_LANG_CODES:
            log.info(f"  using NLLB-200 for {lang_code} -> en")
            translated = self._translate_nllb(text, lang_code)
            if translated:
                return (translated, lang_code)

        log.warning(f"  no translation model available for {lang_code} -> en")
        return (None, lang_code)

    def _translate_helsinki(self, text, lang_code, model, tokenizer, model_name):
        """translate using a Helsinki MarianMT model."""
        # add group model prefix if needed
        prefix = ""
        prefixes = GROUP_MODEL_PREFIXES.get(model_name, {})
        if prefixes and lang_code in prefixes:
            prefix = prefixes[lang_code] + " "

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        translated_parts = []

        import torch
        for para in paragraphs:
            chunks = self._split_into_chunks(para, max_chars=400)
            for chunk in chunks:
                input_text = prefix + chunk
                inputs = tokenizer(input_text, return_tensors="pt",
                                   max_length=512, truncation=True).to(self._device)
                with torch.no_grad():
                    outputs = model.generate(**inputs, max_length=512)
                result = tokenizer.decode(outputs[0], skip_special_tokens=True)
                translated_parts.append(result)
            translated_parts.append("")

        return "\n".join(translated_parts).strip()

    def _split_into_chunks(self, text, max_chars=400):
        """split text into sentence-level chunks for translation."""
        if len(text) <= max_chars:
            return [text]

        # split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) > max_chars and current:
                chunks.append(current.strip())
                current = sent
            else:
                current = current + " " + sent if current else sent
        if current:
            chunks.append(current.strip())
        return chunks

    def extract_original_terms(self, text, lang_code):
        """extract key political terms, named entities, place names from source text.

        uses simple regex-based NER: capitalized noun phrases, quoted terms,
        and common political vocabulary patterns.

        returns dict with: terms, entities, places
        """
        if not text or lang_code == "en":
            return {"terms": [], "entities": [], "places": []}

        # extract quoted terms (common in political text)
        quoted = re.findall(r'["\u201c\u201d\u00ab\u00bb]([^"\u201c\u201d\u00ab\u00bb]{2,40})["\u201c\u201d\u00ab\u00bb]', text)

        # extract capitalized multi-word phrases (likely proper nouns / entities)
        # works for latin scripts
        cap_phrases = re.findall(r'\b([A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+(?:\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+)+)\b', text)

        # extract arabic/persian specific patterns (common political terms)
        arabic_terms = []
        if lang_code in ("ar", "fa", "ur"):
            # common arabic/persian political phrases (3+ char sequences)
            arabic_terms = re.findall(r'[\u0600-\u06FF\u0750-\u077F]{3,}(?:\s+[\u0600-\u06FF\u0750-\u077F]{3,}){0,3}', text)
            arabic_terms = list(set(arabic_terms))[:10]

        # extract CJK terms (Chinese/Japanese/Korean)
        cjk_terms = []
        if lang_code in ("zh", "ja", "ko"):
            cjk_terms = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]{2,8}', text)
            cjk_terms = list(set(cjk_terms))[:10]

        # deduplicate and limit
        entities = list(set(cap_phrases))[:10]
        terms = list(set(quoted))[:8] + arabic_terms + cjk_terms

        return {
            "terms": terms[:15],
            "entities": entities[:10],
            "places": [],  # would need gazetteer for reliable place extraction
        }


# ── standalone testing ─────────────────────────────────────────
def test_translation():
    """test translation engine on sample articles from the cache."""
    import os
    import json

    engine = TranslationEngine()

    # load articles to find non-english ones
    with open("analysis/all_results.json", "r", encoding="utf-8") as f:
        results = json.load(f)

    # find one article per target language
    test_langs = {"Arabic": None, "Chinese": None, "French": None, "Russian": None,
                  "German": None, "Spanish": None, "Portuguese": None, "Korean": None}
    for r in results:
        lang = r.get("sourcelang", "")
        if lang in test_langs and test_langs[lang] is None:
            test_langs[lang] = r

    print(f"\n{'='*60}")
    print(f"TRANSLATION ENGINE TEST")
    print(f"{'='*60}")

    times = []
    for lang_name, article in test_langs.items():
        if article is None:
            print(f"\n  {lang_name}: no article found in corpus")
            continue

        url = article["url"]
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join("cache", f"{url_hash}.txt")

        if not os.path.exists(cache_path):
            print(f"\n  {lang_name}: cache miss for {url[:50]}...")
            continue

        with open(cache_path, "r", encoding="utf-8") as f:
            text = f.read()

        if not text.strip():
            print(f"\n  {lang_name}: empty cached text")
            continue

        print(f"\n  {lang_name} ({article['domain']}):")
        print(f"    source text: {len(text)} chars")

        # detect language
        detected = engine.detect_language(text)
        print(f"    detected: {detected}")

        # translate
        t0 = time.time()
        translated, lang_code = engine.translate(text[:2000], source_lang=lang_name)
        elapsed = time.time() - t0
        times.append(elapsed)

        if translated:
            print(f"    translated: {len(translated)} chars in {elapsed:.2f}s")
            print(f"    preview: {translated[:150]}...")

            # extract original terms
            terms = engine.extract_original_terms(text[:2000], lang_code)
            if terms["terms"]:
                print(f"    original terms: {terms['terms'][:5]}")
            if terms["entities"]:
                print(f"    entities: {terms['entities'][:5]}")
        else:
            print(f"    NO MODEL AVAILABLE for {lang_code}")

    if times:
        avg = sum(times) / len(times)
        print(f"\n{'='*60}")
        print(f"BENCHMARK: {len(times)} articles translated")
        print(f"  average: {avg:.2f}s per article")
        print(f"  total: {sum(times):.2f}s")
        print(f"{'='*60}")

    # report missing models
    print(f"\nMISSING HELSINKI MODELS:")
    all_langs = set()
    for r in results:
        code = engine.lang_name_to_code(r.get("sourcelang", ""))
        if code and code != "en":
            all_langs.add((r.get("sourcelang", ""), code))
    for name, code in sorted(all_langs):
        if not engine.has_model(code):
            count = sum(1 for r in results if engine.lang_name_to_code(r.get("sourcelang", "")) == code)
            print(f"  {name} ({code}): {count} articles — NO MODEL")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    test_translation()
