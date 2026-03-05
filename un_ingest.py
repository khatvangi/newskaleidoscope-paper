#!/usr/bin/env python3
"""
un_ingest.py — ingest UN Security Council press releases and meeting records.

targets press.un.org for:
- emergency session transcripts (per-country positions)
- secretary-general statements
- security council press statements

each country statement is extracted as a separate "article" for the pipeline,
enabling direct comparison of diplomatic vs domestic media framing.
"""

import json
import os
import re
import hashlib
import time
import urllib.request
import urllib.error

ARTICLES_FILE = "articles.json"
CACHE_DIR = "cache"
LLM_URL = "http://boron:11434"
LLM_TIMEOUT = 180

os.makedirs(CACHE_DIR, exist_ok=True)

# ── UN Security Council document registry ──────────────────────────
# curated list of Iran-related SC documents (manually verified URLs)
SC_DOCUMENTS = [
    {
        "url": "https://press.un.org/en/2026/sc16307.doc.htm",
        "doc_id": "SC/16307",
        "title": "Emergency Session: Military Strikes on Iran",
        "date": "2026-02-28",
        "doc_type": "meeting_record",
    },
    {
        "url": "https://press.un.org/en/2026/sgsm23033.doc.htm",
        "doc_id": "SG/SM/23033",
        "title": "Secretary-General Warns of Wider Conflict Following Iran Strikes",
        "date": "2026-02-28",
        "doc_type": "sg_statement",
    },
]

# countries expected on the Security Council + key speakers
# used to identify country-attributed statements in transcripts
SC_MEMBERS_2026 = [
    "United States", "United Kingdom", "France", "Russia", "China",
    "Colombia", "Greece", "Pakistan", "Latvia", "Denmark",
    "Panama", "Liberia", "Democratic Republic of Congo", "Bahrain",
    "Iran", "Israel", "Arab League",
]


def fetch_url(url):
    """fetch URL text, cache by hash."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            text = f.read()
        if text.strip():
            print(f"  cache hit: {url[:60]}...")
            return text

    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False,
                                       include_tables=False)
    except ImportError:
        text = None
    except Exception as e:
        print(f"  trafilatura error: {e}")
        text = None

    if not text:
        # fallback: urllib + basic cleanup
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (NewsKaleidoscope Research)"
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # strip HTML tags for raw extraction
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()
        except Exception as e:
            print(f"  fetch error: {e}")
            return None

    if text and text.strip():
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text
    return None


def llm_extract_positions(full_text, doc_title):
    """use LLM to extract per-country positions from a SC meeting record."""
    prompt = f"""You are extracting country-by-country positions from a UN Security Council meeting record.

Document: {doc_title}

For each country that spoke, extract:
1. The country name
2. Their stated position (2-3 sentences, using their own language)
3. Key framing words they used
4. What they did NOT say (obvious omissions given their known interests)

Also extract the Secretary-General's position separately.

Output JSON:
{{
  "country_positions": [
    {{
      "country": "country name",
      "speaker": "name and title if available",
      "position_summary": "2-3 sentence summary of their stated position",
      "key_framing_language": ["specific phrases they used"],
      "notable_omissions": "what this country conspicuously did not say"
    }}
  ],
  "sg_position": {{
    "position_summary": "Secretary-General's position",
    "key_framing_language": ["specific phrases"],
    "notable_omissions": "what the SG did not say"
  }}
}}

IMPORTANT: Output ONLY valid JSON, no other text.

Meeting transcript:
{full_text[:6000]}"""

    payload = json.dumps({
        "model": "qwen3-32b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 3072,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"].get("content", "")
            if not content:
                content = result["choices"][0]["message"].get("reasoning_content", "")
            # parse JSON from response
            cleaned = content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end])
    except Exception as e:
        print(f"  LLM error: {e}")
    return None


def create_articles_from_positions(positions_data, doc):
    """convert per-country positions into pipeline-compatible articles."""
    articles = []

    if not positions_data:
        return articles

    # each country position becomes a separate "article"
    for pos in positions_data.get("country_positions", []):
        country = pos.get("country", "Unknown")
        articles.append({
            "url": f"{doc['url']}#{country.lower().replace(' ', '-')}",
            "title": f"[UN SC] {country}: {doc['title'][:60]}",
            "domain": "press.un.org",
            "sourcecountry": country,
            "sourcelang": "English",
            "source": "un_security_council",
            "doc_id": doc["doc_id"],
            "doc_type": doc["doc_type"],
            "date": doc["date"],
            "position_summary": pos.get("position_summary", ""),
            "key_framing_language": pos.get("key_framing_language", []),
            "notable_omissions": pos.get("notable_omissions", ""),
            "speaker": pos.get("speaker", ""),
        })

    # secretary-general as separate entry
    sg = positions_data.get("sg_position")
    if sg:
        articles.append({
            "url": f"{doc['url']}#secretary-general",
            "title": f"[UN SG] Secretary-General: {doc['title'][:60]}",
            "domain": "press.un.org",
            "sourcecountry": "United Nations",
            "sourcelang": "English",
            "source": "un_security_council",
            "doc_id": doc["doc_id"],
            "doc_type": "sg_statement",
            "date": doc["date"],
            "position_summary": sg.get("position_summary", ""),
            "key_framing_language": sg.get("key_framing_language", []),
            "notable_omissions": sg.get("notable_omissions", ""),
            "speaker": "Secretary-General",
        })

    return articles


def cache_position_as_text(article):
    """write position summary to cache so pipeline can process it."""
    url_hash = hashlib.md5(article["url"].encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")

    # build a rich text block for the pipeline to analyze
    text = f"""UN Security Council Meeting Record — {article['doc_id']}
Date: {article['date']}
Speaker: {article.get('speaker', 'Unknown')} ({article['sourcecountry']})

STATED POSITION:
{article['position_summary']}

KEY LANGUAGE USED:
{', '.join(article.get('key_framing_language', []))}

NOTABLE OMISSIONS:
{article.get('notable_omissions', 'None identified')}
"""
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(text)
    return cache_path


def main():
    print("=" * 60)
    print("UN SECURITY COUNCIL INGESTOR")
    print("=" * 60)

    # load existing articles
    existing = []
    if os.path.exists(ARTICLES_FILE):
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing_urls = {a["url"] for a in existing}

    new_articles = []

    for doc in SC_DOCUMENTS:
        print(f"\n[{doc['doc_id']}] {doc['title']}")
        print(f"  type: {doc['doc_type']}, date: {doc['date']}")

        # fetch full text
        text = fetch_url(doc["url"])
        if not text:
            print("  SKIP: could not fetch document")
            continue
        print(f"  fetched: {len(text)} chars")

        # extract per-country positions via LLM
        print("  extracting country positions via LLM...")
        positions = llm_extract_positions(text, doc["title"])
        if not positions:
            print("  SKIP: LLM extraction failed")
            continue

        n_countries = len(positions.get("country_positions", []))
        has_sg = bool(positions.get("sg_position"))
        print(f"  extracted: {n_countries} country positions" +
              (" + SG statement" if has_sg else ""))

        # convert to articles
        articles = create_articles_from_positions(positions, doc)
        for a in articles:
            if a["url"] not in existing_urls:
                # cache the position text for pipeline processing
                cache_position_as_text(a)
                new_articles.append(a)
                existing_urls.add(a["url"])
                print(f"    + {a['sourcecountry']}: {a['position_summary'][:60]}...")

        time.sleep(2)  # be polite to UN servers

    # save positions data for analysis
    os.makedirs("analysis", exist_ok=True)
    for doc in SC_DOCUMENTS:
        text = fetch_url(doc["url"])
        if text:
            positions = llm_extract_positions(text, doc["title"])
            if positions:
                safe_id = doc["doc_id"].replace("/", "_").replace(" ", "_")
                pos_path = f"analysis/un_{safe_id}_positions.json"
                with open(pos_path, "w", encoding="utf-8") as f:
                    json.dump(positions, f, indent=2, ensure_ascii=False)
                print(f"  saved: {pos_path}")

    if new_articles:
        # append to articles.json
        existing.extend(new_articles)
        with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        print(f"\n  added {len(new_articles)} UN SC articles to {ARTICLES_FILE}")
    else:
        print("\n  no new articles to add")

    print(f"\n{'=' * 60}")
    print(f"UN INGEST COMPLETE")
    print(f"  documents processed: {len(SC_DOCUMENTS)}")
    print(f"  new articles added: {len(new_articles)}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
