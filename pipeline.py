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

import argparse
import json
import logging
import os
import sys
import time
import hashlib
import urllib.request
import urllib.error

from db import get_session, Event, Source, Article, Analysis, Cluster, ClusterMembership, CoverageGap
from translate import TranslationEngine
from seed_sources import COUNTRY_CODES

# ── config ────────────────────────────────────────────────────────
LLM_URL = "http://boron:11434"  # llama-server with OpenAI-compatible API
ARTICLES_FILE = "articles.json"
OUTLETS_FILE = "outlets.json"
CONTEXTS_FILE = "country_contexts.json"
ANALYSIS_DIR = "analysis"
CACHE_DIR = "cache"
LOG_FILE = "logs/pipeline.log"
LLM_TIMEOUT = 180  # seconds per LLM call

# all ISO 3166-1 alpha-2 codes for coverage gap detection
ALL_COUNTRY_CODES = set(COUNTRY_CODES.values())
ALL_COUNTRY_CODES.update([
    "AF", "AL", "AM", "AZ", "BH", "BY", "BO", "CL", "CU", "CY", "EC", "GE",
    "GT", "HN", "HU", "IS", "JM", "KW", "KZ", "LY", "MM", "MN", "MZ",
    "NA", "NE", "NI", "OM", "PA", "PE", "QA", "RS", "SD", "SN", "SO",
    "SY", "TJ", "TM", "TT", "UY", "UZ", "VE", "XK", "YE", "ZM", "ZW",
])

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
    """check llama-server on boron is reachable, return model name."""
    try:
        req = urllib.request.Request(f"{LLM_URL}/v1/models")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("data", [])
        if models:
            name = models[0].get("id", "unknown")
            log.info(f"llama-server model: {name}")
            return name
    except Exception as e:
        log.error(f"cannot reach llama-server on boron: {e}")
        sys.exit(1)

    log.error("no model loaded on llama-server")
    sys.exit(1)


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

    # fallback: try Wayback Machine for archived version
    if not text:
        try:
            from archive_fetcher import fetch_via_wayback
            log.info(f"  trying Wayback Machine for {url[:60]}...")
            text = fetch_via_wayback(url)
            if text:
                log.info(f"  wayback recovered: {len(text)} chars")
        except ImportError:
            log.warning("archive_fetcher not available")
        except Exception as e:
            log.warning(f"  wayback failed: {e}")

    if text and text.strip():
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text

    return None


# ── llm calls (OpenAI-compatible API via llama-server) ───────────
def llm_generate(model, prompt, timeout=LLM_TIMEOUT):
    """send a prompt to llama-server on boron. returns response text.
    uses OpenAI-compatible /v1/chat/completions endpoint.
    for qwen3, content has the answer and reasoning_content has the thinking."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 3072,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            # extract content (answer), ignore reasoning_content (thinking)
            choices = result.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content", "")
                if content:
                    return content
                # fallback: some models put everything in reasoning_content
                return msg.get("reasoning_content", "")
            return ""
    except urllib.error.URLError as e:
        log.error(f"  llm connection error: {e}")
        return None
    except Exception as e:
        log.error(f"  llm error: {e}")
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
    raw = llm_generate(model, prompt)
    return parse_llm_json(raw)


# ── translation (Helsinki-NLP, not LLM) ─────────────────────────
# global translation engine, initialized lazily
_translator = None

def get_translator():
    """get or create the translation engine singleton."""
    global _translator
    if _translator is None:
        _translator = TranslationEngine()
    return _translator


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
    raw = llm_generate(model, prompt)
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
    # use one_sentence_summary to keep prompt within context window
    descriptions = []
    for i, r in enumerate(results):
        analysis = r.get("analysis", {})
        desc = analysis.get("one_sentence_summary", analysis.get("framing_description", ""))[:120]
        country = r.get("sourcecountry", "unknown")
        domain = r.get("domain", "unknown")
        descriptions.append(f"[{i}] {domain} ({country}): {desc}")

    n_countries = len(set(r.get("sourcecountry", "") for r in results))
    prompt = PASS2_CLUSTER_PROMPT.format(
        n=len(results),
        n_countries=n_countries,
        descriptions="\n".join(descriptions)
    )
    raw = llm_generate(model, prompt, timeout=300)  # longer timeout for corpus-level reasoning
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
    raw = llm_generate(model, prompt, timeout=300)
    return parse_llm_json(raw)


# ── DB helpers ────────────────────────────────────────────────────
def find_or_create_source(session, domain, article_data, outlet_domains):
    """find source by domain match, or create a minimal source record."""
    url = f"https://{domain}" if domain else article_data.get("url", "")

    # try domain match against existing sources
    source = session.query(Source).filter(
        Source.url.ilike(f"%{domain}%")
    ).first() if domain else None

    if source:
        return source

    country = article_data.get("sourcecountry", "")
    country_code = COUNTRY_CODES.get(country, "")
    lang = article_data.get("sourcelang", "English")
    lang_code = get_translator().lang_name_to_code(lang) or "en"

    outlet_info = outlet_domains.get(domain, {})
    source = Source(
        name=outlet_info.get("name", domain),
        url=f"https://{domain}",
        country_code=country_code,
        language_code=lang_code,
        source_type="gdelt_discovered",
        editorial_language=lang,
        tier="C",
        is_state_adjacent=False,
    )
    session.add(source)
    session.flush()
    log.warning(f"  new source not in seed list: {domain}")
    return source


def write_article_to_db(session, event_id, source, url, title, lang, raw_text,
                        translated_text, original_terms, absence_flags):
    """write article record to DB. returns Article or None if duplicate."""
    existing = session.query(Article).filter_by(url=url).first()
    if existing:
        log.info(f"  duplicate: {url[:60]}")
        return existing

    is_english = lang.lower() in ("english", "eng", "en")
    article = Article(
        event_id=event_id,
        source_id=source.id,
        url=url,
        title=title,
        original_language=lang if not is_english else "English",
        translation_language="English" if not is_english and translated_text else None,
        raw_text=raw_text,
        translated_text=translated_text if translated_text else (raw_text if is_english else None),
        original_language_terms=original_terms,
        absence_flags=absence_flags,
    )
    session.add(article)
    session.flush()
    return article


def write_analysis_to_db(session, article_id, event_id, model_name, analysis_data):
    """write analysis record to DB."""
    positions = analysis_data.get("key_framing_language", [])
    tension_text = analysis_data.get("internal_tensions")
    internal_tensions = []
    if tension_text:
        internal_tensions = [{"description": tension_text}] if isinstance(tension_text, str) else tension_text

    unspeakable = []
    for v in analysis_data.get("whose_voice_is_absent", []):
        unspeakable.append(f"voice absent: {v}")

    record = Analysis(
        article_id=article_id,
        event_id=event_id,
        model_used=model_name,
        primary_frame=analysis_data.get("framing_description", analysis_data.get("one_sentence_summary", "")),
        positions=positions,
        internal_tensions=internal_tensions,
        absence_flags=analysis_data.get("absence_flags", []),
        unspeakable_positions=unspeakable,
        raw_llm_output=analysis_data,
    )
    session.add(record)
    return record


def write_clusters_to_db(session, event_id, cluster_data, results, url_to_article_id):
    """write clusters and memberships to DB after pass 2."""
    if not cluster_data or "emergent_clusters" not in cluster_data:
        return 0, 0

    clusters_written = 0
    memberships_written = 0

    for c in cluster_data["emergent_clusters"]:
        indices = c.get("member_indices", [])
        geo_sig = {}
        for idx in indices:
            if 0 <= idx < len(results):
                country = results[idx].get("sourcecountry", "unknown")
                geo_sig[country] = geo_sig.get(country, 0) + 1

        cluster = Cluster(
            event_id=event_id,
            label=c.get("cluster_name", ""),
            article_count=len(indices),
            geographic_signature=geo_sig,
        )
        session.add(cluster)
        session.flush()
        clusters_written += 1

        for idx in indices:
            if 0 <= idx < len(results):
                url = results[idx].get("url", "")
                article_id = url_to_article_id.get(url)
                if article_id:
                    session.add(ClusterMembership(
                        article_id=article_id,
                        cluster_id=cluster.id,
                    ))
                    memberships_written += 1

    # singletons as individual clusters
    for s in cluster_data.get("singletons", []):
        idx = s.get("index", -1)
        if 0 <= idx < len(results):
            url = results[idx].get("url", "")
            article_id = url_to_article_id.get(url)
            title_frag = results[idx].get("title", "")[:60]
            cluster = Cluster(
                event_id=event_id,
                label=f"Singleton: {title_frag}",
                article_count=1,
                geographic_signature={results[idx].get("sourcecountry", "unknown"): 1},
            )
            session.add(cluster)
            session.flush()
            clusters_written += 1
            if article_id:
                session.add(ClusterMembership(
                    article_id=article_id, cluster_id=cluster.id, distance_from_centroid=0.0,
                ))
                memberships_written += 1

    return clusters_written, memberships_written


def write_coverage_gaps_to_db(session, event_id, covered_country_codes):
    """seed coverage_gaps for countries with zero articles."""
    gaps = 0
    for code in sorted(ALL_COUNTRY_CODES - covered_country_codes):
        session.add(CoverageGap(
            event_id=event_id,
            country_code=code,
            source_type="all",
            gap_description="no sources in current corpus",
            attempted=False,
            retrieved=False,
        ))
        gaps += 1
    return gaps


# ── main pipeline ─────────────────────────────────────────────────
def run_pipeline(limit=None, event_id=None):
    """run the full two-pass analysis pipeline.

    args:
        limit: max number of articles to process
        event_id: existing event ID to add articles to. if None, creates new event.
    """
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

    # initialize translation engine
    translator = get_translator()
    log.info(f"translation engine ready (device={translator._device})")

    # open DB session
    db_session = get_session()

    # create or find event
    if event_id:
        event = db_session.query(Event).get(event_id)
        if not event:
            log.error(f"event_id {event_id} not found in DB")
            db_session.close()
            sys.exit(1)
        log.info(f"adding articles to existing event: {event.title} (id={event.id})")
    else:
        event = Event(
            title="US-Israeli Military Strikes on Iran",
            event_type="military",
            primary_actors=["United States", "Israel", "Iran"],
            geographic_scope="regional",
        )
        db_session.add(event)
        db_session.flush()
        log.info(f"created new event: id={event.id}")

    # ── PASS 1: per-article analysis ──────────────────────────────
    log.info(f"\n{'─'*60}")
    log.info(f"PASS 1: per-article framing extraction (no predefined categories)")
    log.info(f"{'─'*60}")

    # resume support: load previously processed results (JSON side)
    results = []
    existing_results = {}
    combined_path_check = os.path.join(ANALYSIS_DIR, "all_results.json")
    if os.path.exists(combined_path_check):
        try:
            with open(combined_path_check, "r", encoding="utf-8") as f:
                prev_results = json.load(f)
            existing_results = {r["url"]: r for r in prev_results}
            if existing_results:
                log.info(f"  resume: found {len(existing_results)} previously processed articles")
        except (json.JSONDecodeError, KeyError):
            pass

    # also check DB for already-ingested URLs
    db_urls = set()
    existing_articles = db_session.query(Article.url).filter_by(event_id=event.id).all()
    db_urls = {a.url for a in existing_articles}
    if db_urls:
        log.info(f"  resume: {len(db_urls)} articles already in DB")

    # track url -> article_id for cluster membership
    url_to_article_id = {}
    for a in db_session.query(Article).filter_by(event_id=event.id).all():
        url_to_article_id[a.url] = a.id

    # track consecutive llm failures to detect boron going offline
    consecutive_llm_failures = 0
    MAX_CONSECUTIVE_FAILURES = 5
    covered_country_codes = set()

    for i, article in enumerate(articles):
        url = article.get("url", "")
        domain = article.get("domain", "unknown")
        title = article.get("title", "untitled")
        lang = article.get("sourcelang", "English")
        country = article.get("sourcecountry", "unknown")

        # track country coverage
        code = COUNTRY_CODES.get(country, "")
        if code:
            covered_country_codes.add(code)

        # resume: skip if already processed (JSON side)
        if url in existing_results:
            results.append(existing_results[url])
            log.info(f"[{i+1}/{len(articles)}] {domain} — RESUME (already processed)")
            continue

        # resume: skip if already in DB
        if url in db_urls:
            log.info(f"[{i+1}/{len(articles)}] {domain} — RESUME (already in DB)")
            continue

        # bail out if boron appears to be offline
        if consecutive_llm_failures >= MAX_CONSECUTIVE_FAILURES:
            log.error(f"  {MAX_CONSECUTIVE_FAILURES} consecutive llm failures — llama-server on boron not responding, stopping pass 1")
            log.error(f"  re-run pipeline to resume from where it left off")
            break

        log.info(f"[{i+1}/{len(articles)}] {domain} — {title[:60]}...")

        # step 1: fetch article text
        raw_text = fetch_article_text(url)
        if not raw_text:
            log.warning(f"  SKIP: could not fetch article text")
            continue

        original_framing = None
        translation_flag = None
        translated_text = None
        original_terms_data = []
        is_non_english = lang.lower() not in ("english", "eng", "en")
        text = raw_text  # working copy for analysis

        # step 2: if non-English, extract original terms + translate with Helsinki-NLP
        if is_non_english:
            # extract original-language terms (regex-based, no LLM needed)
            lang_code = translator.lang_name_to_code(lang) or translator.detect_language(raw_text)
            terms = translator.extract_original_terms(raw_text[:2000], lang_code)
            original_terms_data = terms.get("terms", [])

            # also extract framing via LLM (preserves richer analysis)
            log.info(f"  extracting original {lang} framing terms...")
            original_framing = extract_original_framing(model, raw_text, lang)

            # step 3: translate with Helsinki-NLP (NOT Qwen)
            log.info(f"  translating from {lang} via Helsinki-NLP...")
            helsinki_translated, detected_code = translator.translate(raw_text[:3000], source_lang=lang)

            if helsinki_translated:
                translated_text = helsinki_translated
                ratio = len(translated_text.strip()) / len(raw_text.strip())
                if ratio < 0.3:
                    translation_flag = f"translation is {ratio:.0%} the length of original — likely significant content loss"
                elif ratio < 0.5:
                    translation_flag = f"translation is {ratio:.0%} the length of original — some content may be lost"
                text = translated_text
                log.info(f"  translated: {len(translated_text)} chars ({ratio:.0%} ratio)")
            else:
                log.warning(f"  no Helsinki model for {lang} ({detected_code}) — using original text")
                translation_flag = f"no Helsinki-NLP model for {detected_code} — analysis on original text"

        # step 4: pass 1 — open-ended framing analysis with country context
        country_ctx = get_country_context(country_contexts, country)
        log.info(f"  pass 1: extracting framing description...")
        analysis = pass1_extract(model, text, country_context=country_ctx)
        if not analysis:
            log.warning(f"  SKIP: framing extraction failed")
            consecutive_llm_failures += 1
            continue

        # reset failure counter on success
        consecutive_llm_failures = 0

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

        # ── write to DB ──────────────────────────────────────────
        source = find_or_create_source(db_session, domain, article, outlet_domains)
        absence_flags = analysis.get("absence_flags", [])

        # build structured original_language_terms for DB
        orig_terms = analysis.get("original_framing_terms", [])
        eng_approx = analysis.get("english_approximations", [])
        terms_structured = []
        for j, term in enumerate(orig_terms):
            entry = {"term": term}
            if j < len(eng_approx):
                entry["english"] = eng_approx[j]
            terms_structured.append(entry)
        # also add regex-extracted terms
        for t in original_terms_data:
            if t not in [x.get("term") for x in terms_structured]:
                terms_structured.append({"term": t})

        db_article = write_article_to_db(
            db_session, event.id, source, url, title, lang,
            raw_text, translated_text, terms_structured, absence_flags,
        )
        url_to_article_id[url] = db_article.id

        write_analysis_to_db(db_session, db_article.id, event.id, model, analysis)
        db_session.commit()  # commit per article for resume safety

        # ── also write JSON (parallel output) ────────────────────
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
        tensions = "HAS TENSIONS" if analysis.get("internal_tensions") else ""
        log.info(f"  done: {desc} {tensions}")

    # save pass 1 results (JSON side)
    combined_path = os.path.join(ANALYSIS_DIR, "all_results.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log.info(f"\n  pass 1 complete: {len(results)}/{len(articles)} articles processed")

    # ── PASS 2: emergent clustering ───────────────────────────────
    cluster_data = None
    absence_data = None

    if len(results) >= 3:
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

                for singleton in cluster_data.get("singletons", []):
                    idx = singleton.get("index", -1)
                    if 0 <= idx < len(results):
                        results[idx]["analysis"]["singleton"] = True
                        results[idx]["analysis"]["singleton_reason"] = singleton.get("why_unique", "")

            # print cluster summary
            log.info(f"  emergent clusters found:")
            for c in cluster_data.get("emergent_clusters", []):
                conventional = c.get("maps_to_conventional_category")
                mapped = f" (= {conventional})" if conventional else " [NOVEL]"
                log.info(f"    {c['cluster_name']}{mapped}: {len(c.get('member_indices', []))} articles")

            # write clusters to DB
            c_count, m_count = write_clusters_to_db(
                db_session, event.id, cluster_data, results, url_to_article_id)
            db_session.commit()
            log.info(f"  DB: {c_count} clusters, {m_count} memberships written")
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
        else:
            log.warning("  absence analysis failed")
            absence_data = None

    # write coverage gaps to DB
    gaps = write_coverage_gaps_to_db(db_session, event.id, covered_country_codes)
    db_session.commit()
    log.info(f"  coverage gaps seeded: {gaps}")

    # save final enriched results (with cluster tags)
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # coverage gaps report (JSON side)
    generate_coverage_report(results, articles)

    # final summary
    print_summary(results, articles, cluster_data)

    # close DB
    db_session.close()
    log.info(f"  event_id: {event.id}")

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
    parser = argparse.ArgumentParser(description="NewsKaleidoscope analysis pipeline")
    parser.add_argument("limit", nargs="?", type=int, default=None,
                        help="max articles to process")
    parser.add_argument("--event-id", type=int, default=None,
                        help="existing event ID to add articles to")
    args = parser.parse_args()
    run_pipeline(limit=args.limit, event_id=args.event_id)
