#!/usr/bin/env python3
"""
cs2_expand.py — import existing CS2 source pools into PostgreSQL.

Phase layout mirrors scripts/cs1ru_expand.py:
1. GDELT longitudinal pool from cs2_articles/all_windows.json
2. World News API JSON files under sources/worldnews/cs2_tariffs*.json
3. MarketAux financial layer under sources/marketaux/cs2_tariffs*.json
4. Reddit vernacular layer under sources/reddit/cs2_tariffs.json

Usage:
  python3 scripts/cs2_expand.py gdelt
  python3 scripts/cs2_expand.py worldnews
  python3 scripts/cs2_expand.py marketaux
  python3 scripts/cs2_expand.py reddit
  python3 scripts/cs2_expand.py all
  python3 scripts/cs2_expand.py status
"""

import glob
import hashlib
import json
import os
import sys
import urllib.parse
from datetime import datetime

import psycopg2

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
EVENT_ID = 3
GDELT_JSON = "cs2_articles/all_windows.json"
WORLDNEWS_GLOB = "sources/worldnews/cs2_tariffs*.json"
MARKETAUX_GLOB = "sources/marketaux/cs2_tariffs*.json"
REDDIT_JSON = "sources/reddit/cs2_tariffs.json"


def get_conn():
    return psycopg2.connect(DB_URL)


def resolve_source(cur, domain, source_type):
    if not domain:
        return None

    cur.execute("SELECT id FROM sources WHERE name = %s", (domain,))
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        "INSERT INTO sources (name, source_type) VALUES (%s, %s) RETURNING id",
        (domain, source_type),
    )
    return cur.fetchone()[0]


def parse_pub_date(seendate):
    if not seendate:
        return None
    value = str(seendate).strip()
    for fmt, width in (("%Y%m%d%H%M%S", 14), ("%Y%m%d", 8), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(value[:width], fmt).date()
        except ValueError:
            continue
    return None


def get_raw_text(art):
    raw_text = art.get("full_text", "") or art.get("text", "")
    if raw_text:
        return raw_text

    url = art.get("url", "")
    if not url:
        return None

    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join("cache", f"{url_hash}.txt")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
    return None


def insert_articles(articles, source_type):
    conn = get_conn()
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    errors = 0

    try:
        for art in articles:
            url = (art.get("url") or "").strip()
            if not url:
                continue

            cur.execute("SELECT id FROM articles WHERE url = %s", (url,))
            if cur.fetchone():
                skipped += 1
                continue

            domain = (art.get("domain") or "").strip()
            if not domain:
                try:
                    domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
                except Exception:
                    domain = ""

            source_id = resolve_source(cur, domain, source_type) if domain else None
            pub_date = parse_pub_date(art.get("seendate", ""))
            raw_text = get_raw_text(art)
            language = art.get("sourcelang", "unknown")

            try:
                cur.execute(
                    """
                    INSERT INTO articles (
                        event_id, source_id, url, title, original_language,
                        raw_text, translated_text, publication_date, ingested_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        EVENT_ID,
                        source_id,
                        url,
                        art.get("title", ""),
                        language,
                        raw_text,
                        raw_text if language.lower() in {"english", "en"} else None,
                        pub_date,
                    ),
                )
                inserted += 1
                if inserted % 100 == 0:
                    conn.commit()
            except Exception:
                errors += 1
                conn.rollback()
                conn = get_conn()
                cur = conn.cursor()

        conn.commit()
    finally:
        cur.close()
        conn.close()

    return inserted, skipped, errors


def load_json_articles(paths):
    loaded = []
    seen_urls = set()

    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            continue
        for art in data:
            url = (art.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            loaded.append(art)

    return loaded


def phase_gdelt():
    print(f"\n{'=' * 60}")
    print("PHASE 1: CS2 GDELT pool")
    print(f"{'=' * 60}")
    if not os.path.exists(GDELT_JSON):
        print(f"  missing: {GDELT_JSON}")
        return
    articles = load_json_articles([GDELT_JSON])
    print(f"  loaded: {len(articles)}")
    inserted, skipped, errors = insert_articles(articles, "gdelt_discovered")
    print(f"  inserted: {inserted}")
    print(f"  skipped: {skipped}")
    print(f"  errors: {errors}")


def phase_worldnews():
    print(f"\n{'=' * 60}")
    print("PHASE 2: CS2 World News")
    print(f"{'=' * 60}")
    paths = sorted(glob.glob(WORLDNEWS_GLOB))
    if not paths:
        print(f"  no files matched: {WORLDNEWS_GLOB}")
        return
    articles = load_json_articles(paths)
    print(f"  files: {len(paths)}")
    print(f"  loaded: {len(articles)}")
    inserted, skipped, errors = insert_articles(articles, "regional_flagship")
    print(f"  inserted: {inserted}")
    print(f"  skipped: {skipped}")
    print(f"  errors: {errors}")


def phase_marketaux():
    print(f"\n{'=' * 60}")
    print("PHASE 3: CS2 MarketAux")
    print(f"{'=' * 60}")
    paths = sorted(glob.glob(MARKETAUX_GLOB))
    if not paths:
        print(f"  no files matched: {MARKETAUX_GLOB}")
        return
    articles = load_json_articles(paths)
    print(f"  files: {len(paths)}")
    print(f"  loaded: {len(articles)}")
    inserted, skipped, errors = insert_articles(articles, "financial_news")
    print(f"  inserted: {inserted}")
    print(f"  skipped: {skipped}")
    print(f"  errors: {errors}")


def phase_reddit():
    print(f"\n{'=' * 60}")
    print("PHASE 4: CS2 Reddit")
    print(f"{'=' * 60}")
    if not os.path.exists(REDDIT_JSON):
        print(f"  missing: {REDDIT_JSON}")
        return
    articles = load_json_articles([REDDIT_JSON])
    print(f"  loaded: {len(articles)}")
    inserted, skipped, errors = insert_articles(articles, "reddit")
    print(f"  inserted: {inserted}")
    print(f"  skipped: {skipped}")
    print(f"  errors: {errors}")


def show_status():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT source_id) AS sources,
                   COUNT(DISTINCT original_language) AS langs,
                   COUNT(CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 END) AS with_text,
                   COUNT(CASE WHEN translated_text IS NOT NULL AND translated_text != '' THEN 1 END) AS translated
            FROM articles
            WHERE event_id = %s
            """,
            (EVENT_ID,),
        )
        row = cur.fetchone()
        print(f"\nCS2 status:")
        print(f"  total articles: {row[0]}")
        print(f"  sources: {row[1]}")
        print(f"  languages: {row[2]}")
        print(f"  with raw_text: {row[3]}")
        print(f"  translated: {row[4]}")
    finally:
        cur.close()
        conn.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "gdelt":
        phase_gdelt()
        show_status()
    elif cmd == "worldnews":
        phase_worldnews()
        show_status()
    elif cmd == "marketaux":
        phase_marketaux()
        show_status()
    elif cmd == "reddit":
        phase_reddit()
        show_status()
    elif cmd == "all":
        phase_gdelt()
        phase_worldnews()
        phase_marketaux()
        phase_reddit()
        show_status()
    elif cmd == "status":
        show_status()
    else:
        print(f"unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
