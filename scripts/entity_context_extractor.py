#!/usr/bin/env python3
"""
entity_context_extractor.py — extract entity-level involvement context from articles.

goes beyond article-level framing to extract PER-ENTITY details:
  - involvement level (name-drop → meeting → money → travel → facilitation → complicity)
  - timeline (pre/post conviction, post files release)
  - money flow (amount, direction, what it funded)
  - knowledge (when did they know, what did they do)

runs against any event corpus. uses LLM for context extraction.

usage:
  python3 scripts/entity_context_extractor.py --event-id 5 --llm-url http://boron:11434
  python3 scripts/entity_context_extractor.py --event-id 6 --llm-url http://localhost:11436
  python3 scripts/entity_context_extractor.py --event-id 5 --llm-url http://boron:11434 --limit 50
  python3 scripts/entity_context_extractor.py --status --event-id 5
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
LLM_TIMEOUT = 180

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/entity_context.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("entity_ctx")

# ── the entity context extraction prompt ─────────────────────────
ENTITY_CONTEXT_PROMPT = """You are analyzing a news article about the Jeffrey Epstein scandal, specifically focusing on intellectuals, academics, scientists, doctors, and spiritual figures connected to Epstein.

For EACH named person in the article who is an intellectual/academic/scientist/doctor/guru, extract their involvement context. Return JSON only, no explanation.

{{
  "entities": [
    {{
      "name": "Full Name",
      "role": "their professional role (e.g. 'Harvard mathematics professor', 'wellness author')",
      "institution": "primary institution",
      "involvement_level": "one of: name_drop | social_contact | received_funding | visited_properties | facilitated_access | deep_complicity",
      "involvement_details": "specific description of what the article says about their connection",
      "money": {{
        "received": true/false,
        "amount": "$X" or "unknown" or null,
        "source": "direct from Epstein / Epstein foundation / intermediary",
        "what_funded": "research program / personal / institution / foundation"
      }},
      "timeline": {{
        "relationship_period": "e.g. 2002-2019",
        "post_conviction_contact": true/false,
        "when_knew_about_crimes": "before conviction / at conviction / denied knowledge"
      }},
      "consequences": "what happened to them (resigned, suspended, denied, nothing)",
      "institutional_response": "what their institution did (investigated, covered up, returned money, nothing)",
      "direct_quotes": ["any direct quotes from or about this person in the article"]
    }}
  ],
  "article_framing": "how the article frames intellectual involvement (sympathetic / critical / neutral / investigative)",
  "systemic_analysis": true/false,
  "systemic_details": "does the article analyze WHY intellectuals tolerated Epstein, or just report individual cases?"
}}

Only include entities who are intellectuals/academics/scientists/doctors/spiritual figures.
Do NOT include politicians, financiers, or legal figures unless they are also academics.
If the article mentions no relevant intellectual entities, return {{"entities": [], "article_framing": "not_applicable"}}.

Article text:
{article_text}"""


def get_conn():
    return psycopg2.connect(DB_URL)


def llm_call(llm_url, prompt, timeout=LLM_TIMEOUT):
    """call LLM for entity context extraction."""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{llm_url}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            choices = result.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("content", "") or msg.get("reasoning_content", "")
    except Exception as e:
        log.error(f"llm call failed: {e}")
    return None


def parse_json_response(raw):
    """extract JSON from LLM response."""
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass
    return None


def create_tables():
    """create entity_context table if needed."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS epstein_entity_contexts (
            id SERIAL PRIMARY KEY,
            article_id INTEGER REFERENCES articles(id),
            entity_name TEXT NOT NULL,
            entity_role TEXT,
            institution TEXT,
            involvement_level TEXT,
            involvement_details TEXT,
            money_received BOOLEAN,
            money_amount TEXT,
            money_source TEXT,
            money_funded TEXT,
            post_conviction_contact BOOLEAN,
            consequences TEXT,
            institutional_response TEXT,
            direct_quotes JSONB,
            article_framing TEXT,
            systemic_analysis BOOLEAN,
            raw_extraction JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(article_id, entity_name)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_entity_ctx_name ON epstein_entity_contexts(entity_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_entity_ctx_article ON epstein_entity_contexts(article_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_entity_ctx_level ON epstein_entity_contexts(involvement_level)")
    conn.commit()
    cur.close()
    conn.close()
    log.info("entity_context tables ready")


def get_articles_to_process(event_id, limit=None):
    """get articles that have media mentions but no entity context yet."""
    conn = get_conn()
    cur = conn.cursor()

    # get articles that mention intellectual entities (from epstein_media_mentions)
    # OR articles from the intellectual corpus (event_id=6)
    cur.execute("""
        SELECT DISTINCT a.id, a.title, COALESCE(a.translated_text, a.raw_text, '') as text
        FROM articles a
        WHERE a.event_id = %s
          AND (a.translated_text IS NOT NULL OR a.raw_text IS NOT NULL)
          AND a.id NOT IN (SELECT DISTINCT article_id FROM epstein_entity_contexts)
        ORDER BY a.id
    """, (event_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if limit:
        rows = rows[:limit]
    return rows


def process_article(llm_url, article_id, title, text):
    """extract entity contexts from a single article."""
    prompt = ENTITY_CONTEXT_PROMPT.replace("{article_text}", text[:4000])
    raw = llm_call(llm_url, prompt)

    if raw is None:
        # retry once
        time.sleep(3)
        raw = llm_call(llm_url, prompt)

    if raw is None:
        return None

    parsed = parse_json_response(raw)
    return parsed


def write_contexts(article_id, extraction, article_framing):
    """write extracted entity contexts to DB."""
    if not extraction or not extraction.get("entities"):
        return 0

    conn = get_conn()
    cur = conn.cursor()
    written = 0

    for entity in extraction["entities"]:
        name = entity.get("name", "").strip()
        if not name:
            continue

        money = entity.get("money", {}) or {}
        timeline = entity.get("timeline", {}) or {}

        try:
            cur.execute("""
                INSERT INTO epstein_entity_contexts
                    (article_id, entity_name, entity_role, institution,
                     involvement_level, involvement_details,
                     money_received, money_amount, money_source, money_funded,
                     post_conviction_contact, consequences, institutional_response,
                     direct_quotes, article_framing, systemic_analysis, raw_extraction)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (article_id, entity_name) DO NOTHING
            """, (
                article_id,
                name,
                entity.get("role"),
                entity.get("institution"),
                entity.get("involvement_level"),
                entity.get("involvement_details"),
                money.get("received"),
                money.get("amount"),
                money.get("source"),
                money.get("what_funded"),
                timeline.get("post_conviction_contact"),
                entity.get("consequences"),
                entity.get("institutional_response"),
                json.dumps(entity.get("direct_quotes", [])),
                extraction.get("article_framing"),
                extraction.get("systemic_analysis", False),
                json.dumps(entity),
            ))
            written += 1
        except Exception as e:
            conn.rollback()
            log.warning(f"  write error for {name}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    return written


def show_status(event_id):
    """show entity context extraction status."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT entity_name, involvement_level, COUNT(*) as articles,
               COUNT(CASE WHEN money_received THEN 1 END) as money_articles,
               COUNT(CASE WHEN post_conviction_contact THEN 1 END) as post_conviction
        FROM epstein_entity_contexts ec
        JOIN articles a ON ec.article_id = a.id
        WHERE a.event_id = %s
        GROUP BY entity_name, involvement_level
        ORDER BY articles DESC
    """, (event_id,))
    rows = cur.fetchall()

    if not rows:
        print("  no entity contexts extracted yet")
        cur.close()
        conn.close()
        return

    print(f"\n{'='*80}")
    print(f"ENTITY CONTEXT EXTRACTION — event_id={event_id}")
    print(f"{'='*80}")
    print(f"{'Name':25s} {'Level':20s} {'Articles':>8s} {'Money':>6s} {'Post-Conv':>10s}")
    print(f"{'-'*80}")

    # aggregate by name
    by_name = {}
    for name, level, articles, money, post_conv in rows:
        if name not in by_name:
            by_name[name] = {"levels": {}, "total": 0, "money": 0, "post_conv": 0}
        by_name[name]["levels"][level] = articles
        by_name[name]["total"] += articles
        by_name[name]["money"] += money
        by_name[name]["post_conv"] += post_conv

    for name in sorted(by_name.keys(), key=lambda n: -by_name[n]["total"]):
        info = by_name[name]
        top_level = max(info["levels"].keys(), key=lambda l: info["levels"][l])
        print(f"  {name:25s} {top_level:20s} {info['total']:8d} {info['money']:6d} {info['post_conv']:10d}")

    # involvement level distribution
    cur.execute("""
        SELECT involvement_level, COUNT(*) FROM epstein_entity_contexts ec
        JOIN articles a ON ec.article_id = a.id
        WHERE a.event_id = %s
        GROUP BY involvement_level ORDER BY count DESC
    """, (event_id,))
    print(f"\n  involvement level distribution:")
    for level, count in cur.fetchall():
        print(f"    {level:25s}: {count}")

    # systemic analysis articles
    cur.execute("""
        SELECT COUNT(DISTINCT ec.article_id) FROM epstein_entity_contexts ec
        JOIN articles a ON ec.article_id = a.id
        WHERE a.event_id = %s AND ec.systemic_analysis = true
    """, (event_id,))
    systemic = cur.fetchone()[0]
    print(f"\n  articles with systemic analysis: {systemic}")

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="extract entity-level involvement context")
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--llm-url", type=str, default="http://boron:11434")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    create_tables()

    if args.status:
        show_status(args.event_id)
        return

    articles = get_articles_to_process(args.event_id, args.limit)
    log.info(f"processing {len(articles)} articles for entity context (event_id={args.event_id})")

    if not articles:
        log.info("nothing to process")
        return

    success = 0
    entities_found = 0
    failures = 0

    for i, (article_id, title, text) in enumerate(articles):
        log.info(f"  [{i+1}/{len(articles)}] {title[:60]}...")

        extraction = process_article(args.llm_url, article_id, title, text)

        if extraction is None:
            failures += 1
            log.warning(f"    FAILED")
            continue

        n_entities = len(extraction.get("entities", []))
        if n_entities > 0:
            written = write_contexts(article_id, extraction, extraction.get("article_framing"))
            entities_found += written
            log.info(f"    {n_entities} entities, {written} written, framing: {extraction.get('article_framing')}")
        else:
            log.info(f"    no intellectual entities")

        success += 1

        if (i + 1) % 20 == 0:
            log.info(f"    checkpoint: {success} ok, {failures} fail, {entities_found} entities")

        time.sleep(0.5)

    log.info(f"\n{'='*60}")
    log.info(f"ENTITY CONTEXT EXTRACTION COMPLETE")
    log.info(f"  articles processed: {success}/{len(articles)}")
    log.info(f"  failures: {failures}")
    log.info(f"  entity contexts extracted: {entities_found}")
    log.info(f"{'='*60}")

    show_status(args.event_id)


if __name__ == "__main__":
    main()
