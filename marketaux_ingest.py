#!/usr/bin/env python3
"""
marketaux_ingest.py — financial news ingestion via MarketAux API.

adds a distinct epistemic layer: how financial markets frame tariffs.
ticker-tagged articles reveal which economic actors are centered in coverage.

free tier: 100 requests/day, 3 articles/request = ~300 articles/day.

usage:
  python3 marketaux_ingest.py cs2_tariffs
  python3 marketaux_ingest.py cs2_tariffs --window w1
"""

import json
import os
import sys
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

API_BASE = "https://api.marketaux.com/v1/news/all"
OUTPUT_DIR = "sources/marketaux"
CACHE_DIR = "cache"
REQUEST_DELAY = 1.0

API_KEY = os.environ.get("MARKETAUX_API_KEY", "")

# free tier returns max 3 per request — need pagination
MAX_PER_PAGE = 3

# CS2 tariff windows with date ranges
WINDOWS = {
    "w1": {"label": "Announcement Shock", "published_after": "2025-04-02", "published_before": "2025-04-09"},
    "w2": {"label": "90-Day Pause", "published_after": "2025-04-09", "published_before": "2025-04-17"},
    "w3": {"label": "Reimposition", "published_after": "2025-05-01", "published_before": "2025-08-01"},
    "w4": {"label": "Retaliation", "published_after": "2025-08-01", "published_before": "2025-11-01"},
    "w5": {"label": "Retrospective", "published_after": "2026-02-24", "published_before": "2026-03-07"},
}

# search terms that capture financial framing of tariffs
QUERIES = [
    "tariff trade war",
    "tariff impact stocks",
    "reciprocal tariff market",
    "liberation day tariff",
    "tariff supply chain",
]

# countries with major financial press
FINANCIAL_COUNTRIES = "us,gb,de,fr,jp,cn,in,kr,au,ca,sg,hk,br,za"


def api_call(params):
    """make MarketAux API call. returns parsed JSON or None."""
    params["api_token"] = API_KEY
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f" rate limited (429)")
        elif e.code == 402:
            print(f" quota exhausted")
        else:
            print(f" HTTP {e.code}")
        return None
    except Exception as e:
        print(f" error: {e}")
        return None


def fetch_window(query, window_cfg, pages=10):
    """fetch articles for a query within a time window, paginating."""
    all_articles = []
    seen_urls = set()

    for page in range(1, pages + 1):
        params = {
            "search": query,
            "published_after": window_cfg["published_after"] + "T00:00",
            "published_before": window_cfg["published_before"] + "T00:00",
            "limit": str(MAX_PER_PAGE),
            "page": str(page),
            "sort": "relevance_score",
        }

        time.sleep(REQUEST_DELAY)
        data = api_call(params)
        if not data:
            break

        articles = data.get("data", [])
        if not articles:
            break

        for art in articles:
            url = art.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_articles.append(art)

        # check if more pages exist
        meta = data.get("meta", {})
        if page >= meta.get("found", 0) / MAX_PER_PAGE:
            break

    return all_articles


def normalize_article(art, window_id):
    """convert MarketAux article to our standard format with financial metadata."""
    url = art.get("url", "")
    title = art.get("title", "")
    description = art.get("description", "")
    snippet = art.get("snippet", "")
    source = art.get("source", "")
    language = art.get("language", "en")
    pub_date = art.get("published_at", "")

    # extract entities and tickers
    entities = art.get("entities", [])
    tickers = []
    industries = []
    for ent in entities:
        sym = ent.get("symbol", "")
        if sym:
            tickers.append(sym)
        ind = ent.get("industry", "")
        if ind and ind not in industries:
            industries.append(ind)

    # cache text
    text = description or snippet or ""
    if url and text:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
        if not os.path.exists(cache_path):
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(f"{title}\n\n{text}")

    # seendate
    seendate = ""
    if pub_date:
        try:
            dt = datetime.strptime(pub_date[:19], "%Y-%m-%dT%H:%M:%S")
            seendate = dt.strftime("%Y%m%d%H%M%S")
        except ValueError:
            pass

    # domain
    domain = ""
    if url:
        try:
            domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        except Exception:
            pass

    return {
        "url": url,
        "title": title,
        "seendate": seendate,
        "sourcelang": language,
        "domain": domain,
        "source": "marketaux",
        "source_name": source,
        "tier": 1,
        "event_id": 3,
        "window": window_id,
        "text_chars": len(text),
        # financial metadata — unique to this source
        "tickers": tickers,
        "industries": industries,
        "entity_count": len(entities),
    }


def ingest(window_filter=None):
    """ingest financial tariff articles."""
    if not API_KEY:
        print("ERROR: MARKETAUX_API_KEY not set")
        sys.exit(1)

    windows = WINDOWS
    if window_filter:
        if window_filter in WINDOWS:
            windows = {window_filter: WINDOWS[window_filter]}
        else:
            print(f"unknown window: {window_filter}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  MARKETAUX INGESTION: CS2 Tariffs (Financial Layer)")
    print(f"  {len(windows)} windows x {len(QUERIES)} queries")
    print(f"{'='*60}")

    all_articles = []
    seen_urls = set()
    api_calls = 0

    for wid, wcfg in windows.items():
        print(f"\n  {wcfg['label']} ({wid}):", flush=True)
        window_articles = 0

        for query in QUERIES:
            print(f"    '{query}'...", end=" ", flush=True)
            # fetch up to 5 pages (15 articles) per query per window
            articles = fetch_window(query, wcfg, pages=5)
            api_calls += 5  # approximate

            new = 0
            for art in articles:
                normalized = normalize_article(art, wid)
                if normalized["url"] and normalized["url"] not in seen_urls:
                    seen_urls.add(normalized["url"])
                    all_articles.append(normalized)
                    new += 1
                    window_articles += 1

            print(f"{new} articles")

        print(f"    window total: {window_articles}")

    # save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    suffix = f"_{window_filter}" if window_filter else ""
    outfile = os.path.join(OUTPUT_DIR, f"cs2_tariffs{suffix}.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)

    # summary
    print(f"\n{'='*60}")
    print(f"  MARKETAUX SUMMARY")
    print(f"  articles: {len(all_articles)}")
    print(f"  API calls: ~{api_calls}")
    print(f"  output: {outfile}")

    # ticker frequency — which companies are most mentioned
    ticker_counts = {}
    for a in all_articles:
        for t in a.get("tickers", []):
            ticker_counts[t] = ticker_counts.get(t, 0) + 1
    if ticker_counts:
        print(f"  top tickers ({len(ticker_counts)} total):")
        for t, c in sorted(ticker_counts.items(), key=lambda x: -x[1])[:15]:
            print(f"    {t}: {c}")

    # industry breakdown
    ind_counts = {}
    for a in all_articles:
        for ind in a.get("industries", []):
            ind_counts[ind] = ind_counts.get(ind, 0) + 1
    if ind_counts:
        print(f"  industries ({len(ind_counts)}):")
        for ind, c in sorted(ind_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"    {ind}: {c}")

    # source breakdown
    by_source = {}
    for a in all_articles:
        s = a.get("source_name", "")
        by_source[s] = by_source.get(s, 0) + 1
    print(f"  sources ({len(by_source)}):")
    for s, c in sorted(by_source.items(), key=lambda x: -x[1])[:10]:
        print(f"    {s}: {c}")

    print(f"{'='*60}")
    return all_articles


def main():
    if len(sys.argv) < 2:
        print("usage: python3 marketaux_ingest.py cs2_tariffs [--window w1]")
        sys.exit(1)

    window_filter = None
    if "--window" in sys.argv:
        idx = sys.argv.index("--window")
        if idx + 1 < len(sys.argv):
            window_filter = sys.argv[idx + 1]

    ingest(window_filter=window_filter)


if __name__ == "__main__":
    main()
