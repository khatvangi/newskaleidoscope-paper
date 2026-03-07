#!/usr/bin/env python3
"""
archive_fetcher.py — retrieve article text via Wayback Machine when direct fetch fails.

the Internet Archive's CDX API is fully open, no auth needed.
for non-commercial research use (which we are), this is explicitly permitted.

two modes:
  1. standalone: re-fetch all failed articles from the current pipeline run
  2. library: import fetch_via_wayback() into pipeline.py as fallback layer

CDX API docs: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

CACHE_DIR = "cache"
CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PREFIX = "https://web.archive.org/web"
USER_AGENT = "NewsKaleidoscope/0.1 (epistemic mapping research, non-commercial)"
REQUEST_DELAY = 1.0  # be polite to archive.org


def fetch_via_wayback(url, max_age_days=365):
    """try to retrieve article text from the Wayback Machine.

    1. query CDX API for closest snapshot
    2. fetch the archived page
    3. extract text with trafilatura

    returns extracted text or None.
    """
    # check cache first — same hash scheme as pipeline.py
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            text = f.read()
        if text.strip():
            return text

    # query CDX for closest snapshot
    snapshot_url = find_snapshot(url)
    if not snapshot_url:
        return None

    # fetch archived page
    time.sleep(REQUEST_DELAY)
    html = fetch_archived_page(snapshot_url)
    if not html:
        return None

    # extract text
    text = extract_text(html, url)
    if text and text.strip():
        # cache it — same location pipeline.py expects
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text

    return None


def find_snapshot(url, limit=1):
    """query the CDX API for the closest archived snapshot of a URL.

    returns the full wayback URL or None.
    CDX returns tab-separated lines: urlkey timestamp original mimetype statuscode digest length
    """
    params = {
        "url": url,
        "output": "json",
        "limit": str(limit),
        "filter": "statuscode:200",
        "fl": "timestamp,original",
    }
    cdx_url = f"{CDX_API}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(cdx_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # first row is header, second row is data
        if len(data) < 2:
            return None
        timestamp = data[1][0]
        original = data[1][1]
        # construct wayback URL — use 'id_' suffix to get original page (no wayback toolbar)
        return f"{WAYBACK_PREFIX}/{timestamp}id_/{original}"
    except Exception as e:
        # don't print per-URL errors in batch mode — too noisy
        return None


def fetch_archived_page(wayback_url, retries=2):
    """fetch HTML from a Wayback Machine snapshot URL."""
    req = urllib.request.Request(wayback_url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 10 * (attempt + 1)
                print(f"    archive.org rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 404:
                return None
            else:
                return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(3)
    return None


def extract_text(html, original_url=""):
    """extract article body text from HTML using trafilatura."""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False,
                                    url=original_url)
        return text
    except Exception:
        return None


# ── standalone mode: backfill failed articles ──────────────────────

def backfill_from_log(log_path="logs/pipeline.log", articles_path="articles.json"):
    """find articles that failed text extraction and retry via Wayback Machine."""
    import re

    # load articles to get URLs
    with open(articles_path, "r", encoding="utf-8") as f:
        articles = json.load(f)
    url_map = {a["url"]: a for a in articles}

    # find failed URLs from pipeline log
    # log format: [N/M] domain.com — title...
    # followed by: SKIP: could not fetch article text
    failed_urls = []
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_url = None
    for i, line in enumerate(lines):
        # match article processing lines
        match = re.search(r'\[\d+/\d+\]\s+(\S+)\s+', line)
        if match:
            domain = match.group(1)
            # find the article URL by domain match from recent lines
            current_url = None
            for url, art in url_map.items():
                if art.get("domain", "") == domain or domain in url:
                    url_hash = hashlib.md5(url.encode()).hexdigest()
                    cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
                    if not os.path.exists(cache_path):
                        current_url = url
                        break

        if "SKIP: could not fetch" in line and current_url:
            failed_urls.append(current_url)
            current_url = None

    # deduplicate
    failed_urls = list(dict.fromkeys(failed_urls))
    print(f"found {len(failed_urls)} failed articles to retry via Wayback Machine")

    # also find uncached articles directly — more reliable than log parsing
    uncached = []
    for art in articles:
        url = art.get("url", "")
        if not url:
            continue
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
        if not os.path.exists(cache_path):
            uncached.append(url)

    # combine both lists
    all_missing = list(dict.fromkeys(failed_urls + uncached))
    print(f"total uncached articles: {len(all_missing)}")

    recovered = 0
    failed = 0

    for i, url in enumerate(all_missing):
        print(f"  [{i+1}/{len(all_missing)}] {url[:80]}...", end=" ", flush=True)

        text = fetch_via_wayback(url)
        if text:
            print(f"OK ({len(text)} chars)")
            recovered += 1
        else:
            print("not archived")
            failed += 1

        # be polite — 1 req/sec to CDX + 1 req/sec to wayback
        time.sleep(REQUEST_DELAY)

    print(f"\nWayback Machine backfill complete:")
    print(f"  recovered: {recovered}")
    print(f"  not found: {failed}")
    print(f"  total:     {len(all_missing)}")
    return recovered


def backfill_uncached(articles_path="articles.json"):
    """simpler approach: just find all articles without cached text and try wayback."""
    with open(articles_path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    uncached = []
    for art in articles:
        url = art.get("url", "")
        if not url:
            continue
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
        if not os.path.exists(cache_path):
            uncached.append(art)

    print(f"articles without cached text: {len(uncached)} / {len(articles)}")

    # group by domain for reporting
    by_domain = {}
    for art in uncached:
        d = art.get("domain", "unknown")
        by_domain.setdefault(d, []).append(art)
    print(f"from {len(by_domain)} domains:")
    for d in sorted(by_domain.keys()):
        print(f"  {d}: {len(by_domain[d])}")

    recovered = 0
    failed = 0

    for i, art in enumerate(uncached):
        url = art["url"]
        domain = art.get("domain", "")
        country = art.get("sourcecountry", "")
        lang = art.get("sourcelang", "")
        print(f"  [{i+1}/{len(uncached)}] {domain} ({country}/{lang})", end=" ", flush=True)

        text = fetch_via_wayback(url)
        if text:
            print(f"OK ({len(text)} chars)")
            recovered += 1
        else:
            print("miss")
            failed += 1

        time.sleep(REQUEST_DELAY)

    print(f"\nbackfill complete: {recovered} recovered, {failed} not found, {len(uncached)} total")
    return recovered


if __name__ == "__main__":
    os.makedirs(CACHE_DIR, exist_ok=True)

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # test with a single URL
        test_url = sys.argv[2] if len(sys.argv) > 2 else "https://www.bbc.com/news/world-middle-east-68000000"
        print(f"testing wayback fetch for: {test_url}")
        snapshot = find_snapshot(test_url)
        print(f"snapshot: {snapshot}")
        if snapshot:
            text = fetch_via_wayback(test_url)
            if text:
                print(f"extracted {len(text)} chars:")
                print(text[:500])
            else:
                print("extraction failed")
    else:
        # backfill all uncached articles
        articles_path = sys.argv[1] if len(sys.argv) > 1 else "articles.json"
        backfill_uncached(articles_path)
