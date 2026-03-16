#!/usr/bin/env python3
"""
cs1ru_expand.py — expand CS1-RU corpus to match CS1 pipeline coverage.

phase 1: insert ALL 1,944 GDELT pool articles (no geo-diversity cap)
phase 2: insert World News API JSON output (run worldnews_ingest.py first)
phase 3: insert Reddit JSON output (run reddit_ingest.py first)

usage:
  python3 scripts/cs1ru_expand.py gdelt          # phase 1: uncap GDELT pool
  python3 scripts/cs1ru_expand.py worldnews       # phase 2: insert worldnews JSON
  python3 scripts/cs1ru_expand.py reddit           # phase 3: insert reddit JSON
  python3 scripts/cs1ru_expand.py all              # all phases (run ingestors first!)
  python3 scripts/cs1ru_expand.py status           # show current CS1-RU counts
"""

import json
import hashlib
import os
import sys
import urllib.parse
from datetime import datetime
from collections import defaultdict

import psycopg2

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
EVENT_ID = 4  # CS1-RU: Russian Invasion of Ukraine
GDELT_POOL = "sources/cs1ru/gdelt_pool.json"
WORLDNEWS_JSON = "sources/worldnews/cs1ru_ukraine.json"
REDDIT_JSON = "sources/reddit/cs1ru_ukraine.json"


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


def insert_articles(articles, source_label):
    """insert articles into DB, skip duplicates via URL unique constraint."""
    conn = get_conn()
    cur = conn.cursor()

    inserted = 0
    skipped = 0
    errors = 0

    for art in articles:
        url = art.get("url", "")
        if not url:
            continue

        # check for duplicate
        cur.execute("SELECT id FROM articles WHERE url = %s", (url,))
        if cur.fetchone():
            skipped += 1
            continue

        # resolve source
        domain = art.get("domain", "")
        if not domain and url:
            try:
                domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
            except Exception:
                pass
        source_type = "reddit" if "reddit" in source_label else "news"
        source_id = resolve_source(cur, domain, source_type)

        # parse publication date
        pub_date = None
        seendate = art.get("seendate", "")
        if seendate:
            for fmt in ["%Y%m%d", "%Y-%m-%d"]:
                try:
                    pub_date = datetime.strptime(seendate[:len(fmt.replace("%", "").replace("d", "DD").replace("m", "MM").replace("Y", "YYYY"))], fmt).date()
                    break
                except ValueError:
                    continue
            if not pub_date:
                try:
                    pub_date = datetime.strptime(seendate[:8], "%Y%m%d").date()
                except ValueError:
                    try:
                        pub_date = datetime.strptime(seendate[:10], "%Y-%m-%d").date()
                    except ValueError:
                        pass

        # get raw text from cache or article data
        raw_text = art.get("full_text", "") or art.get("text", "")
        if not raw_text and url:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            cache_path = os.path.join("cache", f"{url_hash}.txt")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        raw_text = f.read()
                except Exception:
                    pass

        try:
            cur.execute("""
                INSERT INTO articles (event_id, source_id, url, title, original_language,
                                      raw_text, publication_date, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                EVENT_ID, source_id, url, art.get("title", ""),
                art.get("sourcelang", "unknown"),
                raw_text if raw_text else None,
                pub_date,
            ))
            inserted += 1
        except Exception as e:
            errors += 1
            conn.rollback()
            conn = get_conn()
            cur = conn.cursor()
            continue

        # commit every 100 rows
        if inserted % 100 == 0:
            conn.commit()

    conn.commit()
    cur.close()
    conn.close()
    return inserted, skipped, errors


def phase_gdelt():
    """phase 1: insert ALL GDELT pool articles (no cap)."""
    print(f"\n{'='*60}")
    print(f"PHASE 1: GDELT pool uncap")
    print(f"{'='*60}")

    if not os.path.exists(GDELT_POOL):
        print(f"  ERROR: pool file not found: {GDELT_POOL}")
        return

    with open(GDELT_POOL, "r", encoding="utf-8") as f:
        pool = json.load(f)

    print(f"  pool size: {len(pool)} articles")

    # count languages and countries in pool
    langs = defaultdict(int)
    countries = defaultdict(int)
    for art in pool:
        langs[art.get("sourcelang", "unknown")] += 1
        countries[art.get("sourcecountry", "unknown")] += 1
    print(f"  languages: {len(langs)}")
    print(f"  countries: {len(countries)}")

    inserted, skipped, errors = insert_articles(pool, "gdelt")

    print(f"\n  GDELT results:")
    print(f"    inserted: {inserted}")
    print(f"    skipped (duplicates): {skipped}")
    print(f"    errors: {errors}")


def phase_worldnews():
    """phase 2: insert World News API output."""
    print(f"\n{'='*60}")
    print(f"PHASE 2: World News API articles")
    print(f"{'='*60}")

    if not os.path.exists(WORLDNEWS_JSON):
        print(f"  ERROR: run worldnews_ingest.py cs1ru_ukraine first")
        print(f"  expected: {WORLDNEWS_JSON}")
        return

    with open(WORLDNEWS_JSON, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"  articles from JSON: {len(articles)}")
    inserted, skipped, errors = insert_articles(articles, "worldnews")

    print(f"\n  World News results:")
    print(f"    inserted: {inserted}")
    print(f"    skipped (duplicates): {skipped}")
    print(f"    errors: {errors}")


def phase_reddit():
    """phase 3: insert Reddit output."""
    print(f"\n{'='*60}")
    print(f"PHASE 3: Reddit articles")
    print(f"{'='*60}")

    if not os.path.exists(REDDIT_JSON):
        print(f"  ERROR: run reddit_ingest.py cs1ru_ukraine first")
        print(f"  expected: {REDDIT_JSON}")
        return

    with open(REDDIT_JSON, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"  articles from JSON: {len(articles)}")
    inserted, skipped, errors = insert_articles(articles, "reddit")

    print(f"\n  Reddit results:")
    print(f"    inserted: {inserted}")
    print(f"    skipped (duplicates): {skipped}")
    print(f"    errors: {errors}")


def show_status():
    """show current CS1-RU article counts vs CS1."""
    conn = get_conn()
    cur = conn.cursor()

    for event_id, label in [(2, "CS1 (Iran)"), (4, "CS1-RU (Ukraine)")]:
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(DISTINCT source_id) as sources,
                   COUNT(DISTINCT original_language) as langs,
                   COUNT(CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 END) as with_text,
                   COUNT(CASE WHEN translated_text IS NOT NULL THEN 1 END) as translated
            FROM articles WHERE event_id = %s
        """, (event_id,))
        row = cur.fetchone()
        print(f"\n  {label}:")
        print(f"    total articles: {row[0]}")
        print(f"    sources: {row[1]}")
        print(f"    languages: {row[2]}")
        print(f"    with raw_text: {row[3]}")
        print(f"    translated: {row[4]}")

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
    elif cmd == "reddit":
        phase_reddit()
        show_status()
    elif cmd == "all":
        phase_gdelt()
        phase_worldnews()
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
