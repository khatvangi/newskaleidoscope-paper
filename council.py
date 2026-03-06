#!/usr/bin/env python3
"""
council.py — multi-model LLM council for epistemic analysis validation.

three models with distinct training lineages analyze each article independently.
consensus logic determines confidence level: high/medium/contested.
sequential model loading via llama-server (one model at a time on boron).

model lineup:
  1. qwen3:32b (Alibaba) — strong on Asian/ME political text
  2. gemma-3-27b-it (Google) — distinct training corpus
  3. mistral-small-3.1-24b (Mistral) — European emphasis, diplomatic register
"""

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime

from db import (
    get_session, Article, Analysis, LLMCouncilVerdict, Cluster,
    ClusterMembership, Event
)

log = logging.getLogger("council")

# ── config ────────────────────────────────────────────────────────
BORON_HOST = "boron"
LLAMA_SERVER_PORT = 11434
LLAMA_SERVER_BIN = "/storage/kiran-stuff/llama.cpp/build/bin/llama-server"
MODEL_DIR = "/storage/kiran-stuff/llama.cpp/models"
LLM_URL = f"http://{BORON_HOST}:{LLAMA_SERVER_PORT}"
TIMEOUT = 120  # seconds per model call

# model registry: name -> gguf filename on boron
MODELS = {
    "qwen3:32b": "qwen3-32b-q4km.gguf",
    "gemma-3-27b-it": "google_gemma-3-27b-it-Q4_K_M.gguf",
    "mistral-small-3.1-24b": "Mistral-Small-3.1-24B-Instruct-2503-Q4_K_M.gguf",
}

# ── council prompt (identical for all models) ─────────────────────
COUNCIL_SYSTEM_PROMPT = """You are an analyst mapping epistemic frames in global media.
Analyze the article and extract the following as JSON only.
No preamble. No explanation. JSON only.
Do not reference what other analysts might conclude.
Analyze only what is in the text.

{
  "primary_frame": "one sentence describing the dominant frame",
  "positions": ["array", "of", "positions", "taken"],
  "absence_flags": ["what is notably absent from this text"],
  "internal_tensions": ["contradictions held within the article"],
  "unspeakable_positions": ["positions the article cannot state directly"],
  "confidence_score": 0.0-1.0,
  "frame_category": "justified_action|illegal_escalation|diplomatic|self_defense|humanitarian|economic|other"
}"""


@dataclass
class CouncilVerdict:
    article_id: int
    confidence_level: str  # high/medium/contested
    consensus_frame: str  # or empty string if contested
    model_readings: dict = field(default_factory=dict)
    positions_union: list = field(default_factory=list)
    absence_flags_union: list = field(default_factory=list)
    internal_tensions_union: list = field(default_factory=list)
    dissenting_model: str = field(default=None)


# ── llama-server management ──────────────────────────────────────
def _ssh_cmd(cmd):
    """run a command on boron via ssh, return stdout."""
    result = subprocess.run(
        ["ssh", BORON_HOST, cmd],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip(), result.returncode


def stop_llama_server():
    """kill any running llama-server on boron."""
    out, _ = _ssh_cmd("pgrep -f llama-server")
    if out:
        for pid in out.split("\n"):
            pid = pid.strip()
            if pid:
                _ssh_cmd(f"kill {pid}")
                log.info(f"  killed llama-server pid {pid}")
        time.sleep(2)


def start_llama_server(model_name):
    """start llama-server on boron with the specified model."""
    gguf = MODELS.get(model_name)
    if not gguf:
        raise ValueError(f"unknown model: {model_name}")

    model_path = f"{MODEL_DIR}/{gguf}"

    # check model file exists
    out, rc = _ssh_cmd(f"test -f {model_path} && echo exists")
    if "exists" not in out:
        raise FileNotFoundError(f"GGUF not found on boron: {model_path}")

    stop_llama_server()

    cmd = (
        f"nohup {LLAMA_SERVER_BIN} "
        f"--model {model_path} "
        f"--tensor-split 0.5,0.5 "
        f"--host 0.0.0.0 --port {LLAMA_SERVER_PORT} "
        f"--ctx-size 16384 --n-gpu-layers 99 "
        f"> /tmp/llama-server.log 2>&1 &"
    )
    _ssh_cmd(cmd)
    log.info(f"  starting llama-server with {model_name} ({gguf})...")

    # wait for server to be ready
    for attempt in range(30):
        time.sleep(2)
        try:
            req = urllib.request.Request(f"{LLM_URL}/v1/models")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("data"):
                    loaded = data["data"][0].get("id", "unknown")
                    log.info(f"  llama-server ready: {loaded}")
                    return loaded
        except Exception:
            pass

    raise TimeoutError(f"llama-server failed to start with {model_name} after 60s")


def llm_call(prompt, timeout=TIMEOUT):
    """send a prompt to the running llama-server, return response text."""
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": COUNCIL_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
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


def parse_council_json(raw):
    """extract JSON from council member response."""
    if not raw:
        return None
    cleaned = raw.strip()
    # strip markdown fences
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    # try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # try finding JSON object
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass
    return None


# ── semantic similarity for consensus ────────────────────────────
_sim_model = None

def get_similarity_model():
    """lazy-load sentence-transformers model for consensus measurement."""
    global _sim_model
    if _sim_model is None:
        from sentence_transformers import SentenceTransformer
        _sim_model = SentenceTransformer("all-MiniLM-L6-v2")
        log.info("  loaded sentence similarity model: all-MiniLM-L6-v2")
    return _sim_model


def compute_similarity(text_a, text_b):
    """compute semantic similarity between two frame descriptions."""
    if not text_a or not text_b:
        return 0.0
    model = get_similarity_model()
    embeddings = model.encode([text_a, text_b])
    # cosine similarity
    import numpy as np
    a, b = embeddings[0], embeddings[1]
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ── consensus logic ──────────────────────────────────────────────
SIMILARITY_THRESHOLD = 0.82

def determine_consensus(readings):
    """determine consensus across model readings.

    readings: dict of model_name -> parsed JSON output

    returns: (confidence_level, consensus_frame, dissenting_model)
    """
    valid = {k: v for k, v in readings.items() if v is not None}
    if len(valid) < 2:
        # can't determine consensus with < 2 valid readings
        if len(valid) == 1:
            model_name, data = list(valid.items())[0]
            return ("low", data.get("primary_frame", ""), None)
        return ("failed", "", None)

    model_names = list(valid.keys())
    frames = {k: v.get("primary_frame", "") for k, v in valid.items()}

    # compute pairwise similarity
    pairs = {}
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            a, b = model_names[i], model_names[j]
            sim = compute_similarity(frames[a], frames[b])
            pairs[(a, b)] = sim
            log.info(f"    similarity {a} <-> {b}: {sim:.3f}")

    # check for all-agree
    all_above = all(s >= SIMILARITY_THRESHOLD for s in pairs.values())
    if all_above and len(valid) >= 3:
        # pick frame from highest confidence model
        best_model = max(valid.keys(),
                         key=lambda k: valid[k].get("confidence_score", 0))
        return ("high", frames[best_model], None)

    # check for 2-of-3 agreement
    if len(valid) >= 3:
        for (a, b), sim in pairs.items():
            if sim >= SIMILARITY_THRESHOLD:
                # a and b agree, find the dissenter
                dissenter = [m for m in model_names if m != a and m != b]
                dissenter = dissenter[0] if dissenter else None
                # pick frame from higher-confidence model of the agreeing pair
                if valid[a].get("confidence_score", 0) >= valid[b].get("confidence_score", 0):
                    consensus = frames[a]
                else:
                    consensus = frames[b]
                return ("medium", consensus, dissenter)

    # no agreement
    return ("contested", "", None)


# ── main council class ───────────────────────────────────────────
class LLMCouncil:
    """three-model council for epistemic analysis validation."""

    def __init__(self, model_names=None):
        self.model_names = model_names or list(MODELS.keys())
        # pre-collect all readings per model to minimize server swaps
        # structure: {model_name: {article_id: raw_response}}
        self._all_readings = {m: {} for m in self.model_names}

    def collect_readings(self, articles_data, model_name):
        """run a single model across all articles.

        articles_data: list of (article_id, text_for_analysis)
        model_name: which model to use

        returns dict of article_id -> parsed JSON or None
        """
        log.info(f"\n{'='*60}")
        log.info(f"COUNCIL: running {model_name} on {len(articles_data)} articles")
        log.info(f"{'='*60}")

        # start llama-server with this model
        try:
            loaded_name = start_llama_server(model_name)
        except (FileNotFoundError, TimeoutError) as e:
            log.error(f"  cannot start {model_name}: {e}")
            return {aid: None for aid, _ in articles_data}

        readings = {}
        failures = 0

        for i, (article_id, text) in enumerate(articles_data):
            log.info(f"  [{i+1}/{len(articles_data)}] article {article_id}...")

            prompt = f"Analyze this article:\n\n{text[:3000]}"
            raw = llm_call(prompt)

            if raw is None:
                log.warning(f"    timeout/error for article {article_id}")
                readings[article_id] = None
                failures += 1
                if failures >= 5:
                    log.error(f"  5 consecutive failures on {model_name}, aborting model")
                    for _, (aid, _) in enumerate(articles_data[i+1:]):
                        readings[aid] = None
                    break
                continue

            parsed = parse_council_json(raw)
            if parsed is None:
                log.warning(f"    parse error for article {article_id}")
                readings[article_id] = {"_parse_error": True, "_raw": raw[:500]}
                failures = 0  # reset — model is responding, just bad JSON
            else:
                readings[article_id] = parsed
                failures = 0

            # brief pause to avoid overwhelming server
            time.sleep(0.5)

        success = sum(1 for v in readings.values() if v and not v.get("_parse_error"))
        log.info(f"  {model_name}: {success}/{len(articles_data)} successful readings")

        return readings

    def run_council(self, event_id):
        """run full council across all articles for an event.

        loads articles from DB, runs all three models sequentially,
        computes consensus, writes verdicts to DB.
        """
        session = get_session()

        # load articles with their analysis text
        articles = session.query(Article).filter_by(event_id=event_id).all()
        if not articles:
            log.error(f"no articles found for event_id {event_id}")
            session.close()
            return

        log.info(f"council: {len(articles)} articles for event_id={event_id}")

        # skip articles that already have council verdicts (immutability)
        existing_verdict_ids = set()
        for v in session.query(LLMCouncilVerdict.article_id).all():
            existing_verdict_ids.add(v.article_id)
        if existing_verdict_ids:
            log.info(f"  {len(existing_verdict_ids)} articles already have verdicts — skipping")

        # prepare article text — use translated_text if available, else raw_text
        articles_data = []
        for art in articles:
            if art.id in existing_verdict_ids:
                continue
            text = art.translated_text or art.raw_text or ""
            if text.strip():
                articles_data.append((art.id, text))
            else:
                log.warning(f"  article {art.id} has no text, skipping")

        log.info(f"  {len(articles_data)} new articles to process")

        # run each model across all articles
        all_readings = {}
        for model_name in self.model_names:
            readings = self.collect_readings(articles_data, model_name)
            all_readings[model_name] = readings

        # stop llama-server after all models are done
        stop_llama_server()
        log.info("  llama-server stopped")

        # compute consensus for each article
        verdicts = []
        for article_id, _ in articles_data:
            readings_for_article = {}
            for model_name in self.model_names:
                r = all_readings[model_name].get(article_id)
                if r and not r.get("_parse_error"):
                    readings_for_article[model_name] = r

            confidence, consensus_frame, dissenter = determine_consensus(readings_for_article)

            # union of positions, absence flags, tensions across all models
            positions_union = []
            absence_union = []
            tensions_union = []
            for r in readings_for_article.values():
                for p in r.get("positions", []):
                    if p and p not in positions_union:
                        positions_union.append(p)
                for a in r.get("absence_flags", []):
                    if a and a not in absence_union:
                        absence_union.append(a)
                for t in r.get("internal_tensions", []):
                    if t and t not in tensions_union:
                        tensions_union.append(t)

            verdict = CouncilVerdict(
                article_id=article_id,
                confidence_level=confidence,
                consensus_frame=consensus_frame or "",
                model_readings={m: all_readings[m].get(article_id)
                                for m in self.model_names},
                positions_union=positions_union,
                absence_flags_union=absence_union,
                internal_tensions_union=tensions_union,
                dissenting_model=dissenter,
            )
            verdicts.append(verdict)

        # write verdicts to DB
        self._write_verdicts(session, event_id, verdicts)

        session.close()
        return verdicts

    def _write_verdicts(self, session, event_id, verdicts):
        """write council verdicts and analyses to DB."""
        high = medium = contested = 0

        for v in verdicts:
            # write council verdict
            db_verdict = LLMCouncilVerdict(
                article_id=v.article_id,
                models_agree=(v.confidence_level == "high"),
                consensus_frame=v.consensus_frame if v.consensus_frame else None,
                confidence_level=v.confidence_level,
                model_readings=v.model_readings,
                dissent_recorded=(v.dissenting_model is not None),
            )
            session.add(db_verdict)

            # write council analysis to analyses table
            model_label = f"council_{v.confidence_level}"

            if v.confidence_level == "contested":
                # write separate analysis rows per model
                contested += 1
                for model_name, reading in v.model_readings.items():
                    if reading and not reading.get("_parse_error"):
                        analysis = Analysis(
                            article_id=v.article_id,
                            event_id=event_id,
                            model_used=f"council_contested:{model_name}",
                            primary_frame=reading.get("primary_frame", ""),
                            frame_confidence=reading.get("confidence_score"),
                            positions=reading.get("positions", []),
                            internal_tensions=[{"description": t} for t in reading.get("internal_tensions", [])],
                            absence_flags=reading.get("absence_flags", []),
                            unspeakable_positions=reading.get("unspeakable_positions", []),
                            raw_llm_output=reading,
                        )
                        session.add(analysis)

                # flag article for human review
                article = session.get(Article, v.article_id)
                if article:
                    article.needs_human_review = True
            else:
                if v.confidence_level == "high":
                    high += 1
                else:
                    medium += 1

                # write single consensus analysis
                analysis = Analysis(
                    article_id=v.article_id,
                    event_id=event_id,
                    model_used=model_label,
                    primary_frame=v.consensus_frame,
                    positions=v.positions_union,
                    internal_tensions=[{"description": t} for t in v.internal_tensions_union],
                    absence_flags=v.absence_flags_union,
                    unspeakable_positions=[],
                    raw_llm_output={"council_verdict": asdict(v)},
                )
                session.add(analysis)

        session.commit()
        log.info(f"\n{'='*60}")
        log.info(f"COUNCIL VERDICTS WRITTEN")
        log.info(f"  HIGH: {high}")
        log.info(f"  MEDIUM: {medium}")
        log.info(f"  CONTESTED: {contested}")
        log.info(f"  total: {len(verdicts)}")
        log.info(f"{'='*60}")


# ── CLI ───────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="run LLM council analysis")
    parser.add_argument("--event-id", type=int, required=True,
                        help="event ID to analyze")
    parser.add_argument("--models", nargs="+", default=None,
                        help="model names to use (default: all three)")
    parser.add_argument("--limit", type=int, default=None,
                        help="max articles to process (for testing)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/council.log"),
            logging.StreamHandler(),
        ],
    )

    council = LLMCouncil(model_names=args.models)

    if args.limit:
        # for testing: only process first N articles
        session = get_session()
        articles = session.query(Article).filter_by(
            event_id=args.event_id
        ).limit(args.limit).all()
        articles_data = [(a.id, a.translated_text or a.raw_text or "")
                         for a in articles if (a.translated_text or a.raw_text)]
        session.close()

        all_readings = {}
        for model_name in council.model_names:
            readings = council.collect_readings(articles_data, model_name)
            all_readings[model_name] = readings

        stop_llama_server()

        # print results without writing to DB (test mode)
        for aid, _ in articles_data:
            print(f"\narticle {aid}:")
            for m in council.model_names:
                r = all_readings[m].get(aid)
                if r and not r.get("_parse_error"):
                    print(f"  {m}: {r.get('primary_frame', 'N/A')[:80]}")
                else:
                    print(f"  {m}: FAILED")
    else:
        council.run_council(args.event_id)


if __name__ == "__main__":
    main()
