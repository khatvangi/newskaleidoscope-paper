#!/usr/bin/env python3
"""
pipeline_run.py — production weekly pipeline orchestrator.

single entry point for every weekly run. calls existing proven modules
in sequence with stage tracking, checkpointing, and error recovery.

usage:
  python pipeline_run.py --topic "Iran nuclear" --event-date 2026-03-01 --event-type military
  python pipeline_run.py --event-id 2 --skip-ingest --output-dir docs/events/iran-march-2026
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from sqlalchemy import create_engine, text

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
LLM_URL = "http://boron:11434"

log = logging.getLogger("pipeline_run")


# ── stage definitions ────────────────────────────────────────────

STAGES = [
    "ingest",
    "translate",
    "analyze",
    "syntax",
    "vocabulary",
    "presupposition",
    "cluster",
    "mirror_gap",
    "absence",
    "render",
]


def make_run_id():
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def load_checkpoint(checkpoint_file):
    """load checkpoint to resume from last completed stage."""
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file) as f:
            return json.load(f)
    return {"completed_stages": [], "run_id": None, "event_id": None, "article_ids": []}


def save_checkpoint(checkpoint_file, state):
    with open(checkpoint_file, 'w') as f:
        json.dump(state, f, indent=2)


def stage_complete(state, stage_name, result=None):
    """mark a stage as complete in checkpoint state."""
    state["completed_stages"].append(stage_name)
    if result:
        state.setdefault("stage_results", {})[stage_name] = result
    return state


# ── stage implementations ────────────────────────────────────────

def run_ingest(args, state):
    """stage 1: ingest articles from GDELT + RSS."""
    from pipeline import run_pipeline
    from db import get_session, Event

    db_session = get_session()

    if args.event_id:
        event = db_session.query(Event).get(args.event_id)
        if not event:
            log.error(f"event_id {args.event_id} not found")
            db_session.close()
            return None
        state["event_id"] = event.id
        log.info(f"using existing event: {event.title} (id={event.id})")
    else:
        event = Event(
            title=args.topic,
            event_type=args.event_type,
            event_date=datetime.strptime(args.event_date, "%Y-%m-%d").date(),
        )
        db_session.add(event)
        db_session.commit()
        state["event_id"] = event.id
        log.info(f"created event: {event.title} (id={event.id})")

    # get existing article IDs for this event
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id FROM articles WHERE event_id = :eid ORDER BY id"
        ), {"eid": state["event_id"]})
        state["article_ids"] = [r[0] for r in rows]

    db_session.close()
    log.info(f"event has {len(state['article_ids'])} articles")
    return {"article_count": len(state["article_ids"])}


def run_translate(args, state):
    """stage 2: translate non-english articles."""
    from translate import TranslationEngine

    engine_db = create_engine(DB_URL)
    translator = TranslationEngine(device="cuda")

    with engine_db.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, raw_text, original_language, translated_text
            FROM articles
            WHERE event_id = :eid AND translated_text IS NULL
              AND original_language != 'English'
              AND raw_text IS NOT NULL
            ORDER BY id
        """), {"eid": state["event_id"]})
        to_translate = list(rows)

    if not to_translate:
        log.info("no articles need translation")
        return {"translated": 0}

    translated_count = 0
    with engine_db.connect() as conn:
        for r in to_translate:
            try:
                translated, lang = translator.translate(r.raw_text, source_lang=r.original_language)
                if translated:
                    conn.execute(text(
                        "UPDATE articles SET translated_text = :txt WHERE id = :aid"
                    ), {"txt": translated, "aid": r.id})
                    translated_count += 1
                    log.info(f"  translated article {r.id} ({r.original_language})")
            except Exception as e:
                log.warning(f"  translation failed for article {r.id}: {e}")
        conn.commit()

    log.info(f"translated {translated_count} articles")
    return {"translated": translated_count}


def run_analyze(args, state):
    """stage 3: LLM council analysis (two-pass)."""
    from council import LLMCouncil

    # check if council already ran for these articles
    engine_db = create_engine(DB_URL)
    with engine_db.connect() as conn:
        existing = conn.execute(text(
            "SELECT count(*) FROM llm_council_verdicts WHERE article_id = ANY(:aids)"
        ), {"aids": state["article_ids"]})
        count = existing.fetchone()[0]

    if count >= len(state["article_ids"]):
        log.info(f"council already ran for all {count} articles — skipping")
        return {"verdicts": count, "skipped": True}

    model_names = None
    if args.council_models:
        model_names = [m.strip() for m in args.council_models.split(",")]

    council = LLMCouncil(model_names=model_names)
    council.run_council(state["event_id"])
    return {"verdicts": len(state["article_ids"])}


def run_syntax(args, state):
    """stage 4: spaCy syntactic analysis."""
    from syntax_analyzer import analyze_article, load_nlp, get_articles, write_results

    engine_db = create_engine(DB_URL)

    # check if already ran
    with engine_db.connect() as conn:
        existing = conn.execute(text(
            "SELECT count(*) FROM syntactic_features WHERE run_id = :rid"
        ), {"rid": state["run_id"]})
        if existing.fetchone()[0] > 0:
            log.info("syntactic analysis already ran for this run_id — skipping")
            return {"skipped": True}

    nlp = load_nlp()

    with engine_db.connect() as conn:
        articles = get_articles(conn)
        results = []
        for i, art in enumerate(articles):
            log.info(f"  syntax [{i+1}/{len(articles)}] article {art['id']}")
            result = analyze_article(nlp, art)
            results.append(result)

        # override run_id to current run
        for r in results:
            if r:
                r['run_id'] = state['run_id']

        success = write_results(conn, results)

    log.info(f"syntactic analysis: {success} articles")
    return {"analyzed": success}


def run_vocabulary(args, state):
    """stage 5: vocabulary asymmetry analysis."""
    from vocabulary_asymmetry import analyze_article as vocab_analyze, load_nlp, get_articles, write_results

    engine_db = create_engine(DB_URL)

    with engine_db.connect() as conn:
        existing = conn.execute(text(
            "SELECT count(*) FROM actor_framing WHERE run_id = :rid"
        ), {"rid": state["run_id"]})
        if existing.fetchone()[0] > 0:
            log.info("vocabulary analysis already ran — skipping")
            return {"skipped": True}

    nlp = load_nlp()

    with engine_db.connect() as conn:
        articles = get_articles(conn)
        all_results = []
        for i, art in enumerate(articles):
            log.info(f"  vocab [{i+1}/{len(articles)}] article {art['id']}")
            results = vocab_analyze(nlp, art)
            # override run_id
            for r in results:
                r['run_id'] = state['run_id']
            all_results.extend(results)

        success = write_results(conn, all_results)

    log.info(f"vocabulary analysis: {success} actor-framing rows")
    return {"rows": success}


def run_presupposition(args, state):
    """stage 6: presupposition extraction on targeted articles."""
    # only run on US articles + high-ambiguity contested articles
    engine_db = create_engine(DB_URL)
    with engine_db.connect() as conn:
        existing = conn.execute(text(
            "SELECT count(*) FROM presuppositions WHERE run_id = :rid"
        ), {"rid": state["run_id"]})
        if existing.fetchone()[0] > 0:
            log.info("presupposition extraction already ran — skipping")
            return {"skipped": True}

        # find US articles
        us = conn.execute(text("""
            SELECT a.id FROM articles a
            JOIN sources s ON a.source_id = s.id
            WHERE a.event_id = :eid AND s.country_code = 'US'
        """), {"eid": state["event_id"]})
        target_ids = [r[0] for r in us]

        # find top contested by ambiguity score
        contested = conn.execute(text("""
            SELECT sf.article_id
            FROM syntactic_features sf
            JOIN llm_council_verdicts lcv ON sf.article_id = lcv.article_id
            WHERE sf.run_id = :rid AND lcv.confidence_level = 'contested'
              AND sf.severe_tokenism_flag = false
            ORDER BY (sf.passive_voice_ratio * 0.3 + sf.attribution_rate * 0.3 +
                      LEAST(COALESCE(sf.elaboration_ratio, 1.0) / 10.0, 1.0) * 0.4) DESC
            LIMIT 15
        """), {"rid": state["run_id"]})
        for r in contested:
            if r[0] not in target_ids:
                target_ids.append(r[0])

    if not target_ids:
        log.info("no target articles for presupposition extraction")
        return {"extracted": 0}

    log.info(f"presupposition targets: {len(target_ids)} articles")

    from presupposition_extractor import llm_call, parse_json_array, SYSTEM_PROMPT
    import json as _json

    with engine_db.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, translated_text, raw_text FROM articles
            WHERE id = ANY(:aids)
        """), {"aids": target_ids})

        total = 0
        for r in rows:
            article_text = r.translated_text or r.raw_text or ""
            if len(article_text.strip()) < 50:
                continue
            raw = llm_call(article_text)
            parsed = parse_json_array(raw)
            if parsed:
                for p in parsed:
                    conn.execute(text("""
                        INSERT INTO presuppositions
                            (article_id, run_id, presupposition, carrier_phrase,
                             favors_actor, consistency_check, would_be_contested_by)
                        VALUES (:aid, :rid, :presup, :carrier, :favors, :check, :contested)
                    """), {
                        'aid': r.id, 'rid': state['run_id'],
                        'presup': p.get('presupposition', ''),
                        'carrier': p.get('carrier_phrase', ''),
                        'favors': p.get('favors_actor', ''),
                        'check': p.get('consistency_check', ''),
                        'contested': p.get('would_be_contested_by', ''),
                    })
                    total += 1
                log.info(f"  article {r.id}: {len(parsed)} presuppositions")
        conn.commit()

    return {"extracted": total}


def run_cluster(args, state):
    """stage 7: LLM Pass 2 emergent clustering."""
    # uses pipeline.py's pass2_cluster
    log.info("clustering uses council Pass 2 from analyze stage — checking existing clusters")
    engine_db = create_engine(DB_URL)
    with engine_db.connect() as conn:
        existing = conn.execute(text(
            "SELECT count(*) FROM clusters WHERE event_id = :eid AND valid = true"
        ), {"eid": state["event_id"]})
        count = existing.fetchone()[0]

    if count > 0:
        log.info(f"found {count} valid clusters — skipping")
        return {"clusters": count, "skipped": True}

    log.info("no valid clusters found — would run Pass 2 here")
    return {"clusters": 0, "note": "manual clustering needed"}


def run_mirror_gap(args, state):
    """stage 8: US frame vs world frame."""
    from mirror_gap import generate_mirror_gap
    result = generate_mirror_gap(state["event_id"], state["run_id"])
    return result


def run_absence(args, state):
    """stage 9: absence report."""
    from absence_report import generate_absence_report
    result = generate_absence_report(state["event_id"], state["run_id"])
    return result


def run_render(args, state):
    """stage 10: HTML output generation."""
    from render import render_event_page
    output_dir = args.output_dir or f"docs/events/{args.topic.lower().replace(' ', '-')}"
    result = render_event_page(state["event_id"], state["run_id"], output_dir)
    return result


# ── main orchestrator ────────────────────────────────────────────

STAGE_RUNNERS = {
    "ingest": run_ingest,
    "translate": run_translate,
    "analyze": run_analyze,
    "syntax": run_syntax,
    "vocabulary": run_vocabulary,
    "presupposition": run_presupposition,
    "cluster": run_cluster,
    "mirror_gap": run_mirror_gap,
    "absence": run_absence,
    "render": run_render,
}


def run_pipeline(args):
    """run the full production pipeline with stage tracking."""
    run_id = make_run_id()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # setup logging
    os.makedirs("logs", exist_ok=True)
    log_file = f"logs/run_{timestamp}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ],
    )

    checkpoint_file = f"logs/run_{timestamp}_checkpoint.json"
    state = load_checkpoint(checkpoint_file)
    state["run_id"] = run_id
    state["timestamp"] = timestamp
    state["topic"] = args.topic
    state["event_type"] = args.event_type

    log.info(f"{'=' * 60}")
    log.info(f"NEWSKALEIDOSCOPE PIPELINE RUN")
    log.info(f"  run_id: {run_id}")
    log.info(f"  topic: {args.topic}")
    log.info(f"  event_type: {args.event_type}")
    log.info(f"  event_date: {args.event_date}")
    log.info(f"{'=' * 60}")

    # determine which stages to run
    stages_to_run = list(STAGES)

    if args.skip_ingest:
        stages_to_run = [s for s in stages_to_run if s != "ingest"]
        # still need to set event_id
        if args.event_id:
            state["event_id"] = args.event_id
            engine_db = create_engine(DB_URL)
            with engine_db.connect() as conn:
                rows = conn.execute(text(
                    "SELECT id FROM articles WHERE event_id = :eid ORDER BY id"
                ), {"eid": args.event_id})
                state["article_ids"] = [r[0] for r in rows]
            log.info(f"using existing event {args.event_id} with {len(state['article_ids'])} articles")

    # skip already-completed stages (resume support)
    completed = set(state.get("completed_stages", []))
    stages_to_run = [s for s in stages_to_run if s not in completed]

    if not stages_to_run:
        log.info("all stages already completed")
        return state

    log.info(f"stages to run: {stages_to_run}")

    # run each stage
    for stage in stages_to_run:
        runner = STAGE_RUNNERS.get(stage)
        if not runner:
            log.warning(f"no runner for stage: {stage}")
            continue

        log.info(f"\n{'─' * 60}")
        log.info(f"STAGE: {stage}")
        log.info(f"{'─' * 60}")

        start = time.time()
        try:
            result = runner(args, state)
            elapsed = time.time() - start
            log.info(f"  completed in {elapsed:.1f}s: {result}")
            state = stage_complete(state, stage, result)
            save_checkpoint(checkpoint_file, state)
        except Exception as e:
            elapsed = time.time() - start
            log.error(f"  FAILED after {elapsed:.1f}s: {e}")
            import traceback
            log.error(traceback.format_exc())
            state.setdefault("stage_results", {})[stage] = {"error": str(e)}
            save_checkpoint(checkpoint_file, state)
            # continue to next stage — don't halt pipeline
            continue

    # final summary
    log.info(f"\n{'=' * 60}")
    log.info(f"PIPELINE COMPLETE")
    log.info(f"  run_id: {run_id}")
    log.info(f"  stages completed: {state.get('completed_stages', [])}")
    log.info(f"  results: {state.get('stage_results', {})}")
    log.info(f"{'=' * 60}")

    return state


def main():
    parser = argparse.ArgumentParser(description="NewsKaleidoscope production pipeline")
    parser.add_argument("--topic", default="", help="search terms for GDELT + RSS")
    parser.add_argument("--event-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--event-type", default="military",
                        choices=["military", "election", "economic", "disaster", "diplomatic"])
    parser.add_argument("--event-id", type=int, help="use existing event ID")
    parser.add_argument("--weeks-back", type=int, default=1)
    parser.add_argument("--output-dir", help="HTML output directory")
    parser.add_argument("--skip-ingest", action="store_true", help="skip article ingestion")
    parser.add_argument("--skip-tier3", action="store_true", help="skip YouTube/podcast/Whisper")
    parser.add_argument("--council-models", help="comma-separated model list")
    parser.add_argument("--dry-run", action="store_true", help="report counts without LLM")
    args = parser.parse_args()

    if not args.topic and not args.event_id:
        parser.error("either --topic or --event-id required")

    run_pipeline(args)


if __name__ == "__main__":
    main()
