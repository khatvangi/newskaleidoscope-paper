#!/usr/bin/env python3
"""
pipeline.py — two-pass epistemic analysis of global news coverage.

pass 1 (per-article): open-ended framing description in article's own vocabulary.
    no predefined categories. just: "how does this article frame the event?"
pass 2 (post-corpus): cluster the free-text descriptions into emergent categories.
    some will map to expected patterns. the ones that don't are the discovery.

design principles:
- taxonomy emerges from data, not imposed on it
- original-language framing is preserved before translation
- country context injected to compensate for LLM's Western training bias
- tension within articles is captured, not flattened
- absence is analyzed at corpus level after all articles processed
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
CONTEXTS_FILE = "country_contexts.json"
ANALYSIS_DIR = "analysis"
CACHE_DIR = "cache"
LOG_FILE = "logs/pipeline.log"
OLLAMA_TIMEOUT = 180  # seconds per LLM call

# top world languages by speaker count for coverage audit
TOP_LANGUAGES = [
    "English", "Mandarin Chinese", "Hindi", "Spanish", "French",
    "Arabic", "Bengali", "Portuguese", "Russian", "Swahili",
    "Hausa", "Japanese", "German", "Korean", "Turkish",
]

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
    """find the best available model on boron."""
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

    names = [m["name"] for m in models]
    if "qwen2.5:72b" in names:
        return "qwen2.5:72b"

    best = max(models, key=lambda m: m.get("size", 0))
    log.info(f"qwen2.5:72b not found, using fallback: {best['name']}")
    return best["name"]


# ── article fetching ──────────────────────────────────────────────
def fetch_article_text(url):
    """fetch and extract article body text."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            text = f.read()
        if text.strip():
            log.info(f"  cache hit: {url[:60]}...")
            return text

    text = None
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
            "num_predict": 3072,
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


def parse_llm_json(raw):
    """extract JSON from LLM response, handling markdown fences."""
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            log.warning(f"  could not parse LLM JSON output")
            return {"raw_response": raw}
    return {"raw_response": raw}


# ── country context loading ───────────────────────────────────────
def load_country_contexts():
    """load country context injection library."""
    if os.path.exists(CONTEXTS_FILE):
        with open(CONTEXTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    log.warning(f"  {CONTEXTS_FILE} not found — running without country context injection")
    return {}


def get_country_context(contexts, country):
    """get context injection string for a country."""
    entry = contexts.get(country, {})
    if not entry:
        return ""
    ctx = entry.get("context", "")
    factors = entry.get("key_framing_factors", [])
    if ctx:
        parts = [f"COUNTRY CONTEXT for interpreting this source ({country}): {ctx}"]
        if factors:
            parts.append(f"Key framing factors: {', '.join(factors)}.")
        return "\n".join(parts)
    return ""


# ── language preservation: extract framing from original text ─────
FRAMING_EXTRACT_PROMPT = """You are analyzing a news article written in {language} about US-Iran/Israel military tensions.

Extract ONLY the key framing language — the specific words and phrases that reveal how this source frames the event. Return them in the ORIGINAL language, not translated. Also provide approximate English translations.

Output JSON:
{{
  "original_framing_terms": ["5-8 specific words or phrases from the article in their original {language}"],
  "english_approximations": ["approximate English translation of each term above, in same order"],
  "contested_translations": ["any terms where the English translation significantly loses meaning — explain what's lost"],
  "emotional_register": "one of: neutral_analytical, alarmed, triumphant, mournful, ironic, propagandistic, diplomatic"
}}

IMPORTANT: Output ONLY valid JSON, no other text.

Article excerpt:
{text}"""


def extract_original_framing(model, text, language):
    """extract key framing language from original (non-English) text before translation."""
    prompt = FRAMING_EXTRACT_PROMPT.format(language=language, text=text[:2000])
    raw = ollama_generate(model, prompt)
    return parse_llm_json(raw)


# ── translation ───────────────────────────────────────────────────
def translate_text(model, text):
    """translate non-English text to English."""
    prompt = f"Translate to English. Output translation only.\n\n{text[:3000]}"
    return ollama_generate(model, prompt)


# ══════════════════════════════════════════════════════════════════
#  PASS 1: open-ended framing description
#  no predefined categories — use the article's own conceptual vocabulary
# ══════════════════════════════════════════════════════════════════

PASS1_PROMPT = """You are analyzing a news article about US-Israel military action against Iran.

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
{{
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
}}

IMPORTANT: Output ONLY valid JSON, no other text.

Article:
{article_text}"""


def pass1_extract(model, text, country_context=""):
    """pass 1: open-ended framing description, no predefined categories."""
    truncated = text[:3000]
    prompt = PASS1_PROMPT.format(
        article_text=truncated,
        country_context=country_context
    )
    raw = ollama_generate(model, prompt)
    return parse_llm_json(raw)


# ══════════════════════════════════════════════════════════════════
#  PASS 2: cluster emergent descriptions across the whole corpus
#  runs ONCE after all articles are processed
# ══════════════════════════════════════════════════════════════════

PASS2_CLUSTER_PROMPT = """You have analyzed {n} news articles from {n_countries} countries about US-Israel military action against Iran.

Below are the framing descriptions from each article. Your task: identify the EMERGENT clusters — the natural groupings that arise from the data itself.

RULES:
- Do NOT start with predefined categories. Let the clusters emerge from the descriptions.
- Some clusters may resemble expected categories (e.g., endorsement, opposition). That's fine — but name them in the data's own language, not political science textbook terms.
- Some articles may belong to multiple clusters. That's fine.
- If an article genuinely resists clustering, flag it as a singleton — it may be the most interesting finding.
- Name each cluster with a descriptive phrase, not a single word.
- For each cluster, note whether its members are geographically concentrated or dispersed.

ARTICLE DESCRIPTIONS:
{descriptions}

Output JSON:
{{
  "emergent_clusters": [
    {{
      "cluster_name": "descriptive name for this framing pattern",
      "description": "what unites these articles — the shared assumptions, vocabulary, or framing logic",
      "member_indices": [0, 3, 7],
      "geographic_pattern": "concentrated in X region / dispersed globally / etc.",
      "maps_to_conventional_category": "if this resembles a standard political category, name it. otherwise null"
    }}
  ],
  "singletons": [
    {{
      "index": 5,
      "why_unique": "what makes this article's framing distinct from all clusters"
    }}
  ],
  "meta_observation": "one paragraph on what the clustering reveals about global framing patterns that would not be visible from any single article or region"
}}

IMPORTANT: Output ONLY valid JSON, no other text."""


def pass2_cluster(model, results):
    """pass 2: cluster all framing descriptions into emergent categories."""
    # build descriptions summary for clustering prompt
    descriptions = []
    for i, r in enumerate(results):
        analysis = r.get("analysis", {})
        desc = analysis.get("framing_description", analysis.get("one_sentence_summary", ""))
        country = r.get("sourcecountry", "unknown")
        domain = r.get("domain", "unknown")
        tensions = analysis.get("internal_tensions", "")
        line = f"[{i}] {domain} ({country}): {desc}"
        if tensions:
            line += f" TENSIONS: {tensions}"
        descriptions.append(line)

    n_countries = len(set(r.get("sourcecountry", "") for r in results))
    prompt = PASS2_CLUSTER_PROMPT.format(
        n=len(results),
        n_countries=n_countries,
        descriptions="\n".join(descriptions)
    )
    raw = ollama_generate(model, prompt, timeout=300)  # longer timeout for corpus-level reasoning
    return parse_llm_json(raw)


# ══════════════════════════════════════════════════════════════════
#  CORPUS-LEVEL ABSENCE REPORT
#  what positions are structurally missing from the dataset?
# ══════════════════════════════════════════════════════════════════

ABSENCE_PROMPT = """You have analyzed {n} news articles from {n_countries} countries about US-Israel military action against Iran.

The articles came from these countries: {country_list}
The languages represented: {lang_list}

Here is a summary of the framing positions found:
{cluster_summary}

Now identify what is STRUCTURALLY ABSENT from this corpus:

1. Which actors have obvious stakes in this event but are NOT represented? (e.g., Iranian domestic press, Kurdish media, specific religious authorities)
2. What arguments could legitimately be made about this event that NO article in this set makes?
3. Which regions or populations are affected by this event but have no voice in this corpus?
4. What framings would appear if the corpus included Tier 3 sources — oral media, WhatsApp networks, sermons, radio?
5. Are there positions that are logically possible but politically unspeakable in any major outlet?

Output JSON:
{{
  "unrepresented_actors": ["actors with stakes but no voice in this corpus"],
  "unmade_arguments": ["legitimate arguments that no article makes"],
  "voiceless_populations": ["affected populations with no representation"],
  "tier3_predictions": ["framings that would likely appear from non-digital sources"],
  "unspeakable_positions": ["positions that are logically coherent but politically impossible to publish"],
  "overall_assessment": "one paragraph on what this corpus's absences reveal about the structure of global media"
}}

IMPORTANT: Output ONLY valid JSON, no other text."""


def generate_absence_report(model, results, cluster_data):
    """corpus-level analysis of what positions are structurally missing."""
    countries = sorted(set(r.get("sourcecountry", "") for r in results))
    langs = sorted(set(r.get("sourcelang", "") for r in results))

    # summarize clusters for the prompt
    cluster_summary = ""
    if cluster_data and "emergent_clusters" in cluster_data:
        for c in cluster_data["emergent_clusters"]:
            cluster_summary += f"- {c['cluster_name']}: {c['description']}\n"

    prompt = ABSENCE_PROMPT.format(
        n=len(results),
        n_countries=len(countries),
        country_list=", ".join(countries),
        lang_list=", ".join(langs),
        cluster_summary=cluster_summary or "(clustering not available)"
    )
    raw = ollama_generate(model, prompt, timeout=300)
    return parse_llm_json(raw)


# ── main pipeline ─────────────────────────────────────────────────
def run_pipeline(limit=None):
    """run the full two-pass analysis pipeline."""
    with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    if limit:
        articles = articles[:limit]
        log.info(f"processing {limit} articles (limited run)")
    else:
        log.info(f"processing all {len(articles)} articles")

    model = find_best_model()
    log.info(f"using model: {model}")

    # load country contexts for bias compensation
    country_contexts = load_country_contexts()
    if country_contexts:
        log.info(f"loaded context for {len(country_contexts)} countries")

    # load outlet registry for metadata matching
    outlet_domains = {}
    if os.path.exists(OUTLETS_FILE):
        with open(OUTLETS_FILE, "r", encoding="utf-8") as f:
            outlets = json.load(f)
        outlet_domains = {o["domain"]: o for o in outlets}

    # ── PASS 1: per-article analysis ──────────────────────────────
    log.info(f"\n{'─'*60}")
    log.info(f"PASS 1: per-article framing extraction (no predefined categories)")
    log.info(f"{'─'*60}")

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

        original_framing = None
        translation_flag = None
        is_non_english = lang.lower() not in ("english", "eng", "en")

        # step 2: if non-English, extract framing from ORIGINAL text first
        if is_non_english:
            log.info(f"  extracting original {lang} framing terms...")
            original_framing = extract_original_framing(model, text, lang)

            # step 3: translate
            log.info(f"  translating from {lang}...")
            translated = translate_text(model, text)
            if translated and len(translated.strip()) > 50:
                ratio = len(translated.strip()) / len(text.strip())
                if ratio < 0.3:
                    translation_flag = f"translation is {ratio:.0%} the length of original — likely significant content loss"
                elif ratio < 0.5:
                    translation_flag = f"translation is {ratio:.0%} the length of original — some content may be lost"
                text = translated
            else:
                log.warning(f"  translation failed, using original text")
                translation_flag = "translation failed entirely — position extracted from original language text"

        # step 4: pass 1 — open-ended framing analysis with country context
        country_ctx = get_country_context(country_contexts, country)
        log.info(f"  pass 1: extracting framing description...")
        analysis = pass1_extract(model, text, country_context=country_ctx)
        if not analysis:
            log.warning(f"  SKIP: framing extraction failed")
            continue

        # merge original framing data
        if original_framing and not original_framing.get("raw_response"):
            analysis["original_framing_terms"] = original_framing.get("original_framing_terms", [])
            analysis["english_approximations"] = original_framing.get("english_approximations", [])
            analysis["contested_translations"] = original_framing.get("contested_translations", [])
            analysis["original_language"] = original_framing.get("original_language", lang)
            analysis["emotional_register"] = original_framing.get("emotional_register", "unknown")
        else:
            analysis["original_framing_terms"] = []
            analysis["english_approximations"] = []
            analysis["contested_translations"] = []
            analysis["original_language"] = lang if is_non_english else "English"

        if translation_flag:
            analysis["translation_warning"] = translation_flag

        # enrich with metadata
        outlet_info = outlet_domains.get(domain, {})
        result = {
            "url": url,
            "title": title,
            "domain": domain,
            "sourcecountry": country,
            "sourcelang": lang,
            "source_type": article.get("source", "gdelt"),
            "outlet_name": outlet_info.get("name", domain),
            "outlet_tier": outlet_info.get("tier", 0),
            "outlet_region": outlet_info.get("region", "unknown"),
            "outlet_bias_notes": outlet_info.get("bias_notes", ""),
            "analysis": analysis,
        }
        results.append(result)

        # save per-article result
        safe_domain = domain.replace("/", "_").replace(".", "_")
        out_path = os.path.join(ANALYSIS_DIR, f"{safe_domain}_{i}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        desc = analysis.get("framing_description", analysis.get("one_sentence_summary", ""))[:80]
        tensions = "⚡ HAS TENSIONS" if analysis.get("internal_tensions") else ""
        log.info(f"  ✓ {desc} {tensions}")

    # save pass 1 results
    combined_path = os.path.join(ANALYSIS_DIR, "all_results.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log.info(f"\n  pass 1 complete: {len(results)}/{len(articles)} articles processed")

    # ── PASS 2: emergent clustering ───────────────────────────────
    if len(results) >= 3:  # need at least a few articles to cluster
        log.info(f"\n{'─'*60}")
        log.info(f"PASS 2: emergent clustering of {len(results)} framing descriptions")
        log.info(f"{'─'*60}")

        cluster_data = pass2_cluster(model, results)
        if cluster_data and not cluster_data.get("raw_response"):
            cluster_path = os.path.join(ANALYSIS_DIR, "emergent_clusters.json")
            with open(cluster_path, "w", encoding="utf-8") as f:
                json.dump(cluster_data, f, indent=2, ensure_ascii=False)

            # tag each result with its cluster assignments
            if "emergent_clusters" in cluster_data:
                for cluster in cluster_data["emergent_clusters"]:
                    name = cluster["cluster_name"]
                    for idx in cluster.get("member_indices", []):
                        if 0 <= idx < len(results):
                            results[idx]["analysis"].setdefault("emergent_cluster_assignments", [])
                            results[idx]["analysis"]["emergent_cluster_assignments"].append(name)

                # tag singletons
                for singleton in cluster_data.get("singletons", []):
                    idx = singleton.get("index", -1)
                    if 0 <= idx < len(results):
                        results[idx]["analysis"]["singleton"] = True
                        results[idx]["analysis"]["singleton_reason"] = singleton.get("why_unique", "")

            # print cluster summary
            log.info(f"  emergent clusters found:")
            for c in cluster_data.get("emergent_clusters", []):
                conventional = c.get("maps_to_conventional_category")
                mapped = f" (≈ {conventional})" if conventional else " [NOVEL]"
                log.info(f"    • {c['cluster_name']}{mapped}: {len(c.get('member_indices', []))} articles")
                log.info(f"      {c.get('geographic_pattern', '')}")

            singletons = cluster_data.get("singletons", [])
            if singletons:
                log.info(f"  singletons (resist clustering): {len(singletons)}")
                for s in singletons:
                    idx = s.get("index", -1)
                    if 0 <= idx < len(results):
                        log.info(f"    • {results[idx]['domain']}: {s.get('why_unique', '')[:80]}")

            meta = cluster_data.get("meta_observation", "")
            if meta:
                log.info(f"  meta-observation: {meta[:200]}")
        else:
            log.warning("  pass 2 clustering failed — saving pass 1 results only")
            cluster_data = None

        # ── CORPUS-LEVEL ABSENCE REPORT ───────────────────────────
        log.info(f"\n{'─'*60}")
        log.info(f"ABSENCE ANALYSIS: what this corpus doesn't say")
        log.info(f"{'─'*60}")

        absence_data = generate_absence_report(model, results, cluster_data)
        if absence_data and not absence_data.get("raw_response"):
            absence_path = os.path.join(ANALYSIS_DIR, "absence_report.json")
            with open(absence_path, "w", encoding="utf-8") as f:
                json.dump(absence_data, f, indent=2, ensure_ascii=False)

            log.info(f"  unrepresented actors: {absence_data.get('unrepresented_actors', [])[:5]}")
            log.info(f"  unmade arguments: {len(absence_data.get('unmade_arguments', []))}")
            log.info(f"  voiceless populations: {absence_data.get('voiceless_populations', [])[:5]}")
            assessment = absence_data.get("overall_assessment", "")
            if assessment:
                log.info(f"  assessment: {assessment[:200]}")
        else:
            log.warning("  absence analysis failed")
            absence_data = None
    else:
        log.info("  too few articles for pass 2 clustering — skipping")
        cluster_data = None
        absence_data = None

    # save final enriched results (with cluster tags)
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # coverage gaps report
    generate_coverage_report(results, articles)

    # final summary
    print_summary(results, articles, cluster_data)

    return results


def print_summary(results, articles, cluster_data=None):
    """print final pipeline summary."""
    log.info(f"\n{'='*60}")
    log.info(f"PIPELINE COMPLETE")
    log.info(f"  articles processed: {len(results)}/{len(articles)}")

    if cluster_data and "emergent_clusters" in cluster_data:
        log.info(f"  emergent clusters: {len(cluster_data['emergent_clusters'])}")
        novel = [c for c in cluster_data["emergent_clusters"]
                 if not c.get("maps_to_conventional_category")]
        if novel:
            log.info(f"  NOVEL clusters (no conventional equivalent): {len(novel)}")
            for c in novel:
                log.info(f"    → {c['cluster_name']}")

    tensions = [r for r in results if r["analysis"].get("internal_tensions")]
    if tensions:
        log.info(f"  articles with internal tensions: {len(tensions)}")

    log.info(f"  results: {os.path.join(ANALYSIS_DIR, 'all_results.json')}")
    log.info(f"{'='*60}")


def generate_coverage_report(results, articles):
    """audit coverage gaps: missing regions, languages, sources."""
    report = {"generated": time.strftime("%Y-%m-%d %H:%M:%S")}

    all_regions = {"Middle East", "Europe", "Asia", "Africa", "Latin America",
                   "North America", "Oceania", "Central Asia"}
    covered_regions = set()
    region_counts = {}
    for r in results:
        region = r.get("outlet_region", "unknown")
        covered_regions.add(region)
        region_counts[region] = region_counts.get(region, 0) + 1

    missing_regions = all_regions - covered_regions
    report["regions"] = {
        "covered": dict(sorted(region_counts.items(), key=lambda x: -x[1])),
        "missing": sorted(missing_regions),
    }

    lang_map = {
        "Chinese": "Mandarin Chinese", "English": "English", "Spanish": "Spanish",
        "French": "French", "Arabic": "Arabic", "Portuguese": "Portuguese",
        "Russian": "Russian", "German": "German", "Korean": "Korean",
        "Japanese": "Japanese", "Turkish": "Turkish", "Hindi": "Hindi",
        "Bengali": "Bengali", "Swahili": "Swahili", "Hausa": "Hausa",
    }
    covered_langs = set()
    for r in results:
        raw_lang = r.get("sourcelang", "")
        mapped = lang_map.get(raw_lang, raw_lang)
        covered_langs.add(mapped)

    all_article_langs = set()
    for a in articles:
        raw_lang = a.get("sourcelang", "")
        mapped = lang_map.get(raw_lang, raw_lang)
        all_article_langs.add(mapped)

    top_missing = [l for l in TOP_LANGUAGES if l not in covered_langs]
    report["languages"] = {
        "covered": sorted(covered_langs),
        "top_languages_missing": top_missing,
        "in_pool_but_not_processed": sorted(all_article_langs - covered_langs),
    }

    # source type breakdown: how many from GDELT vs curated RSS
    source_types = {}
    for r in results:
        st = r.get("source_type", "gdelt")
        source_types[st] = source_types.get(st, 0) + 1
    report["source_types"] = source_types

    country_counts = {}
    for r in results:
        c = r.get("sourcecountry", "unknown")
        country_counts[c] = country_counts.get(c, 0) + 1
    report["countries"] = {
        "total": len(country_counts),
        "distribution": dict(sorted(country_counts.items(), key=lambda x: -x[1])),
    }

    report_path = os.path.join(ANALYSIS_DIR, "coverage_gaps.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log.info(f"\n{'='*60}")
    log.info(f"COVERAGE GAPS REPORT")
    if missing_regions:
        log.info(f"  ⚠ missing regions: {', '.join(sorted(missing_regions))}")
    if top_missing:
        log.info(f"  ⚠ top languages absent: {', '.join(top_missing)}")
    log.info(f"  countries covered: {len(country_counts)}")
    log.info(f"  source breakdown: {source_types}")
    log.info(f"  full report: {report_path}")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            print(f"usage: {sys.argv[0]} [limit]")
            sys.exit(1)
    run_pipeline(limit=limit)
