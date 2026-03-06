#!/usr/bin/env python3
"""
mirror_gap.py — US frame vs. world frame generation.

synthesizes how US media frames an event vs. how the rest of the world does.
produces the 8-word mirror gap display strings and detailed frame summaries.

uses llama-server on boron for synthesis.
stores results in mirror_gap table.
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime

from sqlalchemy import create_engine, text

log = logging.getLogger("mirror_gap")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
LLM_URL = "http://boron:11434"
TIMEOUT = 120


def llm_call(system_prompt, user_prompt):
    """send prompt to llama-server on boron."""
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
                content = msg.get("content", "") or msg.get("reasoning_content", "")
                # strip qwen3 thinking tags
                if "<think>" in content:
                    idx = content.rfind("</think>")
                    if idx >= 0:
                        content = content[idx + len("</think>"):].strip()
                return content
            return ""
    except Exception as e:
        log.error(f"llm call failed: {e}")
        return None


def get_us_frames(conn, event_id):
    """get all framing descriptions for US-sourced articles."""
    rows = conn.execute(text("""
        SELECT a.id, a.title, an.primary_frame, an.positions, s.name as outlet,
               lcv.confidence_level
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        JOIN analyses an ON a.id = an.article_id
        LEFT JOIN llm_council_verdicts lcv ON a.id = lcv.article_id
        WHERE a.event_id = :eid AND s.country_code = 'US'
          AND an.model_used LIKE 'qwen3%%'
          AND an.model_used NOT LIKE '%%session_004%%'
        ORDER BY a.id
    """), {"eid": event_id})
    return [dict(r._mapping) for r in rows]


def get_world_frames(conn, event_id):
    """get all framing descriptions for non-US articles."""
    rows = conn.execute(text("""
        SELECT a.id, a.title, an.primary_frame, an.positions, s.name as outlet,
               s.country_code, lcv.confidence_level
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        JOIN analyses an ON a.id = an.article_id
        LEFT JOIN llm_council_verdicts lcv ON a.id = lcv.article_id
        WHERE a.event_id = :eid AND s.country_code != 'US'
          AND an.model_used LIKE 'qwen3%%'
          AND an.model_used NOT LIKE '%%session_004%%'
        ORDER BY a.id
    """), {"eid": event_id})
    return [dict(r._mapping) for r in rows]


def compute_domestic_ratio(conn, event_id):
    """compute domestic_ratio for US articles using syntactic features."""
    rows = conn.execute(text("""
        SELECT sf.article_id, sf.opening_subject, sf.direct_quotes_by_actor
        FROM syntactic_features sf
        JOIN articles a ON sf.article_id = a.id
        JOIN sources s ON a.source_id = s.id
        WHERE a.event_id = :eid AND s.country_code = 'US'
    """), {"eid": event_id})

    ratios = []
    for r in rows:
        quotes = r.direct_quotes_by_actor or {}
        us_quotes = quotes.get("us_israeli_official", 0) + quotes.get("unnamed_official", 0)
        iran_quotes = quotes.get("iranian_official", 0) + quotes.get("international", 0)
        total = us_quotes + iran_quotes
        if total > 0:
            ratios.append(us_quotes / total)

    return sum(ratios) / len(ratios) if ratios else 0.0


def synthesize_frame(frames, label):
    """use LLM to synthesize a frame summary from multiple articles."""
    frame_texts = []
    for f in frames[:30]:  # cap at 30 to fit context
        outlet = f.get('outlet', '?')
        frame = f.get('primary_frame', '')[:200]
        cc = f.get('country_code', '')
        frame_texts.append(f"[{outlet} ({cc})]: {frame}")

    frame_block = "\n".join(frame_texts)

    system = """You are a media analyst synthesizing how a group of outlets collectively frame an event.
Output EXACTLY this JSON format, nothing else:
{
  "summary": "3-4 sentence synthesis of what this group of outlets collectively says about the event",
  "eight_words": "exactly 8 words capturing the core frame",
  "absent_subjects": ["list of affected parties who never appear as subjects in this coverage"]
}"""

    user = f"""These are the framing descriptions from {label} coverage of a geopolitical event.
Synthesize what they collectively say — not individual outlets, but the aggregate frame.

{frame_block}"""

    raw = llm_call(system, user)
    if not raw:
        return None

    # parse JSON
    try:
        # strip markdown fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
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


def generate_mirror_gap(event_id, run_id):
    """generate the mirror gap: US frame vs. world frame."""
    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        # check existing
        existing = conn.execute(text(
            "SELECT count(*) FROM mirror_gap WHERE event_id = :eid"
        ), {"eid": event_id})
        # we allow multiple runs — additive only

        us_frames = get_us_frames(conn, event_id)
        world_frames = get_world_frames(conn, event_id)

        log.info(f"mirror gap: {len(us_frames)} US frames, {len(world_frames)} world frames")

        if not us_frames or not world_frames:
            log.warning("insufficient data for mirror gap")
            return {"error": "insufficient data"}

        # compute domestic ratio
        domestic_ratio = compute_domestic_ratio(conn, event_id)
        log.info(f"domestic ratio: {domestic_ratio:.2f}")

        # synthesize frames
        log.info("synthesizing US frame...")
        us_synthesis = synthesize_frame(us_frames, "US media")

        log.info("synthesizing world frame...")
        world_synthesis = synthesize_frame(world_frames, "non-US global media")

        if not us_synthesis or not world_synthesis:
            log.error("frame synthesis failed")
            return {"error": "synthesis failed"}

        # write to DB
        conn.execute(text("""
            INSERT INTO mirror_gap
                (event_id, us_frame, world_frame, delta_score,
                 us_domestic_ratio, us_sources_count, world_sources_count)
            VALUES
                (:eid, :us_frame, :world_frame, :delta,
                 :ratio, :us_count, :world_count)
        """), {
            'eid': event_id,
            'us_frame': json.dumps(us_synthesis),
            'world_frame': json.dumps(world_synthesis),
            'delta': domestic_ratio,  # store domestic ratio as delta for now
            'ratio': domestic_ratio,
            'us_count': len(us_frames),
            'world_count': len(world_frames),
        })
        conn.commit()

        log.info(f"\nMIRROR GAP GENERATED:")
        log.info(f"  US:    {us_synthesis.get('eight_words', 'N/A')}")
        log.info(f"  WORLD: {world_synthesis.get('eight_words', 'N/A')}")

        return {
            "us_frame": us_synthesis,
            "world_frame": world_synthesis,
            "domestic_ratio": domestic_ratio,
            "us_sources": len(us_frames),
            "world_sources": len(world_frames),
        }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    import sys
    event_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    run_id = f"mirror_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    result = generate_mirror_gap(event_id, run_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
