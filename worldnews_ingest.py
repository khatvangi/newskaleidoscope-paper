#!/usr/bin/env python3
"""
worldnews_ingest.py — multilingual news ingestion via World News API.

key advantage over NewsData.io: returns FULL article text (no separate extraction needed).
80+ languages, 210+ countries. free tier has daily limits but supports historical queries.

API docs: https://worldnewsapi.com/docs/

usage:
  python3 worldnews_ingest.py cs1_iran                     # all priority languages
  python3 worldnews_ingest.py cs1_iran --lang fr            # french only
  python3 worldnews_ingest.py cs2_tariffs                   # tariff coverage
  python3 worldnews_ingest.py cs2_tariffs --window w1       # specific window
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

API_ENDPOINTS = [
    # same backend, separate quotas — use both for 2x coverage
    {"base": "https://api.worldnewsapi.com/search-news", "key_env": "WORLDNEWS_API_KEY"},
    {"base": "https://api.apileague.com/search-news", "key_env": "APILEAGUE_API_KEY"},
]
OUTPUT_DIR = "sources/worldnews"
CACHE_DIR = "cache"
REQUEST_DELAY = 1.5  # be polite
MAX_PER_QUERY = 50   # max results per API call

# pick first available key
API_KEY = ""
API_BASE = ""
for ep in API_ENDPOINTS:
    key = os.environ.get(ep["key_env"], "")
    if key:
        API_KEY = key
        API_BASE = ep["base"]
        break

# ── priority languages (ordered by gap severity in our corpus) ────

# tier A: biggest gaps — these languages have zero or near-zero representation
PRIORITY_A = {
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "ar": "Arabic",
    "fa": "Persian",
    "hi": "Hindi",
    "tr": "Turkish",
    "ru": "Russian",
    "pt": "Portuguese",
}

# tier B: important but less critical gaps
PRIORITY_B = {
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "id": "Indonesian",
    "nl": "Dutch",
    "pl": "Polish",
    "he": "Hebrew",
    "ur": "Urdu",
    "bn": "Bengali",
    "sw": "Swahili",
    "sv": "Swedish",
    "ro": "Romanian",
    "el": "Greek",
    "cs": "Czech",
    "hu": "Hungarian",
    "th": "Thai",
    "vi": "Vietnamese",
    "ms": "Malay",
}

# ── event configs with per-language search terms ─────────────────

EVENTS = {
    "cs1_iran": {
        "event_id": 2,
        "label": "CS1: Iran Strike",
        "earliest_date": "2026-02-26",
        "latest_date": "2026-03-06",
        "queries_by_lang": {
            "default": ["iran attack", "iran strike"],
            "fr": ["iran frappe", "iran bombardement"],
            "de": ["Iran Angriff", "Iran Bombardierung"],
            "es": ["Irán ataque", "Irán bombardeo"],
            "it": ["Iran attacco", "Iran bombardamento"],
            "pt": ["Irã ataque", "Irã guerra"],
            "ar": ["إيران هجوم", "إيران ضربة"],
            "fa": ["ایران حمله", "ایران بمباران"],
            "tr": ["İran saldırı", "İran bombardıman"],
            "hi": ["ईरान हमला", "ईरान बमबारी"],
            "ru": ["Иран удар", "Иран бомбардировка"],
            "ja": ["イラン 攻撃"],
            "ko": ["이란 공격"],
            "zh": ["伊朗 袭击"],
            "he": ["איראן תקיפה"],
            "id": ["Iran serangan"],
            "sw": ["Iran shambulio"],
        },
    },
    "cs1ru_ukraine": {
        "event_id": 4,
        "label": "CS1-RU: Ukraine Invasion (2022)",
        "earliest_date": "2022-02-24",
        "latest_date": "2022-03-02",
        "queries_by_lang": {
            "default": ["Russia Ukraine invasion", "Ukraine war 2022"],
            "fr": ["Russie Ukraine invasion", "guerre Ukraine 2022"],
            "de": ["Russland Ukraine Invasion", "Krieg Ukraine 2022"],
            "es": ["Rusia Ucrania invasión", "guerra Ucrania 2022"],
            "it": ["Russia Ucraina invasione", "guerra Ucraina 2022"],
            "pt": ["Rússia Ucrânia invasão", "guerra Ucrânia 2022"],
            "ar": ["روسيا أوكرانيا غزو", "حرب أوكرانيا"],
            "fa": ["روسیه اوکراین حمله", "جنگ اوکراین"],
            "tr": ["Rusya Ukrayna savaş", "Ukrayna işgal"],
            "hi": ["रूस यूक्रेन आक्रमण", "यूक्रेन युद्ध"],
            "ru": ["Россия Украина вторжение", "война Украина 2022"],
            "ja": ["ロシア ウクライナ 侵攻"],
            "ko": ["러시아 우크라이나 침공"],
            "zh": ["俄罗斯 乌克兰 入侵"],
            "he": ["רוסיה אוקראינה פלישה"],
            "id": ["Rusia Ukraina invasi"],
            "pl": ["Rosja Ukraina inwazja"],
            "nl": ["Rusland Oekraïne invasie"],
            "uk": ["Росія Україна вторгнення"],
            "ro": ["Rusia Ucraina invazie"],
            "cs": ["Rusko Ukrajina invaze"],
            "hu": ["Oroszország Ukrajna invázió"],
            "sv": ["Ryssland Ukraina invasion"],
            "el": ["Ρωσία Ουκρανία εισβολή"],
        },
    },
    "cs2_tariffs": {
        "event_id": 3,
        "label": "CS2: US Tariffs",
        "windows": {
            "w1": {"earliest": "2025-04-02", "latest": "2025-04-08"},
            "w2": {"earliest": "2025-04-09", "latest": "2025-04-16"},
            "w3": {"earliest": "2025-05-01", "latest": "2025-07-31"},
            "w4": {"earliest": "2025-08-01", "latest": "2025-10-31"},
            "w5": {"earliest": "2026-02-24", "latest": "2026-03-06"},
        },
        "queries_by_lang": {
            "default": ["tariff trade war", "reciprocal tariff"],
            "fr": ["droits de douane", "guerre commerciale"],
            "de": ["Zölle Handelskrieg", "Gegenzölle"],
            "es": ["aranceles guerra comercial", "aranceles recíprocos"],
            "it": ["dazi guerra commerciale"],
            "pt": ["tarifas guerra comercial"],
            "ar": ["رسوم جمركية حرب تجارية"],
            "tr": ["gümrük vergisi ticaret savaşı"],
            "hi": ["शुल्क व्यापार युद्ध"],
            "ru": ["тарифы торговая война"],
            "ja": ["関税 貿易戦争"],
            "ko": ["관세 무역전쟁"],
            "zh": ["关税 贸易战"],
            "nl": ["invoertarieven handelsoorlog"],
            "pl": ["cła wojna handlowa"],
        },
    },
}


def _try_api(base_url, api_key, params_base):
    """try a single API endpoint. returns (articles, quota_exhausted)."""
    params = dict(params_base)
    params["api-key"] = api_key
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})

    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            remaining = resp.headers.get("X-API-Quota-Left", "?")
            if remaining != "?":
                try:
                    if float(remaining) < 5:
                        print(f"\n  WARNING: only {remaining} quota left on {base_url.split('/')[2]}")
                        return data.get("news", []), True  # signal to switch endpoints
                except ValueError:
                    pass
            return data.get("news", []), False
        except urllib.error.HTTPError as e:
            if e.code == 402:
                return [], True  # quota exhausted — try next endpoint
            elif e.code == 429 and attempt == 0:
                time.sleep(10)
            else:
                return [], False
        except Exception:
            if attempt == 0:
                time.sleep(3)
    return [], False


# track which endpoint index to use (auto-failover)
_current_endpoint_idx = 0


def api_search(text, language=None, earliest_date=None, latest_date=None, number=MAX_PER_QUERY):
    """search news APIs with automatic failover between endpoints."""
    global _current_endpoint_idx

    params = {"text": text, "number": str(number)}
    if language:
        params["language"] = language
    if earliest_date:
        params["earliest-publish-date"] = f"{earliest_date} 00:00:00"
    if latest_date:
        params["latest-publish-date"] = f"{latest_date} 23:59:59"

    # try each endpoint starting from current
    for offset in range(len(API_ENDPOINTS)):
        idx = (_current_endpoint_idx + offset) % len(API_ENDPOINTS)
        ep = API_ENDPOINTS[idx]
        key = os.environ.get(ep["key_env"], "")
        if not key:
            continue

        articles, exhausted = _try_api(ep["base"], key, params)
        if exhausted:
            host = ep["base"].split("/")[2]
            print(f" [{host} exhausted, trying next]", end="", flush=True)
            _current_endpoint_idx = (idx + 1) % len(API_ENDPOINTS)
            continue
        return articles

    return []


def normalize_article(art, event_id, lang_code, window_id=None):
    """convert World News API article to our standard format."""
    url = art.get("url", "")
    title = art.get("title", "")
    text = art.get("text", "")
    pub_date = art.get("publish_date", "")
    source_country = art.get("source_country", "unknown")
    language = art.get("language", lang_code)

    # cache the full text — same hash scheme as pipeline.py
    if url and text:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
        if not os.path.exists(cache_path):
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)

    # convert pub_date to seendate format
    seendate = ""
    if pub_date:
        try:
            # world news api format: "2025-04-03 14:22:00"
            dt = datetime.strptime(pub_date[:19], "%Y-%m-%d %H:%M:%S")
            seendate = dt.strftime("%Y%m%d%H%M%S")
        except ValueError:
            seendate = pub_date.replace("-", "").replace(":", "").replace(" ", "")[:14]

    # extract domain
    domain = ""
    if url:
        try:
            domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        except Exception:
            pass

    result = {
        "url": url,
        "title": title,
        "seendate": seendate,
        "sourcecountry": source_country,
        "sourcelang": PRIORITY_A.get(lang_code, PRIORITY_B.get(lang_code, language)),
        "domain": domain,
        "source": "worldnews",
        "tier": 1,
        "event_id": event_id,
        "text_chars": len(text),
        "has_full_text": bool(text),
    }
    if window_id:
        result["window"] = window_id
    return result


def ingest_event(event_key, lang_filter=None, window_filter=None):
    """ingest articles for an event across priority languages."""
    # check at least one API key is available
    has_key = any(os.environ.get(ep["key_env"]) for ep in API_ENDPOINTS)
    if not has_key:
        print("ERROR: no API key set. Run: export WORLDNEWS_API_KEY=your_key")
        print("  or: export APILEAGUE_API_KEY=your_key")
        sys.exit(1)

    cfg = EVENTS[event_key]
    event_id = cfg["event_id"]
    label = cfg["label"]
    queries_by_lang = cfg["queries_by_lang"]

    # determine languages — priority A first, then B
    languages = {}
    languages.update(PRIORITY_A)
    languages.update(PRIORITY_B)
    if lang_filter:
        if lang_filter in languages:
            languages = {lang_filter: languages[lang_filter]}
        else:
            print(f"unknown language: {lang_filter}")
            sys.exit(1)

    # determine date ranges
    date_ranges = []
    if "windows" in cfg:
        windows = cfg["windows"]
        if window_filter:
            if window_filter in windows:
                w = windows[window_filter]
                date_ranges = [(window_filter, w["earliest"], w["latest"])]
            else:
                print(f"unknown window: {window_filter}")
                sys.exit(1)
        else:
            for wid, w in windows.items():
                date_ranges.append((wid, w["earliest"], w["latest"]))
    else:
        date_ranges = [("all", cfg.get("earliest_date"), cfg.get("latest_date"))]

    print(f"\n{'='*60}")
    print(f"  WORLD NEWS INGESTION: {label}")
    print(f"  {len(languages)} languages x {len(date_ranges)} windows")
    print(f"{'='*60}")

    all_articles = []
    seen_urls = set()
    api_calls = 0

    for lang_code, lang_name in languages.items():
        print(f"\n  {lang_name} ({lang_code}):", flush=True)
        lang_articles = 0

        # get queries for this language
        lang_queries = queries_by_lang.get(lang_code, queries_by_lang["default"])

        for window_id, earliest, latest in date_ranges:
            for query in lang_queries:
                tag = f"[{window_id}] " if len(date_ranges) > 1 else ""
                print(f"    {tag}'{query}'...", end=" ", flush=True)

                results = api_search(query, language=lang_code,
                                     earliest_date=earliest, latest_date=latest)
                api_calls += 1
                time.sleep(REQUEST_DELAY)

                if not results:
                    print("0 articles")
                    continue

                new = 0
                for art in results:
                    normalized = normalize_article(art, event_id, lang_code, window_id)
                    if normalized["url"] and normalized["url"] not in seen_urls:
                        seen_urls.add(normalized["url"])
                        all_articles.append(normalized)
                        new += 1
                        lang_articles += 1

                print(f"{new} new ({len(results)} raw)")

        if lang_articles > 0:
            print(f"    total {lang_name}: {lang_articles}")

    # save output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    suffix = f"_{lang_filter}" if lang_filter else ""
    suffix += f"_{window_filter}" if window_filter else ""
    outfile = os.path.join(OUTPUT_DIR, f"{event_key}{suffix}.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)

    # summary
    print(f"\n{'='*60}")
    print(f"  WORLD NEWS SUMMARY: {label}")
    print(f"  API calls: {api_calls}")
    print(f"  articles: {len(all_articles)}")
    print(f"  output: {outfile}")

    by_lang = {}
    for a in all_articles:
        l = a["sourcelang"]
        by_lang[l] = by_lang.get(l, 0) + 1
    print(f"  languages ({len(by_lang)}):")
    for l in sorted(by_lang.keys()):
        print(f"    {l}: {by_lang[l]}")

    by_country = {}
    for a in all_articles:
        c = a["sourcecountry"]
        by_country[c] = by_country.get(c, 0) + 1
    print(f"  countries ({len(by_country)}):")
    for c in sorted(by_country.keys()):
        print(f"    {c}: {by_country[c]}")

    # text stats
    with_text = sum(1 for a in all_articles if a["has_full_text"])
    avg_chars = sum(a["text_chars"] for a in all_articles) / max(len(all_articles), 1)
    print(f"  with full text: {with_text}/{len(all_articles)}")
    print(f"  avg text length: {avg_chars:.0f} chars")
    print(f"{'='*60}")

    return all_articles


def main():
    if len(sys.argv) < 2:
        print("usage: python3 worldnews_ingest.py <cs1_iran|cs2_tariffs> [options]")
        print("  options:")
        print("    --lang XX       single language (e.g. fr, de, ar)")
        print("    --window WID    single window (cs2 only: w1-w5)")
        sys.exit(1)

    event_key = sys.argv[1]
    if event_key not in EVENTS:
        print(f"unknown event: {event_key}. valid: {', '.join(EVENTS.keys())}")
        sys.exit(1)

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
