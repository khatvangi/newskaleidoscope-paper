#!/usr/bin/env python3
"""
session4_unassigned.py — targeted analysis of 37 articles that resisted
classification into session_001's 5 political-frame clusters.

uses a different analytical lens: register detection + embedded assumption
extraction, specifically designed to read "view from nowhere" journalism
and non-political epistemic frames.

stores results as run_id: session_004_unassigned
NEVER touches existing session data (immutability rule).
"""

import json
import logging
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from collections import Counter

from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/session4_unassigned.log"),
    ],
)
log = logging.getLogger("session4")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
LLM_URL = "http://boron:11434"
TIMEOUT = 120
RUN_ID = "session_004_unassigned"

# the 5 cluster names from session_001 for context in the prompt
EXISTING_CLUSTERS = [
    "Strategic Necessity of US-Israeli Military Action",
    "Legitimacy of US-Israeli Defensive Actions",
    "Critique of US Hegemony and Destabilization",
    "Diplomatic and Technical Resolution Focus",
    "Regional and Ethical Criticisms",
]

SYSTEM_PROMPT = """You are an analyst mapping epistemic registers in global media.
This article resisted classification into political-frame clusters.
Do NOT attempt to classify it politically.

Instead extract two things as JSON only. No preamble. JSON only.

{
  "register": ["array of applicable registers from: political, legal, economic, ethical_moral, spiritual_eschatological, technical_strategic, biographical, view_from_nowhere"],
  "register_explanation": "one sentence explaining why you chose these registers",
  "embedded_assumptions": {
    "default_legitimate_actor": "who is treated as the default legitimate actor? which side's actions need no justification?",
    "centered_perspective": "whose perspective is centered as the objective/neutral viewpoint?",
    "settled_history": "what historical context is treated as background fact rather than contested claim?",
    "named_casualties": "whose casualties are named, counted, or mourned? whose are absent or abstracted?",
    "implicit_question": "what does the article implicitly treat as THE important question about this event?"
  },
  "novel_frame": "if this article holds a genuinely novel frame not captured by existing political clusters, name and describe it in one sentence. otherwise null",
  "multiple_frames_tension": "if it holds multiple incompatible frames simultaneously, describe the tension. otherwise null",
  "why_unclassifiable": "if genuinely unclassifiable into any frame, explain why in one sentence. otherwise null"
}"""


def llm_call(article_text, system_prompt=SYSTEM_PROMPT):
    """send article to running llama-server on boron."""
    cluster_list = "\n".join(f"  - {c}" for c in EXISTING_CLUSTERS)
    user_prompt = f"""This article was not classifiable into any of these five political frames:
{cluster_list}

Analyze the article below. Extract register and embedded assumptions.

ARTICLE TEXT:
{article_text[:8000]}"""

    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
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


def parse_json(raw):
    """extract JSON from LLM response."""
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
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # try to find JSON object in the text
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass
    return None


def find_unassigned_articles(conn):
    """find articles in event_id=2 not assigned to any session_001 cluster."""
    assigned = conn.execute(text("""
        SELECT DISTINCT cm.article_id
        FROM cluster_memberships cm
        JOIN clusters c ON cm.cluster_id = c.id
        WHERE c.run_id = 'session_001'
    """))
    assigned_ids = {r[0] for r in assigned}

    all_arts = conn.execute(text("""
        SELECT a.id, a.title, a.original_language, a.translated_text, a.raw_text,
               s.country_code, s.name
        FROM articles a
        LEFT JOIN sources s ON a.source_id = s.id
        WHERE a.event_id = 2
        ORDER BY a.id
    """))

    unassigned = []
    for r in all_arts:
        aid, title, lang, translated, raw_text, cc, outlet = r
        if aid not in assigned_ids:
            # use translated text if available, else raw text
            article_text = translated or raw_text or ""
            unassigned.append({
                'id': aid, 'title': title, 'lang': lang or 'en',
                'cc': cc or '??', 'outlet': outlet or '??',
                'text': article_text,
            })
    return unassigned


def main():
    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        articles = find_unassigned_articles(conn)
        log.info(f"found {len(articles)} unassigned articles")

        if not articles:
            log.info("nothing to do")
            return

        # verify llama-server is running
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

        log.info(f"llama-server healthy, starting analysis")

        results = []
        for i, art in enumerate(articles):
            log.info(f"  [{i+1}/{len(articles)}] article {art['id']} ({art['cc']}, {art['outlet'][:30]})")

            if not art['text'] or len(art['text'].strip()) < 50:
                log.warning(f"    skipping — no text")
                results.append({'article_id': art['id'], 'error': 'no_text'})
                continue

            raw = llm_call(art['text'])
            parsed = parse_json(raw)

            if parsed:
                parsed['article_id'] = art['id']
                parsed['country_code'] = art['cc']
                parsed['outlet'] = art['outlet']
                parsed['language'] = art['lang']
                results.append(parsed)
                registers = parsed.get('register', [])
                log.info(f"    registers: {registers}")
            else:
                log.warning(f"    failed to parse response")
                results.append({
                    'article_id': art['id'], 'error': 'parse_failed',
                    'raw': (raw or '')[:200]
                })

        # write results to DB as new analyses with run_id
        log.info(f"\nwriting {len(results)} results to DB as {RUN_ID}")
        success = 0
        for r in results:
            if 'error' in r:
                continue
            conn.execute(text("""
                INSERT INTO analyses (article_id, event_id, model_used, primary_frame,
                                     positions, raw_llm_output)
                VALUES (:aid, 2, :model, :frame, CAST(:positions AS jsonb), CAST(:raw AS jsonb))
            """), {
                'aid': r['article_id'],
                'model': f'qwen3_32b_{RUN_ID}',
                'frame': r.get('register_explanation', ''),
                'positions': json.dumps(r.get('register', [])),
                'raw': json.dumps(r),
            })
            success += 1

        conn.commit()
        log.info(f"  {success} analyses written to DB")

        # also save to JSON (versioned, never overwrite)
        outfile = f"analysis/session4_unassigned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(outfile, 'w') as f:
            json.dump({
                'run_id': RUN_ID,
                'created': datetime.now().isoformat(),
                'method': 'targeted register + embedded assumption extraction',
                'existing_clusters': EXISTING_CLUSTERS,
                'articles_analyzed': len(articles),
                'results': results,
            }, f, indent=2, ensure_ascii=False)
        log.info(f"  saved to {outfile}")

        # print summary report
        print("\n" + "=" * 60)
        print(f"SESSION 4 — UNASSIGNED ARTICLE ANALYSIS")
        print(f"  run_id: {RUN_ID}")
        print(f"  articles: {len(articles)}")
        print(f"  successful: {success}")
        print("=" * 60)

        # register distribution
        register_counts = Counter()
        vfn_articles = []
        novel_frames = []
        tensions = []
        unclassifiable = []

        for r in results:
            if 'error' in r:
                continue
            for reg in r.get('register', []):
                register_counts[reg] += 1
            if 'view_from_nowhere' in r.get('register', []):
                vfn_articles.append(r)
            if r.get('novel_frame'):
                novel_frames.append(r)
            if r.get('multiple_frames_tension'):
                tensions.append(r)
            if r.get('why_unclassifiable'):
                unclassifiable.append(r)

        print(f"\nREGISTER DISTRIBUTION:")
        for reg, count in register_counts.most_common():
            print(f"  {count:>3}  {reg}")

        print(f"\nVIEW FROM NOWHERE: {len(vfn_articles)} articles")
        for r in vfn_articles:
            ea = r.get('embedded_assumptions', {})
            print(f"  article {r['article_id']} ({r.get('country_code', '??')}, {r.get('outlet', '?')[:25]})")
            print(f"    default actor: {ea.get('default_legitimate_actor', 'N/A')[:100]}")
            print(f"    centered:      {ea.get('centered_perspective', 'N/A')[:100]}")
            print(f"    implicit Q:    {ea.get('implicit_question', 'N/A')[:100]}")

        # US articles specifically
        print(f"\nUS ARTICLES — EMBEDDED ASSUMPTIONS:")
        for r in results:
            if r.get('country_code') == 'US' and 'error' not in r:
                ea = r.get('embedded_assumptions', {})
                print(f"\n  article {r['article_id']} ({r.get('outlet', '?')})")
                for k, v in ea.items():
                    print(f"    {k}: {str(v)[:120]}")

        # christianity today
        print(f"\nCHRISTIANITY TODAY (article 81):")
        for r in results:
            if r.get('article_id') == 81:
                print(f"  registers: {r.get('register', [])}")
                print(f"  explanation: {r.get('register_explanation', 'N/A')}")
                if r.get('novel_frame'):
                    print(f"  novel frame: {r['novel_frame']}")

        # novel frames
        if novel_frames:
            print(f"\nNOVEL FRAMES ({len(novel_frames)}):")
            for r in novel_frames:
                print(f"  article {r['article_id']} ({r.get('country_code', '??')}): {r['novel_frame'][:150]}")

        # geographic pattern of view_from_nowhere
        if vfn_articles:
            vfn_countries = Counter(r.get('country_code', '??') for r in vfn_articles)
            print(f"\nVIEW FROM NOWHERE — GEOGRAPHIC DISTRIBUTION:")
            for cc, count in vfn_countries.most_common():
                print(f"  {cc}: {count}")

        print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
