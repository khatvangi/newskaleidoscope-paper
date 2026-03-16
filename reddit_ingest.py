#!/usr/bin/env python3
"""
reddit_ingest.py — vernacular discourse ingestion from Reddit.

captures how ordinary people in different countries discuss geopolitical events.
uses Reddit's public JSON API (no auth needed for public subreddits).
pulls top posts + top comments as the framing data.

IMPORTANT: label output as "vernacular online discourse" — not public opinion,
not representative. Anglophone bias is real and must be documented.

works for both CS1 (military) and CS2 (economic) events.
"""

import json
import os
import sys
import time
import hashlib
import urllib.request
import urllib.error
from datetime import datetime

OUTPUT_DIR = "sources/reddit"
CACHE_DIR = "cache"
USER_AGENT = "NewsKaleidoscope/0.1 (epistemic mapping research)"
MAX_POSTS_PER_SUB = 10
MAX_COMMENTS_PER_POST = 5
REQUEST_DELAY = 2.5  # reddit asks for 1 req/sec, we give headroom

# ── EVENT CONFIGURATIONS ──

EVENTS = {
    "cs1_iran": {
        "event_id": 2,
        "label": "CS1: Iran Strike",
        "queries": ["iran strike", "iran bombing", "iran nuclear attack", "US Iran war", "iran missile"],
        "subreddits": [
            # geopolitical discussion
            {"sub": "worldnews", "country": "International", "language": "English", "region": "Global"},
            {"sub": "geopolitics", "country": "International", "language": "English", "region": "Global"},
            # country-specific
            {"sub": "iran", "country": "Iran", "language": "English", "region": "Middle East"},
            {"sub": "Israel", "country": "Israel", "language": "English", "region": "Middle East"},
            {"sub": "arabs", "country": "Arab World", "language": "English", "region": "Middle East"},
            {"sub": "india", "country": "India", "language": "English", "region": "South Asia"},
            {"sub": "pakistan", "country": "Pakistan", "language": "English", "region": "South Asia"},
            {"sub": "europe", "country": "Europe", "language": "English", "region": "Europe"},
            {"sub": "de", "country": "Germany", "language": "German", "region": "Europe"},
            {"sub": "france", "country": "France", "language": "French", "region": "Europe"},
            {"sub": "unitedkingdom", "country": "United Kingdom", "language": "English", "region": "Europe"},
            {"sub": "canada", "country": "Canada", "language": "English", "region": "North America"},
            {"sub": "brasil", "country": "Brazil", "language": "Portuguese", "region": "Latin America"},
            {"sub": "Turkey", "country": "Turkey", "language": "English", "region": "Middle East"},
            {"sub": "China_irl", "country": "China", "language": "Chinese", "region": "East Asia"},
            {"sub": "korea", "country": "South Korea", "language": "English", "region": "East Asia"},
            {"sub": "Nigeria", "country": "Nigeria", "language": "English", "region": "Africa"},
            {"sub": "southafrica", "country": "South Africa", "language": "English", "region": "Africa"},
        ],
        # date filter: Feb 26 - Mar 6, 2026
        "date_start": 1772006400,  # approx 2026-02-26
        "date_end": 1772784000,    # approx 2026-03-06
    },
    "cs1ru_ukraine": {
        "event_id": 4,
        "label": "CS1-RU: Ukraine Invasion (2022)",
        "queries": ["russia ukraine invasion", "ukraine war", "ukraine attack", "putin ukraine", "zelensky"],
        "subreddits": [
            # global geopolitical
            {"sub": "worldnews", "country": "International", "language": "English", "region": "Global"},
            {"sub": "geopolitics", "country": "International", "language": "English", "region": "Global"},
            {"sub": "UkrainianConflict", "country": "International", "language": "English", "region": "Global"},
            {"sub": "CombatFootage", "country": "International", "language": "English", "region": "Global"},
            # directly involved
            {"sub": "ukraine", "country": "Ukraine", "language": "English", "region": "Eastern Europe"},
            {"sub": "russia", "country": "Russia", "language": "English", "region": "Eastern Europe"},
            {"sub": "AskARussian", "country": "Russia", "language": "English", "region": "Eastern Europe"},
            {"sub": "liberta", "country": "Russia", "language": "Russian", "region": "Eastern Europe"},
            # european
            {"sub": "europe", "country": "Europe", "language": "English", "region": "Europe"},
            {"sub": "de", "country": "Germany", "language": "German", "region": "Europe"},
            {"sub": "france", "country": "France", "language": "French", "region": "Europe"},
            {"sub": "unitedkingdom", "country": "United Kingdom", "language": "English", "region": "Europe"},
            {"sub": "Polska", "country": "Poland", "language": "Polish", "region": "Europe"},
            {"sub": "Romania", "country": "Romania", "language": "English", "region": "Europe"},
            # neighboring / affected
            {"sub": "Turkey", "country": "Turkey", "language": "English", "region": "Middle East"},
            {"sub": "india", "country": "India", "language": "English", "region": "South Asia"},
            {"sub": "China_irl", "country": "China", "language": "Chinese", "region": "East Asia"},
            {"sub": "korea", "country": "South Korea", "language": "English", "region": "East Asia"},
            # americas
            {"sub": "canada", "country": "Canada", "language": "English", "region": "North America"},
            {"sub": "politics", "country": "United States", "language": "English", "region": "North America"},
            {"sub": "brasil", "country": "Brazil", "language": "Portuguese", "region": "Latin America"},
            # africa
            {"sub": "Nigeria", "country": "Nigeria", "language": "English", "region": "Africa"},
            {"sub": "southafrica", "country": "South Africa", "language": "English", "region": "Africa"},
        ],
        # date filter: Feb 22 - Mar 5, 2022 (slightly wider to catch early/late posts)
        "date_start": 1645488000,   # 2022-02-22 00:00:00 UTC
        "date_end": 1646438400,     # 2022-03-05 00:00:00 UTC
    },
    "cs2_tariffs": {
        "event_id": 3,
        "label": "CS2: US Tariffs",
        "queries": ["tariff", "trade war", "liberation day tariff", "reciprocal tariff", "import duty"],
        "subreddits": [
            # economics/trade discussion
            {"sub": "economics", "country": "International", "language": "English", "region": "Global"},
            {"sub": "worldnews", "country": "International", "language": "English", "region": "Global"},
            {"sub": "geopolitics", "country": "International", "language": "English", "region": "Global"},
            {"sub": "trade", "country": "International", "language": "English", "region": "Global"},
            # most impacted countries
            {"sub": "China_irl", "country": "China", "language": "Chinese", "region": "East Asia"},
            {"sub": "VietNam", "country": "Vietnam", "language": "English", "region": "Southeast Asia"},
            {"sub": "Philippines", "country": "Philippines", "language": "English", "region": "Southeast Asia"},
            {"sub": "indonesia", "country": "Indonesia", "language": "English", "region": "Southeast Asia"},
            {"sub": "malaysia", "country": "Malaysia", "language": "English", "region": "Southeast Asia"},
            {"sub": "Thailand", "country": "Thailand", "language": "English", "region": "Southeast Asia"},
            {"sub": "india", "country": "India", "language": "English", "region": "South Asia"},
            {"sub": "bangladesh", "country": "Bangladesh", "language": "English", "region": "South Asia"},
            # western / retaliating countries
            {"sub": "canada", "country": "Canada", "language": "English", "region": "North America"},
            {"sub": "europe", "country": "Europe", "language": "English", "region": "Europe"},
            {"sub": "de", "country": "Germany", "language": "German", "region": "Europe"},
            {"sub": "france", "country": "France", "language": "French", "region": "Europe"},
            {"sub": "unitedkingdom", "country": "United Kingdom", "language": "English", "region": "Europe"},
            {"sub": "korea", "country": "South Korea", "language": "English", "region": "East Asia"},
            {"sub": "japan", "country": "Japan", "language": "English", "region": "East Asia"},
            {"sub": "taiwan", "country": "Taiwan", "language": "English", "region": "East Asia"},
            # latin america
            {"sub": "brasil", "country": "Brazil", "language": "Portuguese", "region": "Latin America"},
            {"sub": "mexico", "country": "Mexico", "language": "Spanish", "region": "Latin America"},
            {"sub": "argentina", "country": "Argentina", "language": "Spanish", "region": "Latin America"},
            # africa
            {"sub": "Nigeria", "country": "Nigeria", "language": "English", "region": "Africa"},
            {"sub": "southafrica", "country": "South Africa", "language": "English", "region": "Africa"},
            {"sub": "Kenya", "country": "Kenya", "language": "English", "region": "Africa"},
            # US domestic reaction
            {"sub": "politics", "country": "United States", "language": "English", "region": "North America"},
            {"sub": "Conservative", "country": "United States", "language": "English", "region": "North America"},
        ],
        # CS2 windows (unix timestamps)
        "windows": {
            "w1_announcement": {"start": 1743552000, "end": 1744070400},   # Apr 2-8, 2025
            "w2_pause":        {"start": 1744156800, "end": 1744675200},   # Apr 9-16, 2025
            "w3_reimposition": {"start": 1746057600, "end": 1753920000},   # May-Jul 2025
            "w4_retaliation":  {"start": 1754006400, "end": 1761868800},   # Aug-Oct 2025
            "w5_retrospective":{"start": 1772006400, "end": 1772784000},   # Feb 24 - Mar 6, 2026
        },
    },
}


def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)


def reddit_get(url, retries=3):
    """fetch JSON from Reddit's public API with rate limiting."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 10 * (attempt + 1)
                print(f"      rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif e.code == 403:
                print(f"      403 forbidden (private sub?)")
                return None
            else:
                print(f"      HTTP {e.code}")
                return None
        except Exception as e:
            print(f"      error: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return None


def search_subreddit(subreddit, query, sort="relevance", limit=25):
    """search a subreddit for posts matching query."""
    encoded_q = urllib.parse.quote(query)
    url = f"https://www.reddit.com/r/{subreddit}/search.json?q={encoded_q}&restrict_sr=1&sort={sort}&limit={limit}&t=all"
    time.sleep(REQUEST_DELAY)
    return reddit_get(url)


def fetch_comments(subreddit, post_id, limit=MAX_COMMENTS_PER_POST):
    """fetch top comments for a post."""
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json?sort=top&limit={limit}"
    time.sleep(REQUEST_DELAY)
    data = reddit_get(url)
    if not data or len(data) < 2:
        return []

    comments = []
    for child in data[1].get("data", {}).get("children", []):
        if child.get("kind") != "t1":
            continue
        cdata = child.get("data", {})
        body = cdata.get("body", "").strip()
        if body and body != "[deleted]" and body != "[removed]" and len(body) > 20:
            comments.append({
                "body": body[:2000],  # cap comment length
                "score": cdata.get("score", 0),
                "created_utc": cdata.get("created_utc", 0),
            })
    return comments[:limit]


def filter_by_date(posts, date_start, date_end):
    """filter posts by creation timestamp."""
    return [p for p in posts if date_start <= p.get("created_utc", 0) <= date_end]


def ingest_event(event_key, window_filter=None):
    """ingest Reddit posts for an event configuration."""
    cfg = EVENTS[event_key]
    label = cfg["label"]
    event_id = cfg["event_id"]
    queries = cfg["queries"]
    subreddits = cfg["subreddits"]

    print(f"\n{'='*60}")
    print(f"  REDDIT INGESTION: {label}")
    print(f"  {len(subreddits)} subreddits × {len(queries)} queries")
    print(f"{'='*60}")

    all_articles = []
    seen_ids = set()
    stats = {"subs_scanned": 0, "posts_found": 0, "posts_with_comments": 0,
             "total_comments": 0, "errors": 0}

    for sub_cfg in subreddits:
        sub = sub_cfg["sub"]
        country = sub_cfg["country"]
        language = sub_cfg["language"]
        region = sub_cfg["region"]

        print(f"\n  r/{sub} ({country})...", flush=True)
        stats["subs_scanned"] += 1
        sub_posts = []

        for query in queries:
            print(f"    query: '{query}'...", end=" ", flush=True)
            data = search_subreddit(sub, query)
            if not data:
                print("FAILED")
                stats["errors"] += 1
                continue

            children = data.get("data", {}).get("children", [])
            new = 0
            for child in children:
                if child.get("kind") != "t3":
                    continue
                pdata = child.get("data", {})
                post_id = pdata.get("id", "")
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                # basic relevance check — must have some content
                title = pdata.get("title", "")
                selftext = pdata.get("selftext", "")
                score = pdata.get("score", 0)
                if score < 2:  # skip very low-engagement posts
                    continue

                sub_posts.append({
                    "id": post_id,
                    "title": title,
                    "selftext": selftext[:3000],
                    "score": score,
                    "num_comments": pdata.get("num_comments", 0),
                    "created_utc": pdata.get("created_utc", 0),
                    "permalink": pdata.get("permalink", ""),
                    "subreddit": sub,
                    "url": f"https://www.reddit.com{pdata.get('permalink', '')}",
                })
                new += 1
            print(f"{new} posts")

        # date filter if applicable
        if event_key == "cs2_tariffs" and window_filter:
            windows = cfg.get("windows", {})
            if window_filter in windows:
                w = windows[window_filter]
                before = len(sub_posts)
                sub_posts = filter_by_date(sub_posts, w["start"], w["end"])
                print(f"    date filter ({window_filter}): {before} → {len(sub_posts)}")
        elif "date_start" in cfg:
            before = len(sub_posts)
            sub_posts = filter_by_date(sub_posts, cfg["date_start"], cfg["date_end"])
            if before != len(sub_posts):
                print(f"    date filter: {before} → {len(sub_posts)}")

        # sort by score, take top N
        sub_posts.sort(key=lambda p: p["score"], reverse=True)
        sub_posts = sub_posts[:MAX_POSTS_PER_SUB]

        # fetch comments for top posts
        for post in sub_posts:
            if post["num_comments"] > 0:
                print(f"    fetching comments for: {post['title'][:50]}...", end=" ", flush=True)
                comments = fetch_comments(sub, post["id"])
                post["top_comments"] = comments
                stats["total_comments"] += len(comments)
                if comments:
                    stats["posts_with_comments"] += 1
                print(f"{len(comments)} comments")

        # convert to article format
        for post in sub_posts:
            # build text: title + selftext + top comments
            text_parts = [post["title"]]
            if post["selftext"]:
                text_parts.append(post["selftext"])
            for c in post.get("top_comments", []):
                text_parts.append(f"[Comment, score {c['score']}]: {c['body']}")
            full_text = "\n\n".join(text_parts)

            # cache the text
            url_hash = hashlib.md5(post["url"].encode()).hexdigest()
            cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(full_text)

            created_dt = datetime.utcfromtimestamp(post["created_utc"]).strftime("%Y%m%d%H%M%S")

            all_articles.append({
                "url": post["url"],
                "title": post["title"],
                "seendate": created_dt,
                "sourcecountry": country,
                "sourcelang": language,
                "domain": f"reddit.com/r/{sub}",
                "source": "reddit",
                "tier": 3,
                "region": region,
                "event_id": event_id,
                "reddit_score": post["score"],
                "reddit_comments": post["num_comments"],
                "comment_count_captured": len(post.get("top_comments", [])),
                "text_chars": len(full_text),
            })
            stats["posts_found"] += 1

    # save output
    outfile = os.path.join(OUTPUT_DIR, f"{event_key}.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)

    # summary
    print(f"\n{'='*60}")
    print(f"  REDDIT SUMMARY: {label}")
    print(f"  subreddits scanned: {stats['subs_scanned']}")
    print(f"  posts captured: {stats['posts_found']}")
    print(f"  posts with comments: {stats['posts_with_comments']}")
    print(f"  total comments: {stats['total_comments']}")
    print(f"  errors: {stats['errors']}")
    print(f"  output: {outfile}")

    # country breakdown
    by_country = {}
    for a in all_articles:
        c = a["sourcecountry"]
        by_country[c] = by_country.get(c, 0) + 1
    print(f"  countries ({len(by_country)}):")
    for c in sorted(by_country.keys()):
        print(f"    {c}: {by_country[c]}")
    print(f"{'='*60}")

    return all_articles


def main():
    ensure_dirs()

    if len(sys.argv) < 2:
        print("usage: python3 reddit_ingest.py <cs1_iran|cs2_tariffs> [window]")
        print("  examples:")
        print("    python3 reddit_ingest.py cs1_iran")
        print("    python3 reddit_ingest.py cs2_tariffs")
        print("    python3 reddit_ingest.py cs2_tariffs w1_announcement")
        sys.exit(1)

    event_key = sys.argv[1]
    if event_key not in EVENTS:
        print(f"unknown event: {event_key}")
        print(f"valid events: {', '.join(EVENTS.keys())}")
        sys.exit(1)

    window = sys.argv[2] if len(sys.argv) > 2 else None
    ingest_event(event_key, window_filter=window)


if __name__ == "__main__":
    main()
