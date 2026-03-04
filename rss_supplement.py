#!/usr/bin/env python3
"""
rss_supplement.py — pull articles directly from curated outlets via RSS.
fills the gap GDELT leaves: GDELT finds random web sources, this targets
the specific flagship outlets we actually want to analyze.

merges results into articles.json alongside GDELT articles.
"""

import json
import re
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

OUTLETS_FILE = "outlets.json"
ARTICLES_FILE = "articles.json"
MAX_PER_OUTLET = 2  # max articles per outlet to keep corpus balanced

# search terms to filter RSS items (case-insensitive)
SEARCH_TERMS = ["iran", "tehran", "strike", "nuclear", "bombing", "missile"]


def fetch_rss(url, timeout=15):
    """fetch and parse RSS feed XML."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "NewsKaleidoscope/0.1",
        "Accept": "application/rss+xml, application/xml, text/xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None


def parse_rss_items(xml_text):
    """extract items from RSS/Atom feed."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # handle both RSS 2.0 and Atom
    # RSS 2.0: <channel><item>
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # try RSS 2.0
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pubdate = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if title and link:
            items.append({"title": title, "url": link, "pubdate": pubdate, "description": desc})

    # try Atom
    if not items:
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href", "") if link_el is not None else ""
            pubdate = (entry.findtext("{http://www.w3.org/2005/Atom}published") or
                       entry.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
            desc = (entry.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
            if title and link:
                items.append({"title": title, "url": link, "pubdate": pubdate, "description": desc})

    return items


def matches_event(item):
    """check if RSS item is relevant to the Iran strikes event."""
    text = f"{item['title']} {item['description']}".lower()
    return any(term in text for term in SEARCH_TERMS)


def main():
    with open(OUTLETS_FILE, "r", encoding="utf-8") as f:
        outlets = json.load(f)

    # load existing articles to avoid duplicates
    existing_urls = set()
    existing_articles = []
    try:
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing_articles = json.load(f)
        existing_urls = {a["url"] for a in existing_articles}
    except FileNotFoundError:
        pass

    rss_outlets = [o for o in outlets if o.get("rss_url")]
    print(f"[rss] scanning {len(rss_outlets)} outlets with RSS feeds...")

    new_articles = []
    skipped = 0
    errors = 0

    for outlet in rss_outlets:
        name = outlet["name"]
        rss_url = outlet["rss_url"]
        domain = outlet["domain"]
        country = outlet["country"]
        language = outlet["language"]

        print(f"  {name} ({domain})...", end=" ", flush=True)

        xml_text = fetch_rss(rss_url)
        if not xml_text:
            print("FAILED")
            errors += 1
            # respect rate limits between requests
            time.sleep(1)
            continue

        items = parse_rss_items(xml_text)
        relevant = [it for it in items if matches_event(it)]

        # cap per outlet
        relevant = relevant[:MAX_PER_OUTLET]

        added = 0
        for item in relevant:
            if item["url"] in existing_urls:
                continue
            existing_urls.add(item["url"])
            new_articles.append({
                "url": item["url"],
                "title": item["title"],
                "seendate": item.get("pubdate", ""),
                "sourcecountry": country,
                "sourcelang": language,
                "domain": domain,
                "source": "rss_curated",  # flag that this came from curated RSS, not GDELT
            })
            added += 1

        if relevant:
            print(f"found {len(relevant)}, added {added}")
        else:
            print("no matches")
            skipped += 1

        # be polite between requests
        time.sleep(1)

    # merge with existing
    merged = existing_articles + new_articles

    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"[rss] SUMMARY")
    print(f"  outlets scanned: {len(rss_outlets)}")
    print(f"  new articles added: {len(new_articles)}")
    print(f"  outlets with no matches: {skipped}")
    print(f"  fetch errors: {errors}")
    print(f"  total articles now: {len(merged)}")

    if new_articles:
        print(f"\n  new articles from:")
        for a in new_articles:
            print(f"    {a['domain']:30s} {a['sourcelang']:10s} {a['title'][:50]}")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
