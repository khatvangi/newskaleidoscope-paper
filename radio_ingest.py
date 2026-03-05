#!/usr/bin/env python3
"""
radio_ingest.py — tier 3 ingestion: international radio transcript crawlers.

scrapes published transcripts from international broadcast services.
these services (BBC World Service, VOA, RFI, DW) produce broadcast
content in dozens of languages — their websites often publish transcripts
or text versions of radio segments.

unlike podcast_ingest which downloads audio and transcribes, this
targets text already published on the broadcaster's website.

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

ARTICLES_FILE = "articles.json"
MAX_PER_SOURCE = 3
LOOKBACK_DAYS = 7

SEARCH_TERMS = ["iran", "tehran", "strike", "nuclear", "bombing", "missile"]

# international broadcasters with web-published content
# these publish articles/transcripts of their radio content online
RADIO_SOURCES = [
    # BBC World Service — publishes articles in 40+ languages
    {
        "name": "BBC Persian",
        "search_url": "https://www.bbc.com/persian/topics/c1ez1kz8x9zt",
        "country": "United Kingdom/Iran diaspora",
        "language": "Persian",
        "region": "Middle East",
        "notes": "BBC's Farsi service — major source for Iranian diaspora",
    },
    {
        "name": "BBC Arabic",
        "search_url": "https://www.bbc.com/arabic/topics/c1ez1kz80v5t",
        "country": "United Kingdom/Arab world",
        "language": "Arabic",
        "region": "Middle East",
        "notes": "BBC's Arabic service — wide reach across MENA",
    },
    {
        "name": "BBC Turkish",
        "search_url": "https://www.bbc.com/turkce/topics/c1ez1kz81x7t",
        "country": "United Kingdom/Turkey",
        "language": "Turkish",
        "region": "Middle East",
        "notes": "BBC's Turkish service",
    },
    # VOA — Voice of America in multiple languages
    {
        "name": "VOA Persian",
        "search_url": "https://ir.voanews.com/z/599",
        "country": "United States/Iran diaspora",
        "language": "Persian",
        "region": "North America",
        "notes": "US government-funded but editorially independent",
    },
    # RFI — Radio France Internationale
    {
        "name": "RFI Persian",
        "search_url": "https://www.rfi.fr/fa/",
        "country": "France/Iran diaspora",
        "language": "Persian",
        "region": "Europe",
        "notes": "French international radio, Persian service",
    },
    # DW — Deutsche Welle
    {
        "name": "DW Persian",
        "search_url": "https://www.dw.com/fa-ir/",
        "country": "Germany/Iran diaspora",
        "language": "Persian",
        "region": "Europe",
        "notes": "German international broadcaster, Persian service",
    },
    {
        "name": "DW Arabic",
        "search_url": "https://www.dw.com/ar/",
        "country": "Germany/Arab world",
        "language": "Arabic",
        "region": "Europe",
        "notes": "German international broadcaster, Arabic service",
    },
]


def fetch_page(url, timeout=15):
    """fetch a web page."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8,fa;q=0.7",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def extract_article_links(html, base_url):
    """extract article links from a news page."""
    links = []
    # find all <a> tags with href
    pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)

    from urllib.parse import urlparse, urljoin
    parsed_base = urlparse(base_url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

    for match in pattern.finditer(html):
        href = match.group(1)
        text = re.sub(r'<[^>]+>', '', match.group(2)).strip()

        if not text or len(text) < 15:
            continue

        # resolve relative URLs
        if href.startswith("/"):
            href = f"{base_domain}{href}"
        elif not href.startswith("http"):
            continue

        # must be same domain (avoid external links)
        if parsed_base.netloc not in href:
            continue

        # skip navigation, category, and non-article links
        skip_patterns = ["/topics/", "/programmes/", "/help/", "/about/",
                        "/contact/", "#", "javascript:", "/live/"]
        if any(pat in href.lower() for pat in skip_patterns):
            continue

        # check relevance to event
        combined = f"{text}".lower()
        if any(term in combined for term in SEARCH_TERMS):
            links.append({"url": href, "title": text[:100]})

    # deduplicate by URL
    seen = set()
    unique = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique.append(link)

    return unique


def fetch_article_text(url):
    """fetch and extract article text."""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False)
            if text and len(text) > 100:
                return text
    except Exception:
        pass

    # fallback: basic extraction
    html = fetch_page(url)
    if html:
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) > 200:
            return text[:5000]

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

    print(f"[radio] scanning {len(RADIO_SOURCES)} international broadcast services...")

    new_articles = []
    stats = {"sources_scanned": 0, "links_found": 0, "fetched": 0,
             "added": 0, "errors": 0}

    for source in RADIO_SOURCES:
        name = source["name"]
        url = source["search_url"]
        country = source["country"]
        language = source["language"]

        print(f"\n  {name}...", end=" ", flush=True)
        stats["sources_scanned"] += 1

        html = fetch_page(url)
        if not html:
            print("FAILED (fetch)")
            stats["errors"] += 1
            time.sleep(2)
            continue

        links = extract_article_links(html, url)
        stats["links_found"] += len(links)

        if not links:
            print(f"no relevant links found")
            time.sleep(2)
            continue

        print(f"found {len(links)} relevant links")

        added = 0
        for link in links[:MAX_PER_SOURCE]:
            article_url = link["url"]
            if article_url in existing_urls:
                continue

            print(f"    fetching: {link['title'][:50]}...", end=" ", flush=True)

            text = fetch_article_text(article_url)
            if not text:
                print("FAILED")
                stats["errors"] += 1
                continue
            stats["fetched"] += 1

            existing_urls.add(article_url)
            new_articles.append({
                "url": article_url,
                "title": link["title"],
                "seendate": "",
                "sourcecountry": country,
                "sourcelang": language,
                "domain": name.replace(" ", "_").lower(),
                "source": "radio_transcript",
                "tier": 3,
                "region": source.get("region", "unknown"),
                "text_chars": len(text),
            })
            added += 1
            stats["added"] += 1

            # cache text for pipeline
            url_hash = hashlib.md5(article_url.encode()).hexdigest()
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
    print(f"[radio] SUMMARY")
    print(f"  services scanned: {stats['sources_scanned']}")
    print(f"  relevant links found: {stats['links_found']}")
    print(f"  texts fetched: {stats['fetched']}")
    print(f"  new articles added: {stats['added']}")
    print(f"  errors: {stats['errors']}")
    print(f"  total corpus now: {len(existing_articles) + len(new_articles)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
