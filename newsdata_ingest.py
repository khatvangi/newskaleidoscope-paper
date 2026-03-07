#!/usr/bin/env python3
"""
newsdata_ingest.py — multilingual news ingestion via NewsData.io API.

fills the EU-language gap that GDELT misses: French, German, Spanish, Italian,
Portuguese, Dutch, Polish, Swedish, Danish, Greek, Czech, Romanian, etc.

free tier: 200 credits/day (1 credit = 1 API call, returns up to 50 articles).
so 200 calls * 50 articles = up to 10,000 articles/day theoretically.

API docs: https://newsdata.io/documentation

usage:
  python3 newsdata_ingest.py cs2_tariffs              # all EU languages
  python3 newsdata_ingest.py cs2_tariffs --lang fr     # french only
  python3 newsdata_ingest.py cs1_iran                  # iran event
  python3 newsdata_ingest.py cs2_tariffs --backfill    # fill gaps in existing corpus
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

# free tier: /news = 48h lookback, /latest = real-time, /archive = paid only
API_NEWS = "https://newsdata.io/api/1/news"
API_LATEST = "https://newsdata.io/api/1/latest"
OUTPUT_DIR = "sources/newsdata"
CACHE_DIR = "cache"
REQUEST_DELAY = 1.0  # be polite

# get API key from environment
API_KEY = os.environ.get("NEWSDATA_API_KEY", "")

# ── EU + global language configs ──────────────────────────────────

# newsdata.io language codes (ISO 639-1)
EU_LANGUAGES = {
    "fr": {"name": "French", "country": "France", "region": "Europe"},
    "de": {"name": "German", "country": "Germany", "region": "Europe"},
    "es": {"name": "Spanish", "country": "Spain", "region": "Europe"},
    "it": {"name": "Italian", "country": "Italy", "region": "Europe"},
    "pt": {"name": "Portuguese", "country": "Portugal", "region": "Europe"},
    "nl": {"name": "Dutch", "country": "Netherlands", "region": "Europe"},
    "pl": {"name": "Polish", "country": "Poland", "region": "Europe"},
    "sv": {"name": "Swedish", "country": "Sweden", "region": "Europe"},
    "da": {"name": "Danish", "country": "Denmark", "region": "Europe"},
    "el": {"name": "Greek", "country": "Greece", "region": "Europe"},
    "cs": {"name": "Czech", "country": "Czech Republic", "region": "Europe"},
    "ro": {"name": "Romanian", "country": "Romania", "region": "Europe"},
    "hu": {"name": "Hungarian", "country": "Hungary", "region": "Europe"},
    "fi": {"name": "Finnish", "country": "Finland", "region": "Europe"},
    "bg": {"name": "Bulgarian", "country": "Bulgaria", "region": "Europe"},
    "hr": {"name": "Croatian", "country": "Croatia", "region": "Europe"},
    "sk": {"name": "Slovak", "country": "Slovakia", "region": "Europe"},
    "sl": {"name": "Slovenian", "country": "Slovenia", "region": "Europe"},
    "lt": {"name": "Lithuanian", "country": "Lithuania", "region": "Europe"},
    "lv": {"name": "Latvian", "country": "Latvia", "region": "Europe"},
    "et": {"name": "Estonian", "country": "Estonia", "region": "Europe"},
}

# non-EU languages to also target for global coverage
GLOBAL_LANGUAGES = {
    "ar": {"name": "Arabic", "country": "International", "region": "Middle East"},
    "hi": {"name": "Hindi", "country": "India", "region": "South Asia"},
    "tr": {"name": "Turkish", "country": "Turkey", "region": "Middle East"},
    "ja": {"name": "Japanese", "country": "Japan", "region": "East Asia"},
    "ko": {"name": "Korean", "country": "South Korea", "region": "East Asia"},
    "zh": {"name": "Chinese", "country": "China", "region": "East Asia"},
    "ru": {"name": "Russian", "country": "Russia", "region": "Europe"},
    "id": {"name": "Indonesian", "country": "Indonesia", "region": "Southeast Asia"},
    "ms": {"name": "Malay", "country": "Malaysia", "region": "Southeast Asia"},
    "th": {"name": "Thai", "country": "Thailand", "region": "Southeast Asia"},
    "vi": {"name": "Vietnamese", "country": "Vietnam", "region": "Southeast Asia"},
    "sw": {"name": "Swahili", "country": "Kenya", "region": "Africa"},
    "ha": {"name": "Hausa", "country": "Nigeria", "region": "Africa"},
    "bn": {"name": "Bengali", "country": "Bangladesh", "region": "South Asia"},
    "ur": {"name": "Urdu", "country": "Pakistan", "region": "South Asia"},
    "fa": {"name": "Persian", "country": "Iran", "region": "Middle East"},
    "he": {"name": "Hebrew", "country": "Israel", "region": "Middle East"},
}

# ── event query configs ──────────────────────────────────────────

EVENTS = {
    "cs1_iran": {
        "event_id": 2,
        "label": "CS1: Iran Strike",
        # per-language queries — use native terms for each language
        # format: {lang_code: [queries]} or "default" for languages without specific terms
        "queries_by_lang": {
            "default": ["iran"],  # broad catch-all, works in any language
            "fr": ["iran frappe militaire", "iran bombardement"],
            "de": ["Iran Angriff", "Iran Bombardierung"],
            "es": ["Irán ataque", "Irán bombardeo"],
            "it": ["Iran attacco", "Iran bombardamento"],
            "pt": ["Irã ataque", "Irã bombardeio"],
            "ar": ["\u0625\u064a\u0631\u0627\u0646 \u0647\u062c\u0648\u0645", "\u0625\u064a\u0631\u0627\u0646 \u0636\u0631\u0628\u0629"],  # iran hujum, iran darba
            "fa": ["\u0627\u06cc\u0631\u0627\u0646 \u062d\u0645\u0644\u0647", "\u0627\u06cc\u0631\u0627\u0646 \u0628\u0645\u0628\u0627\u0631\u0627\u0646"],  # iran hamle, iran bombardan
            "tr": ["İran saldırı", "İran bombardıman"],
            "hi": ["\u0908\u0930\u0627\u0928 \u0939\u092e\u0932\u093e", "\u0908\u0930\u0906\u0928 \u092c\u092e\u092c\u093e\u0930\u0940"],  # iran hamla, iran bambari
            "ru": ["\u0418\u0440\u0430\u043d \u0443\u0434\u0430\u0440", "\u0418\u0440\u0430\u043d \u0431\u043e\u043c\u0431\u0430\u0440\u0434\u0438\u0440\u043e\u0432\u043a\u0430"],  # iran udar, iran bombardirovka
            "ja": ["\u30a4\u30e9\u30f3 \u653b\u6483"],  # iran kougeki
            "ko": ["\uc774\ub780 \uacf5\uaca9"],  # iran gonggyeok
            "zh": ["\u4f0a\u6717 \u8972\u51fb"],  # yilang xiji
            "he": ["\u05d0\u05d9\u05e8\u05df \u05ea\u05e7\u05d9\u05e4\u05d4"],  # iran tkifa
            "id": ["Iran serangan"],
            "ms": ["Iran serangan"],
            "sw": ["Iran shambulio"],
        },
        # for historical, use from_date/to_date (YYYY-MM-DD)
        "from_date": "2026-02-26",
        "to_date": "2026-03-06",
    },
    "cs2_tariffs": {
        "event_id": 3,
        "label": "CS2: US Tariffs",
        "queries_by_lang": {
            "default": ["tariff"],
            "fr": ["droits de douane", "guerre commerciale"],
            "de": ["Zölle Handel", "Handelskrieg"],
            "es": ["aranceles comercio", "guerra comercial"],
            "it": ["dazi commercio", "guerra commerciale"],
            "pt": ["tarifas comércio", "guerra comercial"],
            "nl": ["handelsoorlog", "invoertarieven"],
            "ar": ["\u0631\u0633\u0648\u0645 \u062c\u0645\u0631\u043a\u064a\u0629", "\u062d\u0631\u0628 \u062a\u062c\u0627\u0631\u064a\u0629"],  # rusum jumrukiyya, harb tijariyya
            "tr": ["gümrük vergisi", "ticaret savaşı"],
            "hi": ["\u0936\u0941\u0932\u094d\u0915 \u0935\u094d\u092f\u093e\u092a\u093e\u0930 \u092f\u0941\u0926\u094d\u0927"],  # shulk vyapar yuddh
            "ru": ["\u0442\u0430\u0440\u0438\u0444\u044b \u0442\u043e\u0440\u0433\u043e\u0432\u0430\u044f \u0432\u043e\u0439\u043d\u0430"],  # tarify torgovaya voina
            "ja": ["\u95a2\u7a0e \u8cbf\u6613\u6226\u4e89"],  # kanzei boueki sensou
            "ko": ["\uad00\uc138 \ubb34\uc5ed\uc804\uc7c1"],  # gwanse muyeok jeonjaeng
            "zh": ["\u5173\u7a0e \u8d38\u6613\u6218"],  # guanshui maoyi zhan
            "id": ["tarif perdagangan"],
            "ms": ["tarif perdagangan"],
            "pl": ["cła handlowe", "wojna handlowa"],
            "sv": ["tullar handel"],
            "da": ["told handel"],
        },
        # CS2 has multiple windows — default to all
        "windows": {
            "w1_announcement": {"from": "2025-04-02", "to": "2025-04-08"},
            "w2_pause":        {"from": "2025-04-09", "to": "2025-04-16"},
            "w3_reimposition": {"from": "2025-05-01", "to": "2025-07-31"},
            "w4_retaliation":  {"from": "2025-08-01", "to": "2025-10-31"},
            "w5_retrospective":{"from": "2026-02-24", "to": "2026-03-06"},
        },
    },
}


def api_call(params, endpoint=API_NEWS):
    """make a single NewsData.io API call. returns parsed JSON or None.
    free tier: /news has 48h lookback, /latest is real-time, /archive is paid.
    """
    params["apikey"] = API_KEY
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url, headers={
        "User-Agent": "NewsKaleidoscope/0.1 (epistemic mapping research)",
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "error":
            print(f"    API error: {data.get('results', {}).get('message', 'unknown')}")
            return None
        return data
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"    rate limited (429) — daily quota may be exhausted")
        else:
            print(f"    HTTP {e.code}")
        return None
    except Exception as e:
        print(f"    error: {e}")
        return None


def fetch_language(lang_code, lang_info, query, from_date=None, to_date=None, page=None):
    """fetch articles for a specific language and query.
    free tier: /news endpoint has 48h lookback, no from_date/to_date support.
    /archive supports dates but requires paid tier.
    we use /news for current events and skip historical windows on free tier.
    """
    params = {
        "q": query,
        "language": lang_code,
        "size": "10",  # free tier max is 10 per page
    }
    if page:
        params["page"] = page

    # free tier can't filter by date — /news returns last 48h automatically
    # we'll post-filter by date client-side if needed
    time.sleep(REQUEST_DELAY)
    return api_call(params, endpoint=API_NEWS)


def normalize_article(art, event_id, lang_code, lang_info):
    """convert newsdata.io article to our standard format."""
    # newsdata returns: title, link, description, content, pubDate, country, language, etc.
    url = art.get("link", "")
    title = art.get("title", "")
    description = art.get("description", "")
    content = art.get("content", "")
    pub_date = art.get("pubDate", "")

    # country can be a list in newsdata
    countries = art.get("country", [])
    country = countries[0] if countries else lang_info.get("country", "unknown")

    # convert pub_date to our seendate format (YYYYMMDDHHmmss)
    seendate = ""
    if pub_date:
        try:
            dt = datetime.strptime(pub_date, "%Y-%m-%d %H:%M:%S")
            seendate = dt.strftime("%Y%m%d%H%M%S")
        except ValueError:
            seendate = pub_date.replace("-", "").replace(":", "").replace(" ", "")[:14]

    # extract domain from URL
    domain = ""
    if url:
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = url.split("/")[2] if len(url.split("/")) > 2 else ""

    # cache the content if available
    if url and (content or description):
        text = content or description
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
        if not os.path.exists(cache_path):
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)

    return {
        "url": url,
        "title": title,
        "seendate": seendate,
        "sourcecountry": country.upper() if len(country) == 2 else country,
        "sourcelang": lang_info["name"],
        "domain": domain,
        "source": "newsdata",
        "tier": 1,
        "region": lang_info["region"],
        "event_id": event_id,
        "text_chars": len(content or description or ""),
        "has_full_text": bool(content),
    }


def ingest_event(event_key, lang_filter=None, window_filter=None):
    """ingest articles for an event across all configured languages."""
    if not API_KEY:
        print("ERROR: NEWSDATA_API_KEY not set. Run: export NEWSDATA_API_KEY=your_key")
        sys.exit(1)

    cfg = EVENTS[event_key]
    event_id = cfg["event_id"]
    label = cfg["label"]
    queries_by_lang = cfg["queries_by_lang"]

    # determine languages to query
    languages = {}
    languages.update(EU_LANGUAGES)
    languages.update(GLOBAL_LANGUAGES)

    if lang_filter:
        if lang_filter in languages:
            languages = {lang_filter: languages[lang_filter]}
        else:
            print(f"unknown language code: {lang_filter}")
            print(f"valid: {', '.join(sorted(languages.keys()))}")
            sys.exit(1)

    # free tier: no historical queries, just pull current/recent articles
    # the /news endpoint returns last 48h, no date filtering
    # budget: ~200 credits/day, 10 articles per credit
    total_calls = sum(len(queries_by_lang.get(lc, queries_by_lang["default"])) for lc in languages)
    print(f"\n{'='*60}")
    print(f"  NEWSDATA INGESTION: {label}")
    print(f"  {len(languages)} languages, ~{total_calls} API calls estimated")
    print(f"  note: free tier = last 48h only, 200 credits/day")
    print(f"{'='*60}")

    all_articles = []
    seen_urls = set()
    credits_used = 0
    stats = {"languages_queried": 0, "articles_found": 0, "errors": 0}

    for lang_code, lang_info in sorted(languages.items()):
        lang_name = lang_info["name"]
        print(f"\n  {lang_name} ({lang_code}):", flush=True)
        stats["languages_queried"] += 1
        lang_articles = 0

        # use language-specific queries if available, else default
        lang_queries = queries_by_lang.get(lang_code, queries_by_lang["default"])
        for query in lang_queries:
            print(f"    '{query}'...", end=" ", flush=True)
            data = fetch_language(lang_code, lang_info, query)
            credits_used += 1

            if not data:
                print("FAILED")
                stats["errors"] += 1
                continue

            results = data.get("results", [])
            if not results:
                print("0 articles")
                continue

            new = 0
            for art in results:
                normalized = normalize_article(art, event_id, lang_code, lang_info)
                if normalized["url"] and normalized["url"] not in seen_urls:
                    seen_urls.add(normalized["url"])
                    all_articles.append(normalized)
                    new += 1
                    lang_articles += 1

            print(f"{new} new ({len(results)} raw)")

            # check if we're near credit limit
            if credits_used >= 190:
                print(f"\n  WARNING: approaching daily credit limit ({credits_used}/200)")
                print(f"  stopping to preserve quota")
                break
        if credits_used >= 190:
            break

        if lang_articles > 0:
            print(f"    total {lang_name}: {lang_articles} articles")

    stats["articles_found"] = len(all_articles)

    # save output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    suffix = f"_{lang_filter}" if lang_filter else ""
    suffix += f"_{window_filter}" if window_filter else ""
    outfile = os.path.join(OUTPUT_DIR, f"{event_key}{suffix}.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)

    # summary
    print(f"\n{'='*60}")
    print(f"  NEWSDATA SUMMARY: {label}")
    print(f"  languages queried: {stats['languages_queried']}")
    print(f"  articles found: {stats['articles_found']}")
    print(f"  API credits used: {credits_used}")
    print(f"  errors: {stats['errors']}")
    print(f"  output: {outfile}")

    # language breakdown
    by_lang = {}
    for a in all_articles:
        l = a["sourcelang"]
        by_lang[l] = by_lang.get(l, 0) + 1
    print(f"  languages ({len(by_lang)}):")
    for l in sorted(by_lang.keys()):
        print(f"    {l}: {by_lang[l]}")

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
    if len(sys.argv) < 2:
        print("usage: python3 newsdata_ingest.py <cs1_iran|cs2_tariffs> [options]")
        print("  options:")
        print("    --lang XX       filter to single language (e.g. fr, de, es)")
        print("    --window WID    filter to single window (cs2 only)")
        print("  examples:")
        print("    python3 newsdata_ingest.py cs2_tariffs")
        print("    python3 newsdata_ingest.py cs2_tariffs --lang fr")
        print("    python3 newsdata_ingest.py cs2_tariffs --window w1_announcement")
        print("    python3 newsdata_ingest.py cs1_iran --lang ar")
        sys.exit(1)

    event_key = sys.argv[1]
    if event_key not in EVENTS:
        print(f"unknown event: {event_key}")
        sys.exit(1)

    # parse options
    lang_filter = None
    window_filter = None
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--lang" and i + 1 < len(args):
            lang_filter = args[i + 1]
            i += 2
        elif args[i] == "--window" and i + 1 < len(args):
            window_filter = args[i + 1]
            i += 2
        else:
            print(f"unknown option: {args[i]}")
            sys.exit(1)

    ingest_event(event_key, lang_filter=lang_filter, window_filter=window_filter)


if __name__ == "__main__":
    main()
