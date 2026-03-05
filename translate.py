#!/usr/bin/env python3
"""
translate.py — Helsinki-NLP translation engine for NewsKaleidoscope.

uses MarianMT models for translation, langdetect for language detection.
models are lazy-loaded on first use and cached in memory.
qwen is NEVER used for translation — only Helsinki-NLP models.
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
}

# group models need a prefix token to specify source language
# format: >>lang<< prepended to input text
GROUP_MODEL_PREFIXES = {
    "Helsinki-NLP/opus-mt-ROMANCE-en": {"pt": ">>pt<<", "ro": ">>ron<<", "fr": ">>fr<<", "es": ">>es<<", "it": ">>it<<"},
    "Helsinki-NLP/opus-mt-roa-en": {"ro": ">>ron<<", "pt": ">>pt<<"},
    "Helsinki-NLP/opus-mt-sla-en": {"hr": ">>hrv<<", "lt": ">>lit<<", "bg": ">>bul<<", "cs": ">>ces<<", "sk": ">>slk<<"},
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
        """check if a helsinki model exists for this language -> english."""
        return lang_code in HELSINKI_MODELS

    def translate(self, text, source_lang=None):
        """translate text to english using helsinki-nlp.

        args:
            text: source text
            source_lang: iso 639-1 code or language name. auto-detected if None.

        returns:
            (translated_text, detected_lang_code)
            if no model available: (None, detected_lang_code)
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

        # check if we have a model for this language
        model_name = HELSINKI_MODELS.get(lang_code)
        if not model_name:
            log.warning(f"  no helsinki model for {lang_code} -> en")
            return (None, lang_code)

        try:
            model, tokenizer = self._load_model(model_name)
        except Exception as e:
            log.error(f"  failed to load model {model_name}: {e}")
            return (None, lang_code)

        # add group model prefix if needed
        prefix = ""
        prefixes = GROUP_MODEL_PREFIXES.get(model_name, {})
        if prefixes and lang_code in prefixes:
            prefix = prefixes[lang_code] + " "

        # translate in chunks (MarianMT has ~512 token limit)
        # split text into paragraphs, translate each
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        translated_parts = []

        import torch
        for para in paragraphs:
            # further split long paragraphs into sentences
            chunks = self._split_into_chunks(para, max_chars=400)
            for chunk in chunks:
                input_text = prefix + chunk
                inputs = tokenizer(input_text, return_tensors="pt",
                                   max_length=512, truncation=True).to(self._device)
                with torch.no_grad():
                    outputs = model.generate(**inputs, max_length=512)
                result = tokenizer.decode(outputs[0], skip_special_tokens=True)
                translated_parts.append(result)
            translated_parts.append("")  # paragraph break

        translated = "\n".join(translated_parts).strip()
        return (translated, lang_code)

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
