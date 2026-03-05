#!/usr/bin/env python3
"""
sermon_harvester.py — tier 3 ingestion: Friday sermon archives.

harvests published Friday sermons (khutbahs) from official religious
institution websites. these represent positions that emerge from
religious authority structures — often invisible to mainstream media analysis.

target institutions:
  - Al-Azhar (Egypt) — Sunni world's most influential seminary
  - Mecca/Medina (Saudi Arabia) — Haramain sermons
  - Diyanet (Turkey) — state religious affairs directorate
  - MUI (Indonesia) — Indonesian Ulama Council
  - ISNA (North America) — Islamic Society of North America
  - Dar al-Ifta (Egypt) — official fatwa house

output matches pipeline.py's articles.json schema.
"""

import json
import os
import re
import sys
import time
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timedelta

ARTICLES_FILE = "articles.json"
MAX_PER_SOURCE = 2
LOOKBACK_DAYS = 14  # sermons may be posted with delay

SEARCH_TERMS = ["iran", "strike", "war", "peace", "ummah", "muslim",
                "aggression", "occupation", "nuclear", "defense"]

# sermon sources — URLs for official sermon archives
# note: many of these are in Arabic/Turkish/Indonesian — that's the point
SERMON_SOURCES = [
    {
        "name": "Al-Azhar (Cairo)",
        "url": "https://www.azhar.eg/en/observer",
        "country": "Egypt",
        "language": "Arabic",
        "region": "Middle East",
        "institution_type": "Sunni seminary",
        "notes": "most influential Sunni institution globally",
    },
    {
        "name": "Diyanet (Turkey)",
        "url": "https://www.diyanet.gov.tr/en-US/Content/PrintDetail/29339",
        "country": "Turkey",
        "language": "Turkish",
        "region": "Middle East",
        "institution_type": "state religious directorate",
        "notes": "Turkish state controls all mosque sermons through Diyanet",
    },
    {
        "name": "ISNA (North America)",
        "url": "https://isna.net/category/friday-khutbah/",
        "country": "United States",
        "language": "English",
        "region": "North America",
        "institution_type": "diaspora umbrella organization",
        "notes": "largest Muslim organization in North America",
    },
    {
        "name": "East London Mosque",
        "url": "https://www.eastlondonmosque.org.uk/khutbahs",
        "country": "United Kingdom",
        "language": "English",
        "region": "Europe",
        "institution_type": "major diaspora mosque",
        "notes": "largest mosque in UK, reflects British Muslim perspective",
    },
    {
        "name": "Dar al-Ifta (Egypt)",
        "url": "https://www.dar-alifta.org/en",
        "country": "Egypt",
        "language": "Arabic",
        "region": "Middle East",
        "institution_type": "official fatwa house",
        "notes": "Egyptian state fatwa institution",
    },
]


def fetch_page(url, timeout=15):
    """fetch a web page, return text."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "text/html",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def extract_sermon_links(html, base_url):
    """extract sermon/article links from a page.

    generic approach: look for <a> tags with href containing
    sermon-related keywords or date patterns.
    """
    links = []
    # find all links
    pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)

    for match in pattern.finditer(html):
        href = match.group(1)
        text = re.sub(r'<[^>]+>', '', match.group(2)).strip()

        if not text or len(text) < 10:
            continue

        # resolve relative URLs
        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif not href.startswith("http"):
            continue

        # check if the link text or URL suggests a sermon/khutbah
        combined = f"{text} {href}".lower()
        sermon_indicators = ["khutbah", "sermon", "friday", "jumu", "hutbe",
                           "خطبة", "خطبه", "cuma"]

        is_sermon = any(ind in combined for ind in sermon_indicators)
        is_relevant = any(term in combined for term in SEARCH_TERMS)

        if is_sermon or is_relevant:
            links.append({"url": href, "title": text[:100]})

    return links


def fetch_sermon_text(url):
    """fetch sermon page and extract main text via trafilatura."""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False)
            if text and len(text) > 100:
                return text
    except Exception:
        pass

    # fallback: basic HTML text extraction
    html = fetch_page(url)
    if html:
        # strip tags, get text
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) > 200:
            return text[:5000]  # cap at 5000 chars

    return None


def main():
    existing_urls = set()
    existing_articles = []
    try:
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing_articles = json.load(f)
        existing_urls = {a["url"] for a in existing_articles}
    except FileNotFoundError:
        pass

    print(f"[sermons] scanning {len(SERMON_SOURCES)} religious institution archives...")

    new_articles = []
    stats = {"sources_scanned": 0, "sermons_found": 0, "fetched": 0,
             "relevant": 0, "added": 0, "errors": 0}

    for source in SERMON_SOURCES:
        name = source["name"]
        url = source["url"]
        country = source["country"]
        language = source["language"]

        print(f"\n  {name} ({country})...", end=" ", flush=True)
        stats["sources_scanned"] += 1

        html = fetch_page(url)
        if not html:
            print("FAILED (fetch)")
            stats["errors"] += 1
            time.sleep(2)
            continue

        # find sermon links
        links = extract_sermon_links(html, url)
        stats["sermons_found"] += len(links)

        if not links:
            print(f"no sermon links found")
            time.sleep(2)
            continue

        print(f"found {len(links)} links")

        added = 0
        for link in links[:MAX_PER_SOURCE]:
            sermon_url = link["url"]
            if sermon_url in existing_urls:
                continue

            print(f"    fetching: {link['title'][:50]}...", end=" ", flush=True)

            text = fetch_sermon_text(sermon_url)
            if not text:
                print("FAILED")
                stats["errors"] += 1
                continue
            stats["fetched"] += 1

            # check relevance
            if not any(term in text.lower() for term in SEARCH_TERMS):
                print("not relevant")
                continue
            stats["relevant"] += 1

            existing_urls.add(sermon_url)
            new_articles.append({
                "url": sermon_url,
                "title": link["title"],
                "seendate": "",  # sermons rarely have clear dates in metadata
                "sourcecountry": country,
                "sourcelang": language,
                "domain": source["name"].replace(" ", "_").lower(),
                "source": "sermon_archive",
                "tier": 3,
                "region": source.get("region", "unknown"),
                "institution_type": source.get("institution_type", ""),
                "text_chars": len(text),
            })
            added += 1
            stats["added"] += 1

            # cache text for pipeline
            url_hash = hashlib.md5(sermon_url.encode()).hexdigest()
            cache_path = os.path.join("cache", f"{url_hash}.txt")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)

            print(f"ok ({len(text)} chars)")
            time.sleep(1)

        time.sleep(2)

    if new_articles:
        merged = existing_articles + new_articles
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"[sermons] SUMMARY")
    print(f"  institutions scanned: {stats['sources_scanned']}")
    print(f"  sermon links found: {stats['sermons_found']}")
    print(f"  texts fetched: {stats['fetched']}")
    print(f"  relevant to event: {stats['relevant']}")
    print(f"  new articles added: {stats['added']}")
    print(f"  errors: {stats['errors']}")
    print(f"  total corpus now: {len(existing_articles) + len(new_articles)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
