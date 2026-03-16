#!/usr/bin/env python3
"""
sample_council.py — stratified sample council for CS1-RU.

instead of running 3 models on all 1,863 articles (~63 hrs), this:
1. draws a stratified sample (~300 articles by language)
2. runs Gemma on the sample only (Qwen Pass 1 already exists)
3. compares Qwen vs Gemma via cosine similarity
4. produces agreement distribution comparable to CS1's full council

methodological justification: council measures model reliability, not
article properties. a 300-article stratified sample is statistically
sufficient to estimate the agreement distribution (95% CI ±5.5%).

usage:
  python3 scripts/sample_council.py --event-id 4 --sample-size 300
  python3 scripts/sample_council.py --event-id 4 --sample-size 300 --dry-run
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_session, Article, Analysis, LLMCouncilVerdict, Event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/sample_council.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("sample_council")

# ── config ────────────────────────────────────────────────────────
BORON_HOST = "boron"
LLAMA_SERVER_PORT = 11434
LLAMA_SERVER_BIN = "/storage/kiran-stuff/llama.cpp/build/bin/llama-server"
MODEL_DIR = "/storage/kiran-stuff/llama.cpp/models"
LLM_URL = f"http://{BORON_HOST}:{LLAMA_SERVER_PORT}"

GEMMA_GGUF = "google_gemma-3-27b-it-Q4_K_M.gguf"
GEMMA_NAME = "gemma-3-27b-it"
PARALLEL = 4  # concurrent requests to llama-server
TIMEOUT = 120
SIMILARITY_THRESHOLD = 0.82

# same council prompt as council.py
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


# ── server management ────────────────────────────────────────────
def ssh_cmd(cmd):
    result = subprocess.run(
        ["ssh", BORON_HOST, cmd],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip(), result.returncode


def start_gemma():
    """start llama-server with Gemma on boron, parallel mode."""
    # kill any existing
    ssh_cmd("pkill -f llama-server")
    time.sleep(2)

    model_path = f"{MODEL_DIR}/{GEMMA_GGUF}"
    cmd = (
        f"nohup {LLAMA_SERVER_BIN} "
        f"--model {model_path} "
        f"--tensor-split 0.5,0.5 "
        f"--host 0.0.0.0 --port {LLAMA_SERVER_PORT} "
        f"--ctx-size 16384 --n-gpu-layers 99 "
        f"--parallel {PARALLEL} "
        f"> /tmp/llama-server.log 2>&1 &"
    )
    ssh_cmd(cmd)
    log.info(f"starting Gemma with --parallel {PARALLEL}...")

    # wait for ready
    for attempt in range(60):
        time.sleep(3)
        try:
            req = urllib.request.Request(f"{LLM_URL}/v1/models")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("data"):
                    log.info(f"Gemma ready: {data['data'][0].get('id')}")
                    break
        except Exception:
            pass
    else:
        raise TimeoutError("Gemma failed to start after 180s")

    # warmup
    log.info("warming up...")
    llm_call("Say OK.", timeout=60)
    log.info("warmup done")


def stop_server():
    ssh_cmd("pkill -f llama-server")
    log.info("llama-server stopped")


def llm_call(prompt, timeout=TIMEOUT):
    """single LLM call."""
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
                return msg.get("content", "") or msg.get("reasoning_content", "")
            return ""
    except Exception as e:
        log.error(f"llm call failed: {e}")
        return None


def parse_json(raw):
    """extract JSON from response."""
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


# ── stratified sampling ──────────────────────────────────────────
def draw_stratified_sample(session, event_id, target_size):
    """draw stratified sample proportional to language distribution."""
    # get all articles with Pass 1 analysis
    articles = session.query(Article).filter_by(event_id=event_id).filter(
        Article.translated_text.isnot(None),
    ).all()

    # group by language
    by_lang = defaultdict(list)
    for art in articles:
        by_lang[art.original_language or "unknown"].append(art)

    total = sum(len(v) for v in by_lang.values())
    log.info(f"population: {total} articles across {len(by_lang)} languages")

    # proportional allocation with minimum 1 per language
    sample = []
    for lang, arts in sorted(by_lang.items(), key=lambda x: -len(x[1])):
        n = max(1, round(len(arts) / total * target_size))
        n = min(n, len(arts))  # can't sample more than exist
        chosen = random.sample(arts, n)
        sample.extend(chosen)
        log.info(f"  {lang}: {n}/{len(arts)} sampled")

    # trim to target if oversampled due to minimum-1 rule
    if len(sample) > target_size * 1.1:
        random.shuffle(sample)
        sample = sample[:target_size]

    log.info(f"final sample: {len(sample)} articles")
    return sample


# ── parallel Gemma inference ─────────────────────────────────────
def run_gemma_parallel(articles_data):
    """run Gemma on articles using concurrent threads."""
    import concurrent.futures

    results = {}
    success = 0
    failed = 0

    def process_one(article_id, text):
        prompt = f"Analyze this article:\n\n{text[:3000]}"
        raw = llm_call(prompt)
        if raw is None:
            time.sleep(3)
            raw = llm_call(prompt)
        return article_id, raw

    # process in batches of PARALLEL
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL) as executor:
        futures = []
        for i, (article_id, text) in enumerate(articles_data):
            futures.append(executor.submit(process_one, article_id, text))

            # log progress every 10
            if (i + 1) % 10 == 0 or i == len(articles_data) - 1:
                # wait for current batch before logging
                pass

        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            article_id, raw = future.result()
            parsed = parse_json(raw)
            results[article_id] = parsed

            if parsed:
                success += 1
            else:
                failed += 1

            if (i + 1) % 20 == 0:
                log.info(f"  progress: {i+1}/{len(articles_data)} ({success} ok, {failed} fail)")

    log.info(f"Gemma done: {success}/{len(articles_data)} successful")
    return results


# ── consensus comparison ─────────────────────────────────────────
def compare_qwen_gemma(session, sample_articles, gemma_readings):
    """compare Qwen Pass 1 output vs Gemma council output."""
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model = SentenceTransformer("all-MiniLM-L6-v2")
    log.info("loaded sentence similarity model")

    # get Qwen's primary_frame from analyses table
    article_ids = [a.id for a in sample_articles]
    qwen_analyses = session.query(Analysis).filter(
        Analysis.article_id.in_(article_ids),
        Analysis.event_id == sample_articles[0].event_id if sample_articles else 0,
    ).all()

    # build lookup: article_id -> qwen primary_frame
    qwen_frames = {}
    for an in qwen_analyses:
        # take the first (Qwen) analysis per article
        if an.article_id not in qwen_frames and an.primary_frame:
            qwen_frames[an.article_id] = an.primary_frame

    # compute pairwise similarity
    high = 0
    medium = 0
    contested = 0
    results_detail = []

    for art in sample_articles:
        qwen_frame = qwen_frames.get(art.id, "")
        gemma_data = gemma_readings.get(art.id)
        gemma_frame = gemma_data.get("primary_frame", "") if gemma_data else ""

        if not qwen_frame or not gemma_frame:
            contested += 1
            results_detail.append({
                "article_id": art.id, "language": art.original_language,
                "similarity": 0.0, "level": "contested", "reason": "missing frame",
            })
            continue

        # cosine similarity
        embeddings = model.encode([qwen_frame, gemma_frame])
        sim = float(np.dot(embeddings[0], embeddings[1]) /
                     (np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])))

        if sim >= SIMILARITY_THRESHOLD:
            high += 1
            level = "high"
        elif sim >= 0.65:
            medium += 1
            level = "medium"
        else:
            contested += 1
            level = "contested"

        results_detail.append({
            "article_id": art.id, "language": art.original_language,
            "similarity": round(sim, 3), "level": level,
            "qwen_frame": qwen_frame[:100], "gemma_frame": gemma_frame[:100],
        })

    total = high + medium + contested
    log.info(f"\n{'='*60}")
    log.info(f"SAMPLE COUNCIL RESULTS (N={total})")
    log.info(f"  HIGH (sim >= {SIMILARITY_THRESHOLD}): {high} ({high/total*100:.1f}%)")
    log.info(f"  MEDIUM (0.65 <= sim < {SIMILARITY_THRESHOLD}): {medium} ({medium/total*100:.1f}%)")
    log.info(f"  CONTESTED (sim < 0.65): {contested} ({contested/total*100:.1f}%)")
    log.info(f"{'='*60}")

    # per-language breakdown
    by_lang = defaultdict(lambda: {"high": 0, "medium": 0, "contested": 0, "sims": []})
    for r in results_detail:
        lang = r["language"]
        by_lang[lang][r["level"]] += 1
        by_lang[lang]["sims"].append(r["similarity"])

    log.info(f"\nper-language agreement:")
    for lang in sorted(by_lang.keys(), key=lambda l: -len(by_lang[l]["sims"])):
        d = by_lang[lang]
        n = len(d["sims"])
        avg = sum(d["sims"]) / n if n else 0
        log.info(f"  {lang:20s}: n={n:3d}  avg_sim={avg:.3f}  "
                 f"H={d['high']} M={d['medium']} C={d['contested']}")

    return {
        "total": total, "high": high, "medium": medium, "contested": contested,
        "high_pct": round(high / total * 100, 1),
        "medium_pct": round(medium / total * 100, 1),
        "contested_pct": round(contested / total * 100, 1),
        "details": results_detail,
        "per_language": {k: {"n": len(v["sims"]), "avg_sim": round(sum(v["sims"])/max(len(v["sims"]),1), 3)}
                         for k, v in by_lang.items()},
    }


# ── write verdicts to DB ─────────────────────────────────────────
def write_sample_verdicts(session, event_id, sample_articles, gemma_readings, comparison):
    """write sample council verdicts to DB."""
    written = 0
    for detail in comparison["details"]:
        article_id = detail["article_id"]
        gemma_data = gemma_readings.get(article_id, {})

        verdict = LLMCouncilVerdict(
            article_id=article_id,
            models_agree=(detail["level"] == "high"),
            consensus_frame=detail.get("qwen_frame", ""),
            confidence_level=detail["level"],
            model_readings={
                "qwen3:32b": {"primary_frame": detail.get("qwen_frame", ""), "source": "pass1"},
                GEMMA_NAME: gemma_data if gemma_data else {"error": "no reading"},
            },
            dissent_recorded=(detail["level"] == "contested"),
        )
        session.add(verdict)
        written += 1

    session.commit()
    log.info(f"wrote {written} sample council verdicts to DB")


# ── main ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="sample council for CS1-RU")
    parser.add_argument("--event-id", type=int, required=True)
    parser.add_argument("--sample-size", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="sample only, no Gemma")
    parser.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    args = parser.parse_args()

    random.seed(args.seed)
    session = get_session()

    # step 1: draw sample
    log.info(f"drawing stratified sample of ~{args.sample_size} from event_id={args.event_id}")
    sample = draw_stratified_sample(session, args.event_id, args.sample_size)

    if args.dry_run:
        log.info("dry run — no Gemma inference")
        session.close()
        return

    # step 2: prepare article data
    articles_data = [(art.id, art.translated_text or art.raw_text or "")
                     for art in sample if (art.translated_text or art.raw_text)]
    log.info(f"articles with text: {len(articles_data)}")

    # step 3: start Gemma and run inference
    start_gemma()
    gemma_readings = run_gemma_parallel(articles_data)
    stop_server()

    # step 4: compare Qwen vs Gemma
    comparison = compare_qwen_gemma(session, sample, gemma_readings)

    # step 5: write verdicts
    write_sample_verdicts(session, args.event_id, sample, gemma_readings, comparison)

    # step 6: save full results
    outfile = f"analysis/sample_council_event{args.event_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    os.makedirs("analysis", exist_ok=True)
    with open(outfile, "w") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    log.info(f"full results saved to {outfile}")

    # step 7: comparison with CS1
    log.info(f"\n{'='*60}")
    log.info(f"CROSS-CASE COMPARISON")
    log.info(f"  CS1 (Iran, full council):    HIGH=4.7%  MEDIUM=37.6%  CONTESTED=57.7%")
    log.info(f"  CS1-RU (Ukraine, sample):    HIGH={comparison['high_pct']}%  MEDIUM={comparison['medium_pct']}%  CONTESTED={comparison['contested_pct']}%")
    log.info(f"{'='*60}")

    session.close()


if __name__ == "__main__":
    main()
