#!/usr/bin/env python3
"""
gdelt_pull.py — query GDELT 2.0 DOC API for Iran strike coverage.
outputs articles.json with enforced geographic diversity.

strategy: fetch a large pool (250), then sample evenly across countries.
if nitrogen IP is rate-limited, falls back to fetching via boron.
"""

import json
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from collections import defaultdict

GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
POOL_SIZE = 250          # fetch a big pool to sample from
MAX_PER_COUNTRY = 3      # hard cap per country
TARGET_TOTAL = 60        # aim for ~60 well-distributed articles
OUTPUT_FILE = "articles.json"

QUERY = "Iran strike attack"


def build_url():
    """build GDELT API URL."""
    params = {
        "query": QUERY,
        "mode": "artlist",
        "maxrecords": str(POOL_SIZE),
        "format": "json",
        "timespan": "7d",
    }
    return f"{GDELT_API}?{urllib.parse.urlencode(params)}"


def fetch_direct(url):
    """fetch from GDELT directly from this machine."""
    req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
    data = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            if raw.strip().startswith("{") or raw.strip().startswith("["):
                data = json.loads(raw)
                break
            else:
                wait = 15 * (attempt + 1)
                print(f"[gdelt] rate limited (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                wait = 15 * (attempt + 1)
                print(f"[gdelt] HTTP 429 (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    return data


def fetch_via_boron(url):
    """fetch GDELT via boron (different IP) to bypass rate limits."""
    print("[gdelt] using boron as proxy to avoid rate limits...")
    try:
        result = subprocess.run(
            ["ssh", "boron", f"curl -s '{url}'"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            return json.loads(result.stdout)
    except Exception as e:
        print(f"[gdelt] boron fallback failed: {e}")
    return None


def fetch_gdelt():
    """fetch articles from GDELT, with boron fallback for rate limits."""
    url = build_url()
    print(f"[gdelt] querying (pool={POOL_SIZE}): {url[:100]}...")

    # try direct first
    try:
        data = fetch_direct(url)
        if data:
            return data.get("articles", [])
    except Exception as e:
        print(f"[gdelt] direct fetch failed: {e}")

    # fallback to boron
    data = fetch_via_boron(url)
    if data:
        return data.get("articles", [])

    print("[gdelt] ERROR: all fetch methods failed", file=sys.stderr)
    sys.exit(1)


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
    """distribute articles evenly across countries.

    instead of first-come-first-served (which favors high-volume producers like China),
    this does round-robin: take 1 from each country, then 1 more from each, etc.
    until we hit MAX_PER_COUNTRY or TARGET_TOTAL.
    """
    # group by country
    by_country = defaultdict(list)
    for art in articles:
        country = art["sourcecountry"]
        if country and country != "unknown":
            by_country[country].append(art)

    # round-robin selection: 1 per country per round
    selected = []
    country_counts = defaultdict(int)
    round_num = 0

    while len(selected) < TARGET_TOTAL and round_num < MAX_PER_COUNTRY:
        added_this_round = False
        for country in sorted(by_country.keys()):
            if len(selected) >= TARGET_TOTAL:
                break
            pool = by_country[country]
            if round_num < len(pool) and country_counts[country] < MAX_PER_COUNTRY:
                selected.append(pool[round_num])
                country_counts[country] += 1
                added_this_round = True
        if not added_this_round:
            break
        round_num += 1

    return selected, dict(country_counts)


def main():
    raw = fetch_gdelt()
    if not raw:
        print("[gdelt] no articles returned. check query or try broader terms.")
        sys.exit(1)

    print(f"[gdelt] raw pool: {len(raw)} articles")

    normalized = [normalize_article(a) for a in raw]

    # deduplicate by URL
    seen_urls = set()
    deduped = []
    for art in normalized:
        if art["url"] not in seen_urls:
            seen_urls.add(art["url"])
            deduped.append(art)
    print(f"[gdelt] after dedup: {len(deduped)} articles")

    filtered, country_dist = enforce_geo_diversity(deduped)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(filtered, f, indent=2, ensure_ascii=False)

    # summary
    langs = set(a["sourcelang"] for a in filtered)
    countries = sorted(country_dist.keys())

    print(f"\n{'='*60}")
    print(f"[gdelt] SUMMARY")
    print(f"  total articles saved: {len(filtered)}")
    print(f"  countries ({len(countries)}):")
    for c in countries:
        print(f"    {c}: {country_dist[c]}")
    print(f"  languages ({len(langs)}): {', '.join(sorted(langs))}")
    print(f"  output: {OUTPUT_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
