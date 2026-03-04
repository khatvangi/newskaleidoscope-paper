#!/usr/bin/env python3
"""
gdelt_pull.py — query GDELT 2.0 DOC API for Iran strike coverage.
outputs articles.json with geographic diversity cap.
"""

import json
import sys
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime

GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_RECORDS = 75
MAX_PER_COUNTRY = 5
OUTPUT_FILE = "articles.json"

QUERY = '"Iran" ("strike" OR "attack" OR "bombing")'


def fetch_gdelt():
    """fetch articles from GDELT DOC API."""
    params = {
        "query": QUERY,
        "mode": "artlist",
        "maxrecords": str(MAX_RECORDS),
        "format": "json",
        "timespan": "7d",
    }
    url = f"{GDELT_API}?{urllib.parse.urlencode(params)}"
    print(f"[gdelt] querying: {url[:120]}...")

    req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[gdelt] ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    articles = data.get("articles", [])
    if not articles:
        print("[gdelt] no articles returned. check query or try broader terms.")
        sys.exit(1)

    print(f"[gdelt] raw articles fetched: {len(articles)}")
    return articles


def normalize_article(art):
    """extract fields we care about from GDELT article record."""
    return {
        "url": art.get("url", ""),
        "title": art.get("title", ""),
        "seendate": art.get("seendate", ""),
        "sourcecountry": art.get("sourcecountry", "unknown"),
        "sourcelang": art.get("language", art.get("sourcelang", "unknown")),
        "domain": art.get("domain", ""),
    }


def enforce_geo_diversity(articles):
    """cap articles per country to ensure geographic spread."""
    country_counts = defaultdict(int)
    filtered = []

    for art in articles:
        country = art["sourcecountry"]
        if country_counts[country] < MAX_PER_COUNTRY:
            filtered.append(art)
            country_counts[country] += 1

    return filtered, dict(country_counts)


def main():
    raw = fetch_gdelt()
    normalized = [normalize_article(a) for a in raw]
    filtered, country_dist = enforce_geo_diversity(normalized)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)

    # summary
    langs = set(a["sourcelang"] for a in filtered)
    countries = sorted(country_dist.keys())

    print(f"\n{'='*60}")
    print(f"[gdelt] SUMMARY")
    print(f"  total articles saved: {len(filtered)}")
    print(f"  countries ({len(countries)}): {', '.join(countries)}")
    print(f"  languages ({len(langs)}): {', '.join(sorted(langs))}")
    print(f"  output: {OUTPUT_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
