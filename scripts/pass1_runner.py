#!/usr/bin/env python3
"""
pass1_runner.py — standalone Pass 1 analysis runner.

runs per-article framing extraction against any LLM endpoint.
reads articles from DB, writes analyses to DB. skips already-analyzed articles.

usage:
  python3 scripts/pass1_runner.py --event-id 4 --llm-url http://localhost:11435
  python3 scripts/pass1_runner.py --event-id 4 --llm-url http://boron:11434
  python3 scripts/pass1_runner.py --event-id 4 --llm-url http://localhost:11435 --limit 5
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import logging
import time
import urllib.request
import urllib.error

from db import get_session, Article, Analysis, Event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/pass1_runner.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("pass1")

LLM_TIMEOUT = 180

# country contexts for bias compensation
COUNTRY_CONTEXTS_FILE = "country_contexts.json"

PASS1_PROMPT = """You are analyzing a news article about {event_context}.

{country_context}

Describe how this article frames this event. Do NOT use predefined political categories.
Instead, answer these questions using the article's own conceptual vocabulary:

1. AUTHORITY: Who does this article treat as having legitimate authority to act? Who is implicitly denied legitimacy?
2. HISTORY: What historical context does the article invoke? What does it assume the reader already knows?
3. RESPONSE: What does the article present as the appropriate response to the situation? What responses are implicitly ruled out?
4. ASSUMPTIONS: What unstated assumptions underlie the article's framing? What would someone from a completely different political tradition notice as strange or arbitrary?
5. SOURCES: Who is quoted or cited? Whose voice is absent?
6. TENSION: Does the article hold positions that are in tension with each other? (e.g., invoking sovereignty principles while supporting selective intervention, or endorsing diplomacy while naturalizing military buildup)

Also extract:
7. FACTUAL CLAIMS: List specific verifiable claims.
8. ABSENCE: What obviously relevant frames, actors, or contexts does this article NOT engage with at all?
9. KEY LANGUAGE: 3-5 specific words or phrases (in English, from the translated text) that most reveal the frame.

Output JSON:
{{
  "framing_description": "2-4 sentences describing how this article frames the event, using the article's own conceptual vocabulary — not external political labels",
  "authority_structure": "who is granted/denied legitimacy to act",
  "historical_context_invoked": ["specific historical events or periods referenced"],
  "assumed_appropriate_response": "what the article implies should happen",
  "unstated_assumptions": ["assumptions a reader from a different tradition would notice"],
  "who_is_quoted": ["authorities cited"],
  "whose_voice_is_absent": ["relevant actors not quoted or referenced"],
  "internal_tensions": "describe any contradictions within the article's own framing, or null if coherent",
  "factual_claims": ["specific verifiable claims"],
  "absence_flags": ["frames or contexts the article does not engage with"],
  "key_framing_language": ["3-5 English words/phrases that reveal the frame"],
  "one_sentence_summary": "single sentence capturing this outlet's essential position"
}}

IMPORTANT: Output ONLY valid JSON, no other text.

Article:
{article_text}"""


def llm_generate(llm_url, prompt, timeout=LLM_TIMEOUT):
    """send a prompt to llama-server, return response text."""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 3072,
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
                content = msg.get("content", "")
                if content:
                    return content
                return msg.get("reasoning_content", "")
            return ""
    except Exception as e:
        log.error(f"  llm call failed: {e}")
        return None


def parse_llm_json(raw):
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
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass
    return None


def write_analysis_to_db(session, article_id, event_id, model_name, analysis_data):
    """write analysis record to DB."""
    positions = analysis_data.get("key_framing_language", [])
    tension_text = analysis_data.get("internal_tensions")
    internal_tensions = []
    if tension_text:
        internal_tensions = [{"description": tension_text}] if isinstance(tension_text, str) else tension_text

    unspeakable = []
    for v in analysis_data.get("whose_voice_is_absent", []):
        unspeakable.append(f"voice absent: {v}")

    record = Analysis(
        article_id=article_id,
        event_id=event_id,
        model_used=model_name,
        primary_frame=analysis_data.get("framing_description", analysis_data.get("one_sentence_summary", "")),
        positions=positions,
        internal_tensions=internal_tensions,
        absence_flags=analysis_data.get("absence_flags", []),
        unspeakable_positions=unspeakable,
        raw_llm_output=analysis_data,
    )
    session.add(record)
    return record


def main():
    parser = argparse.ArgumentParser(description="run Pass 1 framing extraction")
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--llm-url", type=str, required=True, help="e.g. http://localhost:11435")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model-name", type=str, default=None,
                        help="model label for DB (auto-detected if not set)")
    args = parser.parse_args()

    session = get_session()

    # get event
    event = session.query(Event).get(args.event_id)
    if not event:
        log.error(f"event_id {args.event_id} not found")
        session.close()
        sys.exit(1)

    event_context = event.prompt_context or event.title or "a major geopolitical event"
    log.info(f"event: {event.title} (id={event.id})")
    log.info(f"prompt context: {event_context}")
    log.info(f"LLM endpoint: {args.llm_url}")

    # detect model name from endpoint
    model_name = args.model_name
    if not model_name:
        try:
            req = urllib.request.Request(f"{args.llm_url}/v1/models")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("data"):
                    model_name = data["data"][0].get("id", "unknown")
        except Exception:
            model_name = "unknown"
    log.info(f"model: {model_name}")

    # load country contexts
    country_contexts = {}
    if os.path.exists(COUNTRY_CONTEXTS_FILE):
        with open(COUNTRY_CONTEXTS_FILE, "r", encoding="utf-8") as f:
            country_contexts = json.load(f)
        log.info(f"loaded context for {len(country_contexts)} countries")

    # find articles needing analysis
    already_analyzed = set()
    for row in session.query(Analysis.article_id).filter_by(event_id=args.event_id).all():
        already_analyzed.add(row.article_id)

    articles = session.query(Article).filter_by(event_id=args.event_id).filter(
        Article.raw_text.isnot(None),
        Article.raw_text != "",
    ).all()

    # filter to unanalyzed
    to_analyze = [a for a in articles if a.id not in already_analyzed]
    if args.limit:
        to_analyze = to_analyze[:args.limit]

    log.info(f"articles: {len(articles)} total, {len(already_analyzed)} already done, {len(to_analyze)} to process")

    if not to_analyze:
        log.info("nothing to do")
        session.close()
        return

    # process
    success = 0
    failures = 0
    consecutive_failures = 0

    for i, article in enumerate(to_analyze):
        log.info(f"  [{i+1}/{len(to_analyze)}] article {article.id} ({article.original_language})...")

        # use translated text if available, else raw
        text = article.translated_text or article.raw_text or ""
        if not text.strip():
            log.warning(f"    empty text, skipping")
            continue

        # get country context
        # try to find country from source
        country_ctx = ""
        if article.source_id:
            from db import Source
            source = session.query(Source).get(article.source_id)
            if source and source.country_code:
                country_ctx = country_contexts.get(source.country_code, "")

        prompt = PASS1_PROMPT.format(
            article_text=text[:3000],
            country_context=country_ctx,
            event_context=event_context,
        )

        raw = llm_generate(args.llm_url, prompt)
        if raw is None:
            # retry once
            log.warning(f"    retrying in 5s...")
            time.sleep(5)
            raw = llm_generate(args.llm_url, prompt)

        if raw is None:
            failures += 1
            consecutive_failures += 1
            log.warning(f"    FAILED after retry")
            if consecutive_failures >= 10:
                log.error(f"  10 consecutive failures, aborting")
                break
            continue

        analysis = parse_llm_json(raw)
        if analysis is None:
            log.warning(f"    JSON parse error, raw: {raw[:200]}")
            failures += 1
            consecutive_failures = 0  # model responding, just bad output
            continue

        # write to DB
        write_analysis_to_db(session, article.id, args.event_id, model_name, analysis)
        success += 1
        consecutive_failures = 0

        # commit every 10 articles
        if (i + 1) % 10 == 0:
            session.commit()
            log.info(f"    checkpoint: {success} success, {failures} failed")

        time.sleep(0.5)

    log.info(f"\n{'='*60}")
    log.info(f"PASS 1 COMPLETE")
    log.info(f"  event: {event.title} (id={event.id})")
    log.info(f"  model: {model_name}")
    log.info(f"  success: {success}/{len(to_analyze)}")
    log.info(f"  failures: {failures}/{len(to_analyze)}")
    log.info(f"{'='*60}")

    session.commit()
    session.close()


if __name__ == "__main__":
    main()
