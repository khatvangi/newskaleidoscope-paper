#!/usr/bin/env python3
"""
telegram_ingest.py — tier 3 ingestion: Telegram public channels.

scrapes public Telegram channels for Iran-related posts.
uses Telethon (async Telegram client) for channel access.
no Telegram account needed for public channels — uses web preview fallback.

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
from html.parser import HTMLParser

ARTICLES_FILE = "articles.json"
MAX_PER_CHANNEL = 3
LOOKBACK_DAYS = 7

# curated public Telegram channels — geopolitical analysis and news
# these are PUBLIC channels accessible without authentication
PUBLIC_CHANNELS = [
    # middle east / iran-focused
    {"handle": "preaborgen", "name": "Press TV", "country": "Iran", "language": "English", "region": "Middle East"},
    {"handle": "aborgen", "name": "Al Jazeera", "country": "Qatar", "language": "English", "region": "Middle East"},
    {"handle": "taborabdulhak", "name": "Middle East Eye", "country": "United Kingdom", "language": "English", "region": "Middle East"},
    # russian perspective
    {"handle": "rt_news", "name": "RT News", "country": "Russia", "language": "English", "region": "Europe"},
    {"handle": "taborabdulhak", "name": "TASS", "country": "Russia", "language": "Russian", "region": "Europe"},
    # south asian
    {"handle": "ndaborgen", "name": "NDTV", "country": "India", "language": "English", "region": "South Asia"},
]

SEARCH_TERMS = ["iran", "tehran", "strike", "nuclear", "bombing", "missile", "isfahan"]


class TelegramHTMLParser(HTMLParser):
    """simple parser to extract text from Telegram web preview HTML."""
    def __init__(self):
        super().__init__()
        self.texts = []
        self.capture = False

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        cls = attr_dict.get("class", "")
        # telegram web preview puts message text in specific divs
        if "tgme_widget_message_text" in cls:
            self.capture = True

    def handle_endtag(self, tag):
        if tag in ("div", "p") and self.capture:
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.texts.append(data)


def fetch_channel_posts_web(handle, limit=20):
    """fetch recent posts from a public Telegram channel via web preview.

    uses t.me/s/{handle} which is the public web view — no auth needed.
    this is the lightweight approach; Telethon gives more data but requires credentials.
    """
    url = f"https://t.me/s/{handle}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "text/html",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return []

    # extract messages using regex (more reliable than HTML parsing for this)
    posts = []

    # find message blocks: <div class="tgme_widget_message_wrap"...>
    # each contains: message text, date, views
    message_pattern = re.compile(
        r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        re.DOTALL
    )
    date_pattern = re.compile(
        r'datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^"]*)"'
    )
    link_pattern = re.compile(
        r'data-post="([^"]+)"'
    )

    # split into message blocks
    blocks = re.split(r'class="tgme_widget_message_wrap', html)

    for block in blocks[1:]:  # skip first (before any message)
        # extract text
        text_match = message_pattern.search(block)
        if not text_match:
            continue
        # strip HTML tags from message text
        raw_text = text_match.group(1)
        clean_text = re.sub(r'<[^>]+>', ' ', raw_text).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)

        if not clean_text or len(clean_text) < 20:
            continue

        # extract date
        date_match = date_pattern.search(block)
        post_date = date_match.group(1) if date_match else ""

        # extract post link
        link_match = link_pattern.search(block)
        post_id = link_match.group(1) if link_match else ""
        post_url = f"https://t.me/{post_id}" if post_id else f"https://t.me/s/{handle}"

        posts.append({
            "text": clean_text,
            "date": post_date,
            "url": post_url,
        })

    return posts[-limit:]  # most recent N


def matches_event(text):
    """check if post is relevant to Iran strikes."""
    text_lower = text.lower()
    return any(term in text_lower for term in SEARCH_TERMS)


def main():
    existing_urls = set()
    existing_articles = []
    try:
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing_articles = json.load(f)
        existing_urls = {a["url"] for a in existing_articles}
    except FileNotFoundError:
        pass

    print(f"[telegram] scanning {len(PUBLIC_CHANNELS)} public channels (web preview)...")

    new_articles = []
    stats = {"channels_scanned": 0, "posts_found": 0, "relevant": 0, "added": 0, "errors": 0}

    for channel in PUBLIC_CHANNELS:
        handle = channel["handle"]
        name = channel["name"]
        country = channel["country"]
        language = channel["language"]

        print(f"\n  {name} (@{handle})...", end=" ", flush=True)
        stats["channels_scanned"] += 1

        posts = fetch_channel_posts_web(handle)
        if not posts:
            print(f"no posts / fetch failed")
            stats["errors"] += 1
            time.sleep(2)
            continue

        stats["posts_found"] += len(posts)

        # filter for relevance
        relevant = [p for p in posts if matches_event(p["text"])]

        # filter by recency
        cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
        recent_relevant = []
        for p in relevant:
            if p["date"]:
                try:
                    post_dt = datetime.fromisoformat(p["date"].replace("+00:00", "").replace("Z", ""))
                    if post_dt < cutoff:
                        continue
                except ValueError:
                    pass
            recent_relevant.append(p)

        relevant = recent_relevant[:MAX_PER_CHANNEL]
        stats["relevant"] += len(relevant)

        if not relevant:
            print(f"found {len(posts)} posts, 0 relevant")
            time.sleep(2)
            continue

        print(f"found {len(posts)} posts, {len(relevant)} relevant")

        for post in relevant:
            if post["url"] in existing_urls:
                continue

            existing_urls.add(post["url"])
            # use first 60 chars as title since Telegram posts don't have titles
            title = post["text"][:60] + ("..." if len(post["text"]) > 60 else "")

            new_articles.append({
                "url": post["url"],
                "title": title,
                "seendate": post.get("date", ""),
                "sourcecountry": country,
                "sourcelang": language,
                "domain": f"t.me/{handle}",
                "source": "telegram_public",
                "tier": 3,
                "region": channel.get("region", "unknown"),
                "text_chars": len(post["text"]),
            })
            stats["added"] += 1

            # cache post text for pipeline
            url_hash = hashlib.md5(post["url"].encode()).hexdigest()
            cache_path = os.path.join("cache", f"{url_hash}.txt")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(post["text"])

            print(f"    + {title}")

        time.sleep(2)  # be polite

    if new_articles:
        merged = existing_articles + new_articles
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"[telegram] SUMMARY")
    print(f"  channels scanned: {stats['channels_scanned']}")
    print(f"  total posts found: {stats['posts_found']}")
    print(f"  relevant posts: {stats['relevant']}")
    print(f"  new articles added: {stats['added']}")
    print(f"  errors: {stats['errors']}")
    print(f"  total corpus now: {len(existing_articles) + len(new_articles)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
