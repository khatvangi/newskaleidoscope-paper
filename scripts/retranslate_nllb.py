#!/usr/bin/env python3
"""
retranslate_nllb.py — re-translate specific articles using NLLB-200 instead of Helsinki.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import psycopg2

from translate import TranslationEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("retranslate_nllb")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"

# articles where Helsinki gave bad translations — force NLLB
ARTICLE_IDS = [125, 176, 363]


def main():
    engine = TranslationEngine()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, original_language, title, raw_text
        FROM articles
        WHERE id = ANY(%s)
        ORDER BY id
    """, (ARTICLE_IDS,))
    rows = cur.fetchall()

    for article_id, lang, title, raw_text in rows:
        log.info(f"  [{article_id}] {lang}: {title[:80]}")

        # resolve lang code
        lang_code = engine.lang_name_to_code(lang)
        log.info(f"    lang_code: {lang_code}")

        # force NLLB translation (bypass Helsinki)
        translated = engine._translate_nllb(raw_text[:3000], lang_code)

        if translated:
            ratio = len(translated.strip()) / len(raw_text.strip())
            log.info(f"    NLLB translated: {len(translated)} chars ({ratio:.0%} ratio)")
            log.info(f"    preview: {translated[:200]}")

            cur.execute("""
                UPDATE articles
                SET translated_text = %s, translation_language = 'English'
                WHERE id = %s
            """, (translated, article_id))
        else:
            log.warning(f"    NLLB FAILED for {lang_code}")

    conn.commit()
    cur.close()
    conn.close()
    log.info("done")


if __name__ == "__main__":
    main()
