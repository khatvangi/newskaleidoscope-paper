#!/usr/bin/env python3
"""
fetch_text_cs1ru.py — fetch article body text for CS1-RU articles.

2022 articles: many original URLs are dead. uses trafilatura → newspaper3k → wayback.
updates articles.raw_text in DB and caches to cache/ directory.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hashlib
import logging
import time

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fetch_text")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
CACHE_DIR = "cache"
EVENT_ID = 4


def fetch_article_text(url):
    """fetch and extract article text. trafilatura -> newspaper3k -> wayback."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")

    # check cache first
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            text = f.read()
        if text.strip():
            return text

    text = None

    # tier 1: trafilatura (best quality)
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False,
                                       include_tables=False)
    except Exception as e:
        log.debug(f"  trafilatura failed: {e}")

    # tier 2: newspaper3k
    if not text:
        try:
            from newspaper import Article
            article = Article(url)
            article.download()
            article.parse()
            text = article.text
        except Exception as e:
            log.debug(f"  newspaper3k failed: {e}")

    # tier 3: wayback machine (critical for 2022 articles)
    if not text:
        try:
            from archive_fetcher import fetch_via_wayback
            text = fetch_via_wayback(url)
            if text:
                log.info(f"    wayback recovered: {len(text)} chars")
        except Exception as e:
            log.debug(f"  wayback failed: {e}")

    # cache if we got something
    if text and text.strip():
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text

    return None


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, url, title
        FROM articles
        WHERE event_id = %s AND (raw_text IS NULL OR raw_text = '')
        ORDER BY id
    """, (EVENT_ID,))
    rows = cur.fetchall()
    log.info(f"fetching text for {len(rows)} articles (event_id={EVENT_ID})")

    success = 0
    failed = 0
    failed_urls = []

    for i, (article_id, url, title) in enumerate(rows):
        log.info(f"  [{i+1}/{len(rows)}] {url[:70]}...")

        text = fetch_article_text(url)

        if text and len(text.strip()) > 100:
            cur.execute("UPDATE articles SET raw_text = %s WHERE id = %s", (text, article_id))
            success += 1
            log.info(f"    OK: {len(text)} chars")
        else:
            failed += 1
            failed_urls.append((article_id, url[:80]))
            log.warning(f"    FAILED: no text extracted")

        # commit every 20 articles
        if (i + 1) % 20 == 0:
            conn.commit()
            log.info(f"    checkpoint: {success} success, {failed} failed")

        # brief pause to be polite to servers
        time.sleep(0.5)

    conn.commit()
    cur.close()
    conn.close()

    log.info(f"\n{'='*60}")
    log.info(f"TEXT EXTRACTION COMPLETE")
    log.info(f"  success: {success}/{len(rows)}")
    log.info(f"  failed: {failed}/{len(rows)}")
    if failed_urls:
        log.info(f"  failed URLs:")
        for aid, url in failed_urls[:20]:
            log.info(f"    [{aid}] {url}")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
