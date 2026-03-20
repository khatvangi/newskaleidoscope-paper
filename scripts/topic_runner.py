#!/usr/bin/env python3
"""
topic_runner.py — run the full NewsKaleidoscope pipeline from a topic YAML config.

orchestrates: ingest → extract text → translate → pass 1 → council → cluster → report

usage:
  python3 scripts/topic_runner.py topics/epstein-files.yaml
  python3 scripts/topic_runner.py topics/epstein-files.yaml --phase ingest
  python3 scripts/topic_runner.py topics/epstein-files.yaml --phase analyze
  python3 scripts/topic_runner.py topics/epstein-files.yaml --status

phases:
  ingest    — GDELT + World News API + Reddit ingestion
  extract   — text extraction (trafilatura → newspaper3k → Wayback)
  translate — MarianMT + NLLB translation
  analyze   — Pass 1 framing extraction (requires boron GPU)
  council   — sample council validation (requires boron GPU)
  cluster   — emergent clustering (requires boron GPU)
  report    — HTML report generation
  all       — run everything in sequence (default)
"""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict
from datetime import datetime

import psycopg2
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
REQUEST_DELAY = 8  # gdelt rate limit
LLM_URL = "http://boron:11434"
LLAMA_SERVER_BIN = "/storage/kiran-stuff/llama.cpp/build/bin/llama-server"
MODEL_DIR = "/storage/kiran-stuff/llama.cpp/models"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("topic_runner")


def load_config(config_path):
    """load and validate topic YAML config."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    required = ["name", "slug", "windows", "queries"]
    for key in required:
        if key not in config:
            raise ValueError(f"missing required key: {key}")
    return config


def get_conn():
    return psycopg2.connect(DB_URL)


def resolve_source(cur, domain, source_type="news"):
    """get or create source by domain name."""
    if not domain:
        return None
    cur.execute("SELECT id FROM sources WHERE name = %s", (domain,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO sources (name, source_type) VALUES (%s, %s) RETURNING id",
        (domain, source_type)
    )
    return cur.fetchone()[0]


# ── phase: create event ─────────────────────────────────────────
def ensure_event(config):
    """create or find the DB event for this topic."""
    conn = get_conn()
    cur = conn.cursor()

    # check if event already exists
    cur.execute("SELECT id FROM events WHERE title = %s", (config["name"],))
    row = cur.fetchone()
    if row:
        event_id = row[0]
        log.info(f"using existing event_id={event_id}: {config['name']}")
    else:
        # find date range across all windows
        all_starts = [w["start"] for w in config["windows"].values()]
        all_ends = [w["end"] for w in config["windows"].values()]
        event_date = min(all_starts)

        cur.execute("""
            INSERT INTO events (title, description, event_type, event_date,
                                prompt_context, absence_examples, corpus_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            config["name"],
            config.get("description", ""),
            config.get("event_type", "other"),
            event_date,
            config["name"],  # prompt_context
            config.get("absence_examples", ""),
            "v1",
        ))
        event_id = cur.fetchone()[0]
        conn.commit()
        log.info(f"created event_id={event_id}: {config['name']}")

    cur.close()
    conn.close()
    return event_id


# ── phase: GDELT ingestion ─────────────────────────────────────
def fetch_gdelt(query, start_date, end_date):
    """fetch articles from GDELT DOC API. falls back to boron if nitrogen is blocked."""
    start_dt = start_date.replace("-", "") + "000000"
    end_dt = end_date.replace("-", "") + "235959"

    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": "250",
        "format": "json",
        "startdatetime": start_dt,
        "enddatetime": end_dt,
    }
    url = f"{GDELT_API}?{urllib.parse.urlencode(params)}"

    # try direct first
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            if raw.strip().startswith("{"):
                data = json.loads(raw)
                return data.get("articles", [])
            else:
                wait = 15 * (attempt + 1)
                log.warning(f"    rate limited, waiting {wait}s...")
                time.sleep(wait)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log.info(f"    429 on nitrogen, trying boron fallback...")
                break
            log.warning(f"    gdelt error: {e}")
            time.sleep(5)
        except Exception as e:
            log.warning(f"    gdelt error: {e}")
            time.sleep(5)

    # fallback: fetch via boron SSH
    try:
        result = subprocess.run(
            ["ssh", "boron", f"curl -s '{url}'"],
            capture_output=True, text=True, timeout=45
        )
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            data = json.loads(result.stdout)
            articles = data.get("articles", [])
            if articles:
                log.info(f"    boron fallback: {len(articles)} articles")
            return articles
    except Exception as e:
        log.warning(f"    boron fallback failed: {e}")

    return []


def phase_ingest(config, event_id):
    """phase 1: ingest from all sources."""
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: INGEST — {config['name']}")
    log.info(f"{'='*60}")

    conn = get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    seen_urls = set()

    # get already-ingested URLs
    cur.execute("SELECT url FROM articles WHERE event_id = %s", (event_id,))
    for row in cur.fetchall():
        seen_urls.add(row[0])
    log.info(f"  {len(seen_urls)} articles already in DB")

    # 1. GDELT queries across all windows
    gdelt_queries = config["queries"].get("gdelt", [])
    if gdelt_queries:
        log.info(f"\n  [GDELT] {len(gdelt_queries)} queries × {len(config['windows'])} windows")

        for window_key, window in config["windows"].items():
            log.info(f"\n  window: {window['label']} ({window['start']} → {window['end']})")
            for query in gdelt_queries:
                log.info(f"    query: {query[:50]}...")
                articles = fetch_gdelt(query, window["start"], window["end"])
                new = 0
                for art in articles:
                    url = art.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    domain = art.get("domain", "")
                    source_id = resolve_source(cur, domain)
                    pub_date = None
                    seendate = art.get("seendate", "")
                    if seendate:
                        try:
                            pub_date = datetime.strptime(seendate[:8], "%Y%m%d").date()
                        except ValueError:
                            pass

                    try:
                        cur.execute("""
                            INSERT INTO articles (event_id, source_id, url, title,
                                                  original_language, publication_date, ingested_at)
                            VALUES (%s, %s, %s, %s, %s, %s, NOW())
                        """, (
                            event_id, source_id, url, art.get("title", ""),
                            art.get("language", "unknown"), pub_date,
                        ))
                    except psycopg2.errors.UniqueViolation:
                        conn.rollback()
                        continue
                    new += 1
                    total_inserted += 1

                log.info(f"      {len(articles)} fetched, {new} new")
                conn.commit()
                time.sleep(REQUEST_DELAY)

    # 2. World News API (if keys available)
    worldnews_key = os.environ.get("WORLDNEWS_API_KEY", "") or os.environ.get("APILEAGUE_API_KEY", "")
    wn_queries = config["queries"].get("worldnews", {})
    if worldnews_key and wn_queries:
        log.info(f"\n  [WORLD NEWS API] {len(wn_queries)} language groups")

        # determine which API endpoint to use
        if os.environ.get("WORLDNEWS_API_KEY"):
            api_base = "https://api.worldnewsapi.com/search-news"
            api_key = os.environ["WORLDNEWS_API_KEY"]
        else:
            api_base = "https://api.apileague.com/search-news"
            api_key = os.environ["APILEAGUE_API_KEY"]

        for lang, queries in wn_queries.items():
            if isinstance(queries, str):
                queries = [queries]
            for query in queries:
                for window_key, window in config["windows"].items():
                    params = {
                        "text": query,
                        "number": "50",
                        "earliest-publish-date": f"{window['start']} 00:00:00",
                        "latest-publish-date": f"{window['end']} 23:59:59",
                        "api-key": api_key,
                    }
                    if lang != "default":
                        params["language"] = lang

                    url = f"{api_base}?{urllib.parse.urlencode(params)}"
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                        articles = data.get("news", [])

                        new = 0
                        for art in articles:
                            art_url = art.get("url", "")
                            if not art_url or art_url in seen_urls:
                                continue
                            seen_urls.add(art_url)

                            domain = urllib.parse.urlparse(art_url).netloc.replace("www.", "")
                            source_id = resolve_source(cur, domain)
                            text = art.get("text", "")

                            # cache text
                            if text:
                                url_hash = hashlib.md5(art_url.encode()).hexdigest()
                                cache_path = os.path.join("cache", f"{url_hash}.txt")
                                if not os.path.exists(cache_path):
                                    os.makedirs("cache", exist_ok=True)
                                    with open(cache_path, "w", encoding="utf-8") as f:
                                        f.write(text)

                            pub_date = None
                            pd = art.get("publish_date", "")
                            if pd:
                                try:
                                    pub_date = datetime.strptime(pd[:10], "%Y-%m-%d").date()
                                except ValueError:
                                    pass

                            cur.execute("""
                                INSERT INTO articles (event_id, source_id, url, title,
                                                      original_language, raw_text, publication_date, ingested_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                            """, (
                                event_id, source_id, art_url, art.get("title", ""),
                                art.get("language", lang if lang != "default" else "unknown"),
                                text if text else None, pub_date,
                            ))
                            new += 1
                            total_inserted += 1

                        if new > 0:
                            log.info(f"    {lang}/{window_key}: {new} new")
                        conn.commit()
                    except Exception as e:
                        log.warning(f"    worldnews error ({lang}): {e}")
                    time.sleep(1.5)

    # 3. Reddit
    reddit_config = config["queries"].get("reddit", {})
    reddit_subs = reddit_config.get("subreddits", [])
    reddit_queries = reddit_config.get("queries", [])

    if reddit_subs and reddit_queries:
        log.info(f"\n  [REDDIT] {len(reddit_subs)} subreddits × {len(reddit_queries)} queries")

        for sub_cfg in reddit_subs:
            sub = sub_cfg["sub"]
            for query in reddit_queries:
                try:
                    encoded_q = urllib.parse.quote(query)
                    url = f"https://www.reddit.com/r/{sub}/search.json?q={encoded_q}&restrict_sr=1&sort=relevance&limit=25&t=all"
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "NewsKaleidoscope/0.1 (epistemic mapping research)",
                        "Accept": "application/json",
                    })
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode("utf-8"))

                    new = 0
                    for child in data.get("data", {}).get("children", []):
                        if child.get("kind") != "t3":
                            continue
                        pdata = child.get("data", {})
                        score = pdata.get("score", 0)
                        if score < 2:
                            continue

                        post_url = f"https://www.reddit.com{pdata.get('permalink', '')}"
                        if post_url in seen_urls:
                            continue
                        seen_urls.add(post_url)

                        # date filter using windows
                        created = pdata.get("created_utc", 0)
                        all_starts = [w["start"] for w in config["windows"].values()]
                        all_ends = [w["end"] for w in config["windows"].values()]
                        min_ts = datetime.strptime(min(all_starts), "%Y-%m-%d").timestamp()
                        max_ts = datetime.strptime(max(all_ends), "%Y-%m-%d").timestamp() + 86400
                        if created < min_ts or created > max_ts:
                            continue

                        # build text from title + selftext
                        text_parts = [pdata.get("title", "")]
                        if pdata.get("selftext"):
                            text_parts.append(pdata["selftext"][:3000])
                        full_text = "\n\n".join(text_parts)

                        # cache
                        url_hash = hashlib.md5(post_url.encode()).hexdigest()
                        cache_path = os.path.join("cache", f"{url_hash}.txt")
                        os.makedirs("cache", exist_ok=True)
                        with open(cache_path, "w", encoding="utf-8") as f:
                            f.write(full_text)

                        domain = f"reddit.com/r/{sub}"
                        source_id = resolve_source(cur, domain, "reddit")
                        pub_date = datetime.utcfromtimestamp(created).date()

                        cur.execute("""
                            INSERT INTO articles (event_id, source_id, url, title,
                                                  original_language, raw_text, publication_date, ingested_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (
                            event_id, source_id, post_url, pdata.get("title", ""),
                            sub_cfg.get("language", "English"), full_text, pub_date,
                        ))
                        new += 1
                        total_inserted += 1

                    if new > 0:
                        log.info(f"    r/{sub} '{query}': {new} new")
                    conn.commit()
                except Exception as e:
                    log.warning(f"    reddit error r/{sub}: {e}")
                time.sleep(2.5)

    cur.close()
    conn.close()

    log.info(f"\n  INGEST COMPLETE: {total_inserted} new articles")
    return total_inserted


# ── phase: text extraction ──────────────────────────────────────
def phase_extract(config, event_id):
    """phase 2: extract text for articles missing raw_text."""
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: TEXT EXTRACTION")
    log.info(f"{'='*60}")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, url FROM articles
        WHERE event_id = %s AND (raw_text IS NULL OR raw_text = '')
        ORDER BY id
    """, (event_id,))
    rows = cur.fetchall()
    log.info(f"  {len(rows)} articles need text extraction")

    if not rows:
        cur.close()
        conn.close()
        return 0

    success = 0
    for i, (article_id, url) in enumerate(rows):
        # check cache first
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join("cache", f"{url_hash}.txt")

        text = None
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                text = f.read()

        if not text or len(text.strip()) < 100:
            # tier 1: trafilatura
            try:
                import trafilatura
                downloaded = trafilatura.fetch_url(url)
                if downloaded:
                    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            except Exception:
                pass

            # tier 2: newspaper3k
            if not text:
                try:
                    from newspaper import Article
                    article = Article(url)
                    article.download()
                    article.parse()
                    text = article.text
                except Exception:
                    pass

            # tier 3: wayback machine
            if not text:
                try:
                    from archive_fetcher import fetch_via_wayback
                    text = fetch_via_wayback(url)
                except Exception:
                    pass

            # cache
            if text and text.strip():
                os.makedirs("cache", exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(text)

        if text and len(text.strip()) > 100:
            cur.execute("UPDATE articles SET raw_text = %s WHERE id = %s", (text, article_id))
            success += 1

        if (i + 1) % 50 == 0:
            conn.commit()
            log.info(f"    {i+1}/{len(rows)} — {success} success")

        time.sleep(0.3)

    conn.commit()
    cur.close()
    conn.close()
    log.info(f"  EXTRACTION COMPLETE: {success}/{len(rows)} success")
    return success


# ── phase: translation ──────────────────────────────────────────
def phase_translate(config, event_id):
    """phase 3: translate non-English articles."""
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: TRANSLATION")
    log.info(f"{'='*60}")

    conn = get_conn()
    cur = conn.cursor()

    # first: copy raw_text → translated_text for English articles
    cur.execute("""
        UPDATE articles
        SET translated_text = raw_text, translation_language = 'English'
        WHERE event_id = %s AND original_language = 'English'
          AND raw_text IS NOT NULL AND raw_text != ''
          AND (translated_text IS NULL OR translated_text = '')
    """, (event_id,))
    english_copied = cur.rowcount
    conn.commit()
    log.info(f"  {english_copied} English articles copied")

    # find untranslated non-English
    cur.execute("""
        SELECT id, original_language, title, raw_text
        FROM articles
        WHERE event_id = %s
          AND (translated_text IS NULL OR translated_text = '')
          AND raw_text IS NOT NULL AND raw_text != ''
          AND original_language != 'English'
        ORDER BY id
    """, (event_id,))
    rows = cur.fetchall()
    log.info(f"  {len(rows)} non-English articles need translation")

    if not rows:
        cur.close()
        conn.close()
        return english_copied

    # load translation engine
    from translate import TranslationEngine
    engine = TranslationEngine()

    translated = 0
    for i, (article_id, lang, title, raw_text) in enumerate(rows):
        result, lang_code = engine.translate(raw_text[:3000], source_lang=lang)
        if result:
            cur.execute("""
                UPDATE articles SET translated_text = %s, translation_language = 'English'
                WHERE id = %s
            """, (result, article_id))
            translated += 1
        else:
            log.warning(f"    failed: [{article_id}] {lang}")

        if (i + 1) % 50 == 0:
            conn.commit()
            log.info(f"    {i+1}/{len(rows)} — {translated} translated")

    conn.commit()
    cur.close()
    conn.close()
    log.info(f"  TRANSLATION COMPLETE: {translated}/{len(rows)} + {english_copied} English")
    return translated + english_copied


# ── phase: pass 1 (LLM framing extraction) ──────────────────────
def phase_analyze(config, event_id):
    """phase 4: run Pass 1 framing extraction on boron."""
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: PASS 1 ANALYSIS (requires boron GPU)")
    log.info(f"{'='*60}")

    model = config.get("llm_model", "qwen3-32b-q4km.gguf")
    log.info(f"  model: {model}")
    log.info(f"  launching pass1_runner.py...")

    result = subprocess.run(
        ["python3", "scripts/pass1_runner.py",
         "--event-id", str(event_id),
         "--llm-url", LLM_URL],
        capture_output=False,
    )
    return result.returncode == 0


# ── phase: council ──────────────────────────────────────────────
def phase_council(config, event_id):
    """phase 5: run sample council validation."""
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: SAMPLE COUNCIL (requires boron GPU)")
    log.info(f"{'='*60}")

    sample_size = config.get("council_sample_size", 300)
    log.info(f"  sample size: {sample_size}")
    log.info(f"  launching sample_council.py...")

    result = subprocess.run(
        ["python3", "scripts/sample_council.py",
         "--event-id", str(event_id),
         "--sample-size", str(sample_size)],
        capture_output=False,
    )
    return result.returncode == 0


# ── phase: clustering ───────────────────────────────────────────
def phase_cluster(config, event_id):
    """phase 6: run emergent clustering."""
    log.info(f"\n{'='*60}")
    log.info(f"PHASE: EMERGENT CLUSTERING (requires boron GPU)")
    log.info(f"{'='*60}")

    log.info(f"  launching recluster_chunked.py...")

    result = subprocess.run(
        ["python3", "scripts/recluster_chunked.py",
         "--event-id", str(event_id)],
        capture_output=False,
    )
    return result.returncode == 0


# ── status ──────────────────────────────────────────────────────
def show_status(config, event_id):
    """show current pipeline status for this topic."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
          COUNT(*) as total,
          COUNT(CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 END) as with_text,
          COUNT(CASE WHEN translated_text IS NOT NULL THEN 1 END) as translated,
          COUNT(DISTINCT source_id) as sources,
          COUNT(DISTINCT original_language) as langs
        FROM articles WHERE event_id = %s
    """, (event_id,))
    row = cur.fetchone()

    cur.execute("SELECT COUNT(*) FROM analyses WHERE event_id = %s", (event_id,))
    analyses = (cur.fetchone() or (0,))[0]

    cur.execute("""
        SELECT COUNT(*) FROM llm_council_verdicts v
        JOIN articles a ON v.article_id = a.id
        WHERE a.event_id = %s
    """, (event_id,))
    verdicts = (cur.fetchone() or (0,))[0]

    cur.execute("""
        SELECT COUNT(*) FROM clusters
        WHERE event_id = %s AND method LIKE '%%llm_pass2%%'
    """, (event_id,))
    clusters = (cur.fetchone() or (0,))[0]

    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print(f"  TOPIC: {config['name']}")
    print(f"  event_id: {event_id}")
    print(f"{'='*60}")
    print(f"  articles:    {row[0]}")
    print(f"  with text:   {row[1]} ({row[1]/max(row[0],1)*100:.0f}%)")
    print(f"  translated:  {row[2]} ({row[2]/max(row[0],1)*100:.0f}%)")
    print(f"  sources:     {row[3]}")
    print(f"  languages:   {row[4]}")
    print(f"  analyses:    {analyses} ({analyses/max(row[0],1)*100:.0f}%)")
    print(f"  council:     {verdicts}")
    print(f"  clusters:    {clusters}")

    # determine next phase
    if row[0] == 0:
        print(f"\n  NEXT: python3 scripts/topic_runner.py {sys.argv[1]} --phase ingest")
    elif row[1] < row[0] * 0.5:
        print(f"\n  NEXT: python3 scripts/topic_runner.py {sys.argv[1]} --phase extract")
    elif row[2] < row[1] * 0.9:
        print(f"\n  NEXT: python3 scripts/topic_runner.py {sys.argv[1]} --phase translate")
    elif analyses < row[2] * 0.9:
        print(f"\n  NEXT: python3 scripts/topic_runner.py {sys.argv[1]} --phase analyze")
    elif verdicts == 0:
        print(f"\n  NEXT: python3 scripts/topic_runner.py {sys.argv[1]} --phase council")
    elif clusters == 0:
        print(f"\n  NEXT: python3 scripts/topic_runner.py {sys.argv[1]} --phase cluster")
    else:
        print(f"\n  ALL PHASES COMPLETE")
    print(f"{'='*60}")


# ── main ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="run NewsKaleidoscope pipeline from topic config")
    parser.add_argument("config", type=str, help="path to topic YAML config")
    parser.add_argument("--phase", type=str, default="all",
                        choices=["ingest", "extract", "translate", "analyze", "council", "cluster", "report", "all", "nogpu"],
                        help="which phase to run (default: all)")
    parser.add_argument("--status", action="store_true", help="show pipeline status")
    args = parser.parse_args()

    config = load_config(args.config)
    event_id = ensure_event(config)

    if args.status:
        show_status(config, event_id)
        return

    phases = {
        "ingest": lambda: phase_ingest(config, event_id),
        "extract": lambda: phase_extract(config, event_id),
        "translate": lambda: phase_translate(config, event_id),
        "analyze": lambda: phase_analyze(config, event_id),
        "council": lambda: phase_council(config, event_id),
        "cluster": lambda: phase_cluster(config, event_id),
    }

    if args.phase == "all":
        run_phases = ["ingest", "extract", "translate", "analyze", "council", "cluster"]
    elif args.phase == "nogpu":
        # run all non-GPU phases, stop before analyze
        run_phases = ["ingest", "extract", "translate"]
    else:
        run_phases = [args.phase]

    log.info(f"topic: {config['name']} (event_id={event_id})")
    log.info(f"phases: {', '.join(run_phases)}")

    gpu_phases = {"analyze", "council", "cluster"}
    server_started = False

    for phase_name in run_phases:
        # auto-start llama-server for GPU phases
        if phase_name in gpu_phases and not server_started:
            model = config.get("llm_model", "qwen3-32b-q4km.gguf")
            model_path = f"{MODEL_DIR}/{model}"
            log.info(f"\n  starting llama-server with {model}...")
            try:
                subprocess.run(["ssh", "boron", "pkill -f llama-server"], capture_output=True, timeout=10)
                time.sleep(2)
                cmd = (
                    f"nohup {LLAMA_SERVER_BIN} "
                    f"--model {model_path} "
                    f"--tensor-split 0.5,0.5 "
                    f"--host 0.0.0.0 --port 11434 "
                    f"--ctx-size 16384 --n-gpu-layers 99 "
                    f"--parallel 4 "
                    f"> /tmp/llama-server.log 2>&1 &"
                )
                subprocess.run(["ssh", "boron", cmd], capture_output=True, timeout=10)
                # wait for server ready
                for attempt in range(60):
                    time.sleep(3)
                    try:
                        req = urllib.request.Request(f"{LLM_URL}/v1/models")
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                            if data.get("data"):
                                log.info(f"  llama-server ready: {data['data'][0].get('id')}")
                                server_started = True
                                break
                    except Exception:
                        pass
                else:
                    log.error(f"  llama-server failed to start after 180s")
                    break
            except Exception as e:
                log.error(f"  failed to start llama-server: {e}")
                break

        start_time = time.time()
        result = phases[phase_name]()
        elapsed = time.time() - start_time
        log.info(f"  {phase_name} completed in {elapsed/60:.1f} min")

    # kill llama-server after GPU phases
    if server_started:
        log.info("  stopping llama-server on boron...")
        subprocess.run(["ssh", "boron", "pkill -f llama-server"], capture_output=True, timeout=10)

    show_status(config, event_id)


if __name__ == "__main__":
    main()
