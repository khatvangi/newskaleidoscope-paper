#!/usr/bin/env python3
"""
pipeline.py — fetch article text, translate if needed, extract epistemic positions.
sends all LLM work to boron via Ollama API.
"""

import json
import logging
import os
import sys
import time
import hashlib
import urllib.request
import urllib.error

# ── config ────────────────────────────────────────────────────────
OLLAMA_URL = "http://boron:11434"
ARTICLES_FILE = "articles.json"
OUTLETS_FILE = "outlets.json"
ANALYSIS_DIR = "analysis"
CACHE_DIR = "cache"
LOG_FILE = "logs/pipeline.log"
OLLAMA_TIMEOUT = 120  # seconds per LLM call

# ── logging setup ─────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs(ANALYSIS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("pipeline")


# ── model discovery ───────────────────────────────────────────────
def find_best_model():
    """find the best available model on boron. prefers qwen2.5:72b, falls back to largest."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.error(f"cannot reach Ollama on boron: {e}")
        sys.exit(1)

    models = data.get("models", [])
    if not models:
        log.error("no models available on boron")
        sys.exit(1)

    # prefer qwen2.5:72b
    names = [m["name"] for m in models]
    if "qwen2.5:72b" in names:
        return "qwen2.5:72b"

    # fallback: pick largest by size
    best = max(models, key=lambda m: m.get("size", 0))
    log.info(f"qwen2.5:72b not found, using fallback: {best['name']}")
    return best["name"]


# ── article fetching ──────────────────────────────────────────────
def fetch_article_text(url):
    """fetch and extract article body text. uses trafilatura, falls back to newspaper3k."""
    # check cache first
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            text = f.read()
        if text.strip():
            log.info(f"  cache hit: {url[:60]}...")
            return text

    text = None

    # try trafilatura first
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False,
                                       include_tables=False)
    except ImportError:
        log.warning("trafilatura not installed, trying newspaper3k")
    except Exception as e:
        log.warning(f"  trafilatura failed for {url[:60]}: {e}")

    # fallback to newspaper3k
    if not text:
        try:
            from newspaper import Article
            article = Article(url)
            article.download()
            article.parse()
            text = article.text
        except ImportError:
            log.warning("newspaper3k not installed either")
        except Exception as e:
            log.warning(f"  newspaper3k failed for {url[:60]}: {e}")

    if text and text.strip():
        # cache it
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text

    return None


# ── ollama calls ──────────────────────────────────────────────────
def ollama_generate(model, prompt, timeout=OLLAMA_TIMEOUT):
    """send a prompt to Ollama on boron. returns response text."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 2048,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("response", "")
    except urllib.error.URLError as e:
        log.error(f"  ollama connection error: {e}")
        return None
    except Exception as e:
        log.error(f"  ollama error: {e}")
        return None


def translate_text(model, text):
    """translate non-English text to English via Ollama."""
    prompt = f"Translate to English. Output translation only.\n\n{text[:3000]}"
    return ollama_generate(model, prompt)


POSITION_PROMPT = """You are analyzing a news article about the US-Israel strikes on Iran.
Extract the following in JSON format:

{{
  "factual_claims": ["list of specific verifiable claims made"],
  "position_type": one of [
    "endorsement",
    "procedural_objection",
    "sovereignty_opposition",
    "great_power_framing",
    "non_aligned_ambiguity",
    "religious_framing",
    "whataboutism_cynical",
    "whataboutism_legitimate"
  ],
  "historical_anchors": ["what historical events does this article invoke as context"],
  "who_is_quoted": ["list of authorities cited"],
  "what_is_omitted": ["what obvious relevant context does this article not mention"],
  "key_framing_language": ["3-5 specific words or phrases that reveal the frame"],
  "one_sentence_summary": "single sentence capturing this outlet's essential position"
}}

IMPORTANT: Output ONLY valid JSON, no other text.

Article:
{article_text}"""


def extract_position(model, text):
    """run position extraction prompt on article text."""
    # truncate to ~3000 chars to fit context
    truncated = text[:3000]
    prompt = POSITION_PROMPT.format(article_text=truncated)
    raw = ollama_generate(model, prompt)
    if not raw:
        return None

    # try to parse JSON from response
    # the model sometimes wraps JSON in markdown code blocks
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # strip markdown code fences
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # try to find JSON object in the response
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                log.warning(f"  could not parse LLM JSON output")
                return {"raw_response": raw}

    return {"raw_response": raw}


# ── main pipeline ─────────────────────────────────────────────────
def run_pipeline(limit=None):
    """run the full analysis pipeline."""
    # load articles
    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    if limit:
        articles = articles[:limit]
        log.info(f"processing {limit} articles (limited run)")
    else:
        log.info(f"processing all {len(articles)} articles")

    # discover model
    model = find_best_model()
    log.info(f"using model: {model}")

    # load outlet registry for matching
    outlet_domains = {}
    if os.path.exists(OUTLETS_FILE):
        with open(OUTLETS_FILE, "r", encoding="utf-8") as f:
            outlets = json.load(f)
        outlet_domains = {o["domain"]: o for o in outlets}

    results = []
    for i, article in enumerate(articles):
        url = article.get("url", "")
        domain = article.get("domain", "unknown")
        title = article.get("title", "untitled")
        lang = article.get("sourcelang", "English")
        country = article.get("sourcecountry", "unknown")

        log.info(f"[{i+1}/{len(articles)}] {domain} — {title[:60]}...")

        # step 1: fetch article text
        text = fetch_article_text(url)
        if not text:
            log.warning(f"  SKIP: could not fetch article text")
            continue

        # step 2: translate if non-English
        if lang.lower() not in ("english", "eng", "en"):
            log.info(f"  translating from {lang}...")
            translated = translate_text(model, text)
            if translated:
                text = translated
            else:
                log.warning(f"  translation failed, using original text")

        # step 3: extract position
        log.info(f"  extracting position...")
        position = extract_position(model, text)
        if not position:
            log.warning(f"  SKIP: position extraction failed")
            continue

        # enrich with metadata
        outlet_info = outlet_domains.get(domain, {})
        result = {
            "url": url,
            "title": title,
            "domain": domain,
            "sourcecountry": country,
            "sourcelang": lang,
            "outlet_name": outlet_info.get("name", domain),
            "outlet_tier": outlet_info.get("tier", 0),
            "outlet_region": outlet_info.get("region", "unknown"),
            "outlet_bias_notes": outlet_info.get("bias_notes", ""),
            "analysis": position,
        }
        results.append(result)

        # save per-article result
        safe_domain = domain.replace("/", "_").replace(".", "_")
        out_path = os.path.join(ANALYSIS_DIR, f"{safe_domain}_{i}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        log.info(f"  ✓ position: {position.get('position_type', 'unknown')}")

    # save combined results
    combined_path = os.path.join(ANALYSIS_DIR, "all_results.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # print summary
    log.info(f"\n{'='*60}")
    log.info(f"PIPELINE COMPLETE")
    log.info(f"  articles processed: {len(results)}/{len(articles)}")
    if results:
        positions = {}
        for r in results:
            pt = r["analysis"].get("position_type", "unknown")
            positions[pt] = positions.get(pt, 0) + 1
        log.info(f"  position clusters:")
        for pt, count in sorted(positions.items(), key=lambda x: -x[1]):
            log.info(f"    {pt}: {count}")
    log.info(f"  results: {combined_path}")
    log.info(f"{'='*60}")

    return results


if __name__ == "__main__":
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            print(f"usage: {sys.argv[0]} [limit]")
            sys.exit(1)
    run_pipeline(limit=limit)
