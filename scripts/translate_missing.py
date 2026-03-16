#!/usr/bin/env python3
"""
translate_missing.py — translate untranslated articles in the DB.

finds articles with raw_text but no translated_text, runs them through
the translation engine, and updates the DB.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import psycopg2

from translate import TranslationEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("translate_missing")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"

# optionally filter by event_id via CLI arg
EVENT_FILTER = None
if len(sys.argv) > 1:
    EVENT_FILTER = int(sys.argv[1])


def main():
    engine = TranslationEngine()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # find untranslated articles that have raw_text and aren't flagged for review
    if EVENT_FILTER:
        log.info(f"filtering to event_id={EVENT_FILTER}")
        cur.execute("""
            SELECT id, original_language, title, raw_text
            FROM articles
            WHERE (translated_text IS NULL OR translated_text = '')
              AND raw_text IS NOT NULL AND raw_text != ''
              AND (needs_human_review IS NULL OR needs_human_review = false)
              AND event_id = %s
            ORDER BY id
        """, (EVENT_FILTER,))
    else:
        cur.execute("""
            SELECT id, original_language, title, raw_text
            FROM articles
            WHERE (translated_text IS NULL OR translated_text = '')
              AND raw_text IS NOT NULL AND raw_text != ''
              AND (needs_human_review IS NULL OR needs_human_review = false)
            ORDER BY id
        """)
    rows = cur.fetchall()
    log.info(f"found {len(rows)} untranslated articles")

    translated_count = 0
    failed = []

    for article_id, lang, title, raw_text in rows:
        log.info(f"  [{article_id}] {lang}: {title[:80]}")

        # translate (use first 3000 chars like pipeline does)
        translated, lang_code = engine.translate(raw_text[:3000], source_lang=lang)

        if translated:
            ratio = len(translated.strip()) / len(raw_text.strip())
            log.info(f"    translated: {len(translated)} chars ({ratio:.0%} ratio)")

            cur.execute("""
                UPDATE articles
                SET translated_text = %s, translation_language = 'English'
                WHERE id = %s
            """, (translated, article_id))
            translated_count += 1
        else:
            log.warning(f"    FAILED to translate {lang} ({lang_code})")
            failed.append((article_id, lang, title[:60]))

    conn.commit()
    cur.close()
    conn.close()

    log.info(f"\ndone: {translated_count}/{len(rows)} translated")
    if failed:
        log.warning(f"failed ({len(failed)}):")
        for aid, lang, title in failed:
            log.warning(f"  [{aid}] {lang}: {title}")


if __name__ == "__main__":
    main()
