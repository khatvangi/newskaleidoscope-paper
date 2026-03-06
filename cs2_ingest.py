#!/usr/bin/env python3
"""
cs2_ingest.py — Case Study 2: US Reciprocal Tariffs (Liberation Day 2025)

five-window longitudinal corpus for cross-case comparison with CS1.
each window targets ~80-100 articles with enforced geographic diversity.
same outlets tracked across windows to enable drift measurement.

GDELT DOC API supports startdatetime/enddatetime for historical queries.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from collections import defaultdict
from datetime import datetime

EVENT_ID = 3  # tariffs event in DB
OUTPUT_DIR = "cs2_articles"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
POOL_SIZE = 250
MAX_PER_COUNTRY = 4
TARGET_PER_WINDOW = 100

# five analysis windows
WINDOWS = {
    "w1_announcement": {
        "label": "Window 1: Announcement Shock",
        "start": "20250402000000",
        "end": "20250408235959",
        "queries": [
            "tariff reciprocal liberation day",
            "tariff trade war april",
            "US tariff global trade",
        ],
    },
    "w2_pause": {
        "label": "Window 2: 90-Day Pause",
        "start": "20250409000000",
        "end": "20250416235959",
        "queries": [
            "tariff pause 90 day",
            "tariff exemption delay",
            "trade war pause retreat",
        ],
    },
    "w3_reimposition": {
        "label": "Window 3: Reimposition & China Escalation",
        "start": "20250501000000",
        "end": "20250731235959",
        "queries": [
            "tariff China 145 percent",
            "tariff reimposition trade war",
            "US China trade escalation tariff",
        ],
    },
    "w4_retaliation": {
        "label": "Window 4: Retaliation",
        "start": "20250801000000",
        "end": "20251031235959",
        "queries": [
            "tariff retaliation countermeasure",
            "EU Canada China retaliatory tariff",
            "trade war retaliation rare earth",
        ],
    },
    "w5_retrospective": {
        "label": "Window 5: One Year Later (Accountability)",
        "start": "20260224000000",
        "end": "20260306235959",
        "queries": [
            "tariff anniversary impact year",
            "trade war one year later",
            "liberation day tariff impact 2026",
        ],
    },
}

# economic outlets to supplement GDELT — tracked consistently across all windows
ECONOMIC_OUTLETS = [
    # global financial press
    {"name": "Financial Times", "rss": "https://www.ft.com/rss/home", "country": "United Kingdom", "language": "English", "region": "Europe"},
    {"name": "Nikkei Asia", "rss": "https://asia.nikkei.com/rss", "country": "Japan", "language": "English", "region": "East Asia"},
    {"name": "Reuters Business", "rss": "https://www.reutersagency.com/feed/?best-topics=business-finance", "country": "United States", "language": "English", "region": "North America"},
    # regional economic press
    {"name": "Caixin Global", "rss": "https://www.caixinglobal.com/rss.html", "country": "China", "language": "English", "region": "East Asia"},
    {"name": "Economic Times India", "rss": "https://economictimes.indiatimes.com/rssfeedstopstories.cms", "country": "India", "language": "English", "region": "South Asia"},
    {"name": "Business Day South Africa", "rss": "https://www.businesslive.co.za/rss/", "country": "South Africa", "language": "English", "region": "Africa"},
    # wire services
    {"name": "AP News Business", "rss": "https://rsshub.app/apnews/topics/business", "country": "United States", "language": "English", "region": "North America"},
    # latin america
    {"name": "Folha de S.Paulo", "rss": "https://feeds.folha.uol.com.br/mundo/rss091.xml", "country": "Brazil", "language": "Portuguese", "region": "Latin America"},
    # middle east
    {"name": "Al Jazeera Business", "rss": "https://www.aljazeera.com/xml/rss/all.xml", "country": "Qatar", "language": "English", "region": "Middle East"},
    # european
    {"name": "DW News", "rss": "https://rss.dw.com/rdf/rss-en-all", "country": "Germany", "language": "English", "region": "Europe"},
    {"name": "Le Monde", "rss": "https://www.lemonde.fr/international/rss_full.xml", "country": "France", "language": "French", "region": "Europe"},
    # east asian
    {"name": "South China Morning Post", "rss": "https://www.scmp.com/rss/91/feed", "country": "Hong Kong", "language": "English", "region": "East Asia"},
    {"name": "Korea Herald", "rss": "http://www.koreaherald.com/common/rss_xml.php?ct=102", "country": "South Korea", "language": "English", "region": "East Asia"},
]

TARIFF_SEARCH_TERMS = [
    "tariff", "trade war", "liberation day", "reciprocal",
    "import duty", "trade deficit", "customs", "protectionism",
]


def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_gdelt_window(query, start, end, max_records=POOL_SIZE):
    """query GDELT DOC API with date range for historical articles."""
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(max_records),
        "format": "json",
        "startdatetime": start,
        "enddatetime": end,
    }
    url = f"{GDELT_API}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            if raw.strip().startswith("{") or raw.strip().startswith("["):
                data = json.loads(raw)
                return data.get("articles", [])
            else:
                wait = 15 * (attempt + 1)
                print(f"    rate limited (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                wait = 15 * (attempt + 1)
                print(f"    HTTP 429 (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    HTTP error: {e.code}")
                return []
        except Exception as e:
            print(f"    fetch error: {e}")
            return []
    return []


def fetch_gdelt_via_boron(query, start, end, max_records=POOL_SIZE):
    """fallback: fetch GDELT via boron to bypass rate limits."""
    import subprocess
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(max_records),
        "format": "json",
        "startdatetime": start,
        "enddatetime": end,
    }
    url = f"{GDELT_API}?{urllib.parse.urlencode(params)}"

    try:
        result = subprocess.run(
            ["ssh", "boron", f"curl -s '{url}'"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            data = json.loads(result.stdout)
            return data.get("articles", [])
    except Exception as e:
        print(f"    boron fallback failed: {e}")
    return []


def normalize_article(art, window_id):
    """extract fields from GDELT record, tag with window."""
    return {
        "url": art.get("url", ""),
        "title": art.get("title", ""),
        "seendate": art.get("seendate", ""),
        "sourcecountry": art.get("sourcecountry", "unknown"),
        "sourcelang": art.get("language", art.get("sourcelang", "unknown")),
        "domain": art.get("domain", ""),
        "window": window_id,
        "event_id": EVENT_ID,
        "source": "gdelt",
    }


def enforce_geo_diversity(articles, max_per_country=MAX_PER_COUNTRY, target=TARGET_PER_WINDOW):
    """round-robin across countries for geographic balance."""
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


def ingest_window(window_id, window_cfg):
    """pull articles for a single time window."""
    label = window_cfg["label"]
    start = window_cfg["start"]
    end = window_cfg["end"]
    queries = window_cfg["queries"]

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  {start[:8]} — {end[:8]}")
    print(f"{'='*60}")

    all_articles = []
    seen_urls = set()

    for query in queries:
        print(f"  query: '{query}'...", end=" ", flush=True)

        # try direct, fallback to boron
        articles = fetch_gdelt_window(query, start, end)
        if not articles:
            articles = fetch_gdelt_via_boron(query, start, end)

        new_count = 0
        for art in articles:
            normalized = normalize_article(art, window_id)
            if normalized["url"] and normalized["url"] not in seen_urls:
                seen_urls.add(normalized["url"])
                all_articles.append(normalized)
                new_count += 1

        print(f"{new_count} new ({len(articles)} raw)")
        time.sleep(6)  # GDELT rate limit: 1 req / 5 sec

    print(f"\n  total unique articles: {len(all_articles)}")

    # enforce geographic diversity
    selected, country_dist = enforce_geo_diversity(all_articles)

    print(f"  after geo diversity: {len(selected)} articles, {len(country_dist)} countries")
    for c in sorted(country_dist.keys()):
        print(f"    {c}: {country_dist[c]}")

    return selected


def main():
    ensure_dirs()

    # which windows to ingest?
    if len(sys.argv) > 1:
        # ingest specific window(s): python3 cs2_ingest.py w1_announcement
        window_ids = sys.argv[1:]
    else:
        # ingest all windows
        window_ids = list(WINDOWS.keys())

    all_window_articles = {}
    total = 0

    for wid in window_ids:
        if wid not in WINDOWS:
            print(f"unknown window: {wid}")
            print(f"valid windows: {', '.join(WINDOWS.keys())}")
            sys.exit(1)

        articles = ingest_window(wid, WINDOWS[wid])
        all_window_articles[wid] = articles
        total += len(articles)

        # save per-window file
        outfile = os.path.join(OUTPUT_DIR, f"{wid}.json")
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        print(f"  saved: {outfile} ({len(articles)} articles)")

    # also save combined file for pipeline ingestion
    combined = []
    for wid in window_ids:
        combined.extend(all_window_articles.get(wid, []))

    combined_file = os.path.join(OUTPUT_DIR, "all_windows.json")
    with open(combined_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    # summary
    print(f"\n{'='*60}")
    print(f"CS2 INGESTION SUMMARY")
    print(f"  event_id: {EVENT_ID}")
    print(f"  windows ingested: {len(window_ids)}")
    for wid in window_ids:
        arts = all_window_articles.get(wid, [])
        countries = len(set(a["sourcecountry"] for a in arts))
        print(f"    {wid}: {len(arts)} articles, {countries} countries")
    print(f"  total articles: {total}")
    print(f"  combined file: {combined_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
