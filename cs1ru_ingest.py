#!/usr/bin/env python3
"""
cs1ru_ingest.py — Case Study 1-RU: Russian Invasion of Ukraine (Feb 24, 2022)

comparison case for CS1 (US-Israel strikes on Iran). same 7-day window,
same geographic diversity enforcement, same pipeline. different event.

sources:
  1. GDELT DOC API (historical) — primary, multilingual
  2. API League (historical search) — supplement for English/major languages

GDELT has full 2022 archive. rate limit: 1 req per 5s, falls back to boron.
"""

import json
import hashlib
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from collections import defaultdict
from datetime import datetime

import psycopg2

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
POOL_SIZE = 250
MAX_PER_COUNTRY = 5      # slightly higher than CS1 — big event, more coverage
TARGET_TOTAL = 80         # per query batch
REQUEST_DELAY = 8         # GDELT is aggressive about rate limits

# event window: Feb 24 - Mar 2, 2022 (7 days, matching CS1's window)
START_DATE = "20220224000000"
END_DATE = "20220302235959"

# multilingual queries — native terms for maximum recall
# each query targets different language clusters
QUERIES = [
    # english
    "Russia Ukraine invasion attack",
    "Russia Ukraine war military operation",
    # broader terms for non-English GDELT coverage
    "Ukraine Kyiv attack Russia",
    "Zelensky Putin Ukraine war",
    # terms that capture different framings
    "special military operation Ukraine",  # Russian framing
    "Ukraine aggression sovereignty",      # Western framing
    "Ukraine refugees humanitarian crisis",  # humanitarian angle
    "NATO Ukraine Russia sanctions",        # geopolitical angle
]

# API League queries for supplementary English/major language coverage
API_LEAGUE_QUERIES = {
    "en": ["Russia invasion Ukraine February 2022"],
    "fr": ["invasion russe Ukraine guerre"],
    "de": ["Russland Ukraine Invasion Krieg"],
    "es": ["Rusia invasion Ucrania guerra"],
    "ar": ["روسيا أوكرانيا غزو حرب"],
    "zh": ["俄罗斯 乌克兰 入侵 战争"],
    "tr": ["Rusya Ukrayna savaş işgal"],
    "pt": ["Rússia Ucrânia invasão guerra"],
    "ko": ["러시아 우크라이나 침공 전쟁"],
    "ja": ["ロシア ウクライナ 侵攻 戦争"],
    "hi": ["रूस यूक्रेन आक्रमण युद्ध"],
    "it": ["Russia Ucraina invasione guerra"],
    "ru": ["Россия Украина вторжение война"],
    "fa": ["روسیه اوکراین حمله جنگ"],
}


def fetch_via_boron(url):
    """fetch via boron to bypass nitrogen rate limits."""
    try:
        result = subprocess.run(
            ["ssh", "boron", f"curl -s '{url}'"],
            capture_output=True, text=True, timeout=45
        )
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            return json.loads(result.stdout)
    except Exception as e:
        print(f"  [boron fallback failed: {e}]")
    return None


def fetch_gdelt(query):
    """fetch articles from GDELT DOC API for a single query."""
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(POOL_SIZE),
        "format": "json",
        "startdatetime": START_DATE,
        "enddatetime": END_DATE,
    }
    url = f"{GDELT_API}?{urllib.parse.urlencode(params)}"
    print(f"  query: {query[:50]}...")

    # try direct first
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            if raw.strip().startswith("{"):
                data = json.loads(raw)
                return data.get("articles", [])
            else:
                wait = 10 * (attempt + 1)
                print(f"    rate limited (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
        except Exception as e:
            print(f"    direct failed: {e}")
            time.sleep(5)

    # fallback to boron
    print("    falling back to boron...")
    data = fetch_via_boron(url)
    if data:
        return data.get("articles", [])
    return []


def fetch_api_league(lang, query):
    """fetch from API League (World News API backend) for a single language+query."""
    api_key = os.environ.get("APILEAGUE_API_KEY", "")
    if not api_key:
        return []

    params = {
        "text": query,
        "language": lang,
        "earliest-publish-date": "2022-02-24",
        "latest-publish-date": "2022-03-02",
        "number": "50",
        "api-key": api_key,
    }
    url = f"https://api.apileague.com/search-news?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("news", [])
    except Exception as e:
        print(f"    API League {lang} failed: {e}")
        return []


def normalize_gdelt(art):
    """normalize GDELT article to common format."""
    return {
        "url": art.get("url", ""),
        "title": art.get("title", ""),
        "seendate": art.get("seendate", ""),
        "sourcecountry": art.get("sourcecountry", "unknown"),
        "sourcelang": art.get("language", "unknown"),
        "domain": art.get("domain", ""),
        "source_api": "gdelt",
    }


def normalize_api_league(art, lang):
    """normalize API League article to common format."""
    # map language codes to language names
    lang_names = {
        "en": "English", "fr": "French", "de": "German", "es": "Spanish",
        "ar": "Arabic", "zh": "Chinese", "tr": "Turkish", "pt": "Portuguese",
        "ko": "Korean", "ja": "Japanese", "hi": "Hindi", "it": "Italian",
        "ru": "Russian", "fa": "Persian",
    }
    return {
        "url": art.get("url", ""),
        "title": art.get("title", ""),
        "seendate": art.get("publish_date", ""),
        "sourcecountry": art.get("source_country", "unknown"),
        "sourcelang": lang_names.get(lang, lang),
        "domain": urllib.parse.urlparse(art.get("url", "")).netloc,
        "source_api": "api_league",
        # API League returns full text — cache it
        "full_text": art.get("text", ""),
    }


def enforce_geo_diversity(articles, target=TARGET_TOTAL, max_per_country=MAX_PER_COUNTRY):
    """round-robin selection across countries."""
    by_country = defaultdict(list)
    for art in articles:
        country = art.get("sourcecountry", "unknown")
        if country and country != "unknown":
            by_country[country].append(art)

    selected = []
    country_counts = defaultdict(int)
    round_num = 0

    while len(selected) < target and round_num < max_per_country:
        added = False
        for country in sorted(by_country.keys()):
            if len(selected) >= target:
                break
            pool = by_country[country]
            if round_num < len(pool) and country_counts[country] < max_per_country:
                selected.append(pool[round_num])
                country_counts[country] += 1
                added = True
        if not added:
            break
        round_num += 1

    return selected, dict(country_counts)


def cache_text(url, text):
    """cache article text by URL hash."""
    os.makedirs("cache", exist_ok=True)
    url_hash = hashlib.md5(url.encode()).hexdigest()
    path = os.path.join("cache", f"{url_hash}.txt")
    if not os.path.exists(path) and text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return path


def insert_to_db(articles, event_id):
    """insert articles into PostgreSQL, skip duplicates."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    inserted = 0
    skipped = 0

    for art in articles:
        url = art["url"]
        if not url:
            continue

        # check for duplicate
        cur.execute("SELECT id FROM articles WHERE url = %s", (url,))
        if cur.fetchone():
            skipped += 1
            continue

        # resolve source_id from domain
        domain = art.get("domain", "")
        cur.execute("SELECT id FROM sources WHERE name = %s", (domain,))
        row = cur.fetchone()
        if row:
            source_id = row[0]
        else:
            # create new source
            cur.execute(
                "INSERT INTO sources (name, source_type) VALUES (%s, %s) RETURNING id",
                (domain, "news")
            )
            source_id = cur.fetchone()[0]

        # parse publication date
        pub_date = None
        seendate = art.get("seendate", "")
        if seendate:
            try:
                # GDELT format: 20220225T150000Z
                pub_date = datetime.strptime(seendate[:8], "%Y%m%d").date()
            except ValueError:
                try:
                    # API League format: 2022-02-25 15:00:00
                    pub_date = datetime.strptime(seendate[:10], "%Y-%m-%d").date()
                except ValueError:
                    pass

        # cache full text if available (API League provides it)
        raw_text = art.get("full_text", "")
        if raw_text:
            cache_text(url, raw_text)

        cur.execute("""
            INSERT INTO articles (event_id, source_id, url, title, original_language,
                                  raw_text, publication_date, ingested_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (
            event_id, source_id, url, art.get("title", ""),
            art.get("sourcelang", "unknown"),
            raw_text if raw_text else None,
            pub_date,
        ))
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    return inserted, skipped


def main():
    print("=" * 60)
    print("CS1-RU: Russian Invasion of Ukraine (Feb 24 - Mar 2, 2022)")
    print("=" * 60)

    all_articles = []
    seen_urls = set()

    # phase 1: GDELT queries
    print(f"\n[phase 1] GDELT DOC API — {len(QUERIES)} queries")
    for i, query in enumerate(QUERIES):
        print(f"\n  [{i+1}/{len(QUERIES)}]", end=" ")
        articles = fetch_gdelt(query)
        new = 0
        for art in articles:
            normalized = normalize_gdelt(art)
            if normalized["url"] and normalized["url"] not in seen_urls:
                seen_urls.add(normalized["url"])
                all_articles.append(normalized)
                new += 1
        print(f"    got {len(articles)}, {new} new (total pool: {len(all_articles)})")
        time.sleep(REQUEST_DELAY)

    # phase 2: API League supplementary
    print(f"\n[phase 2] API League — {len(API_LEAGUE_QUERIES)} languages")
    for lang, queries in API_LEAGUE_QUERIES.items():
        for query in queries:
            print(f"  {lang}: {query[:40]}...", end=" ")
            articles = fetch_api_league(lang, query)
            new = 0
            for art in articles:
                normalized = normalize_api_league(art, lang)
                if normalized["url"] and normalized["url"] not in seen_urls:
                    seen_urls.add(normalized["url"])
                    all_articles.append(normalized)
                    new += 1
            print(f"got {len(articles)}, {new} new")
            time.sleep(1.5)

    print(f"\n[pool] total unique articles: {len(all_articles)}")

    # language/country distribution of pool
    langs = defaultdict(int)
    countries = defaultdict(int)
    for art in all_articles:
        langs[art["sourcelang"]] += 1
        countries[art["sourcecountry"]] += 1

    print(f"  languages ({len(langs)}):")
    for l, n in sorted(langs.items(), key=lambda x: -x[1])[:20]:
        print(f"    {l}: {n}")
    print(f"  countries ({len(countries)}):")
    for c, n in sorted(countries.items(), key=lambda x: -x[1])[:20]:
        print(f"    {c}: {n}")

    # enforce geographic diversity
    # use larger target since this was the biggest news event of 2022
    selected, country_dist = enforce_geo_diversity(
        all_articles, target=300, max_per_country=MAX_PER_COUNTRY
    )

    print(f"\n[selected] {len(selected)} articles across {len(country_dist)} countries")

    # create event in DB if needed
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT id FROM events WHERE title LIKE '%Russia%Ukraine%'")
    row = cur.fetchone()
    if row:
        event_id = row[0]
        print(f"\n[db] using existing event_id={event_id}")
    else:
        cur.execute("""
            INSERT INTO events (title, description, event_type, event_date, primary_actors,
                                geographic_scope, prompt_context, absence_examples, corpus_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            "Russian Invasion of Ukraine",
            "February 24, 2022: Russia launches full-scale military invasion of Ukraine. "
            "Largest conventional military attack in Europe since WWII. "
            "Comparison case study for CS1 (US-Israel strikes on Iran, 2026).",
            "military",
            "2022-02-24",
            json.dumps(["Russia", "Ukraine", "NATO"]),
            "global",
            "Russian military invasion of Ukraine",
            "Ukrainian civilian voices, Russian anti-war protesters, Central Asian perspectives, "
            "African Union mediation positions, Chinese internal debate",
            "v1",
        ))
        event_id = cur.fetchone()[0]
        conn.commit()
        print(f"\n[db] created event_id={event_id}")
    cur.close()
    conn.close()

    # insert to DB
    inserted, skipped = insert_to_db(selected, event_id)

    # summary
    print(f"\n{'='*60}")
    print(f"CS1-RU INGESTION SUMMARY")
    print(f"  event_id: {event_id}")
    print(f"  total pool: {len(all_articles)}")
    print(f"  selected (geo-diverse): {len(selected)}")
    print(f"  inserted to DB: {inserted}")
    print(f"  duplicates skipped: {skipped}")
    print(f"  countries: {len(country_dist)}")
    print(f"  date range: Feb 24 - Mar 2, 2022")
    print(f"{'='*60}")

    # save raw pool for reference
    os.makedirs("sources/cs1ru", exist_ok=True)
    with open("sources/cs1ru/gdelt_pool.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)
    print(f"  raw pool saved: sources/cs1ru/gdelt_pool.json")


if __name__ == "__main__":
    main()
