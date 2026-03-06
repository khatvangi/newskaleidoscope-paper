#!/usr/bin/env python3
"""
presupposition_extractor.py — session 5, task 5.

runs presupposition extraction on targeted articles identified by
correlation analysis (top contested by strategic ambiguity score + US articles).

uses llama-server on boron (qwen3-32b).
stores results in presuppositions table.

run_id: session_005
"""

import json
import logging
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/presupposition_extractor.log"),
    ],
)
log = logging.getLogger("presupposition")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
LLM_URL = "http://boron:11434"
TIMEOUT = 180
RUN_ID = "session_005"

# targeted article IDs from correlation analysis
# batch 1: top 15 contested by ambiguity score (no severe tokenism)
# batch 2: US articles not in batch 1
TARGET_IDS = [7, 17, 18, 20, 34, 37, 50, 55, 56, 59, 60, 70, 80, 81, 84, 85]

SYSTEM_PROMPT = """You are an analyst detecting presuppositional framing in news articles.

Presuppositional framing embeds political claims as background fact rather than argued positions. The claim is never stated — it is assumed. This makes it invisible to standard bias detection.

Analyze the article below. For EACH presupposition you identify, output a JSON object. Return a JSON array of all presuppositions found.

Each presupposition:
{
  "presupposition": "the claim treated as established fact rather than argued position",
  "carrier_phrase": "the exact phrase from the article that embeds the presupposition",
  "favors_actor": "which actor benefits from this being treated as background fact",
  "consistency_check": "is this same assumption applied to all actors equally, or selectively?",
  "would_be_contested_by": "who would dispute this assumption and what would they say instead",
  "implicit_question": "what question does the article treat as the important one about this event? what question does it exclude?"
}

Focus especially on:
- Noun phrases that embed characterizations as facts ("Iran's nuclear weapons program", "Iranian aggression", "Iranian-backed Hezbollah")
- Questions the article treats as THE relevant ones (implicit agenda-setting)
- Historical context treated as settled rather than contested
- Whose perspective is centered as the neutral/default viewpoint
- What is treated as requiring justification vs. what is taken for granted

Return ONLY a JSON array. No preamble, no explanation. If you find no presuppositions, return [].
"""


def llm_call(article_text):
    """send article to llama-server on boron."""
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"ARTICLE TEXT:\n{article_text[:8000]}"},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            choices = result.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("content", "") or msg.get("reasoning_content", "")
            return ""
    except Exception as e:
        log.error(f"  llm call failed: {e}")
        return None


def parse_json_array(raw):
    """extract JSON array from LLM response."""
    if not raw:
        return None
    cleaned = raw.strip()
    # strip markdown fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    # strip qwen3 thinking tags
    if "<think>" in cleaned:
        idx = cleaned.rfind("</think>")
        if idx >= 0:
            cleaned = cleaned[idx + len("</think>"):].strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return None
    except json.JSONDecodeError:
        # find array
        start = cleaned.find("[")
        end = cleaned.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass
        # try finding object
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                obj = json.loads(cleaned[start:end])
                return [obj]
            except json.JSONDecodeError:
                pass
    return None


def main():
    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        # immutability check
        existing = conn.execute(text(
            "SELECT count(*) FROM presuppositions WHERE run_id = :rid"
        ), {"rid": RUN_ID})
        count = existing.fetchone()[0]
        if count > 0:
            log.warning(f"found {count} existing rows for {RUN_ID} — aborting")
            sys.exit(1)

        # fetch target articles
        placeholders = ", ".join(str(i) for i in TARGET_IDS)
        rows = conn.execute(text(f"""
            SELECT a.id, a.title, a.original_language, a.translated_text, a.raw_text,
                   s.country_code, s.name as outlet
            FROM articles a
            LEFT JOIN sources s ON a.source_id = s.id
            WHERE a.id IN ({placeholders})
            ORDER BY a.id
        """))

        articles = []
        for r in rows:
            article_text = r.translated_text or r.raw_text or ""
            articles.append({
                'id': r.id, 'title': r.title, 'lang': r.original_language or 'en',
                'cc': r.country_code or '??', 'outlet': r.outlet or '??',
                'text': article_text,
            })

        log.info(f"loaded {len(articles)} target articles for presupposition extraction")

        # verify llama-server
        try:
            req = urllib.request.Request(f"{LLM_URL}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                health = json.loads(resp.read().decode("utf-8"))
                if health.get("status") != "ok":
                    log.error("llama-server not healthy")
                    sys.exit(1)
        except Exception as e:
            log.error(f"llama-server not reachable: {e}")
            sys.exit(1)

        log.info("llama-server healthy, starting extraction")

        all_presuppositions = []
        article_results = []

        for i, art in enumerate(articles):
            log.info(f"  [{i+1}/{len(articles)}] article {art['id']} ({art['cc']}, {art['outlet'][:35]})")

            if not art['text'] or len(art['text'].strip()) < 50:
                log.warning(f"    skipping — no text")
                continue

            raw = llm_call(art['text'])
            parsed = parse_json_array(raw)

            if parsed:
                log.info(f"    found {len(parsed)} presuppositions")
                for p in parsed:
                    p['article_id'] = art['id']
                    p['country_code'] = art['cc']
                    p['outlet'] = art['outlet']
                    all_presuppositions.append(p)

                article_results.append({
                    'article_id': art['id'],
                    'country_code': art['cc'],
                    'outlet': art['outlet'],
                    'language': art['lang'],
                    'presupposition_count': len(parsed),
                    'presuppositions': parsed,
                })
            else:
                log.warning(f"    failed to parse response")
                if raw:
                    log.warning(f"    raw (first 200): {raw[:200]}")
                article_results.append({
                    'article_id': art['id'],
                    'error': 'parse_failed',
                    'raw': (raw or '')[:500],
                })

        # write to DB
        log.info(f"\nwriting {len(all_presuppositions)} presuppositions to DB")
        success = 0
        for p in all_presuppositions:
            conn.execute(text("""
                INSERT INTO presuppositions
                    (article_id, run_id, presupposition, carrier_phrase,
                     favors_actor, consistency_check, would_be_contested_by)
                VALUES
                    (:aid, :rid, :presup, :carrier, :favors, :consistency, :contested)
            """), {
                'aid': p['article_id'],
                'rid': RUN_ID,
                'presup': p.get('presupposition', ''),
                'carrier': p.get('carrier_phrase', ''),
                'favors': p.get('favors_actor', ''),
                'consistency': p.get('consistency_check', ''),
                'contested': p.get('would_be_contested_by', ''),
            })
            success += 1
        conn.commit()
        log.info(f"  {success} rows written")

        # save to json
        outfile = f"analysis/session5_presuppositions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(outfile, 'w') as f:
            json.dump({
                'run_id': RUN_ID,
                'created': datetime.now().isoformat(),
                'method': 'qwen3-32b presupposition extraction on targeted articles',
                'target_ids': TARGET_IDS,
                'articles_processed': len(articles),
                'total_presuppositions': len(all_presuppositions),
                'results': article_results,
            }, f, indent=2, ensure_ascii=False)
        log.info(f"  saved to {outfile}")

        # print report
        print("\n" + "=" * 70)
        print("SESSION 5 — PRESUPPOSITION EXTRACTION REPORT")
        print(f"  run_id: {RUN_ID}")
        print(f"  articles: {len(articles)}")
        print(f"  total presuppositions found: {len(all_presuppositions)}")
        print("=" * 70)

        # per-article summary
        print(f"\nPER-ARTICLE COUNTS:")
        for r in article_results:
            if 'error' in r:
                print(f"  article {r['article_id']:>3}: FAILED")
            else:
                print(f"  article {r['article_id']:>3} ({r.get('country_code','??'):>3}, {r.get('outlet','?')[:30]}): "
                      f"{r['presupposition_count']} presuppositions")

        # who benefits
        from collections import Counter
        favors = Counter()
        for p in all_presuppositions:
            actor = p.get('favors_actor', 'unknown')
            favors[actor] += 1

        print(f"\nWHO BENEFITS FROM PRESUPPOSITIONS:")
        for actor, count in favors.most_common():
            print(f"  {actor[:50]:>50}: {count}")

        # sample presuppositions by type
        print(f"\nSAMPLE PRESUPPOSITIONS (first 3 per article):")
        for r in article_results:
            if 'error' in r:
                continue
            print(f"\n  article {r['article_id']} ({r.get('country_code','??')}, {r.get('outlet','?')[:30]}):")
            for p in r['presuppositions'][:3]:
                print(f"    presupposition: {p.get('presupposition', 'N/A')[:100]}")
                print(f"    carrier:        {p.get('carrier_phrase', 'N/A')[:100]}")
                print(f"    favors:         {p.get('favors_actor', 'N/A')[:60]}")
                iq = p.get('implicit_question', '')
                if iq:
                    print(f"    implicit Q:     {iq[:100]}")
                print()

        # implicit questions summary
        print(f"\nIMPLICIT QUESTIONS (what the article treats as THE important question):")
        for p in all_presuppositions:
            iq = p.get('implicit_question', '')
            if iq:
                print(f"  article {p['article_id']:>3}: {iq[:120]}")

        print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
