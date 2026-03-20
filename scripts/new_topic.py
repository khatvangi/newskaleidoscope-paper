#!/usr/bin/env python3
"""
new_topic.py — generate a topic config from natural language.

takes a topic description + date range, generates multilingual search queries,
subreddit suggestions, and a full topic YAML config.

usage:
  python3 scripts/new_topic.py "Epstein files global reaction" --start 2025-12-20 --end 2026-03-19
  python3 scripts/new_topic.py "Bangladesh student protests" --start 2024-07-01 --end 2024-08-15
  python3 scripts/new_topic.py "Nord Stream pipeline sabotage" --start 2022-09-26 --end 2022-10-10

if boron LLM is available, uses it for richer query generation.
otherwise falls back to template-based generation.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import yaml
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TOPICS_DIR = "topics"
LLM_URL = "http://boron:11434"

# languages to generate queries for
LANGUAGES = {
    "fr": "French", "de": "German", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "ar": "Arabic", "tr": "Turkish", "ru": "Russian",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "he": "Hebrew",
    "nl": "Dutch", "pl": "Polish", "sv": "Swedish", "hi": "Hindi",
    "fa": "Persian", "id": "Indonesian",
}

# subreddit templates by topic type
SUBREDDIT_TEMPLATES = {
    "default": [
        {"sub": "worldnews", "country": "International", "language": "English", "region": "Global"},
        {"sub": "news", "country": "United States", "language": "English", "region": "North America"},
        {"sub": "geopolitics", "country": "International", "language": "English", "region": "Global"},
        {"sub": "europe", "country": "Europe", "language": "English", "region": "Europe"},
        {"sub": "unitedkingdom", "country": "United Kingdom", "language": "English", "region": "Europe"},
        {"sub": "de", "country": "Germany", "language": "German", "region": "Europe"},
        {"sub": "france", "country": "France", "language": "French", "region": "Europe"},
        {"sub": "india", "country": "India", "language": "English", "region": "South Asia"},
        {"sub": "canada", "country": "Canada", "language": "English", "region": "North America"},
        {"sub": "australia", "country": "Australia", "language": "English", "region": "Oceania"},
        {"sub": "brasil", "country": "Brazil", "language": "Portuguese", "region": "Latin America"},
        {"sub": "Turkey", "country": "Turkey", "language": "English", "region": "Middle East"},
        {"sub": "China_irl", "country": "China", "language": "Chinese", "region": "East Asia"},
        {"sub": "korea", "country": "South Korea", "language": "English", "region": "East Asia"},
        {"sub": "southafrica", "country": "South Africa", "language": "English", "region": "Africa"},
        {"sub": "Nigeria", "country": "Nigeria", "language": "English", "region": "Africa"},
    ],
}


def check_llm_available():
    """check if boron LLM is running."""
    try:
        req = urllib.request.Request(f"{LLM_URL}/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("data"):
                return data["data"][0].get("id", "unknown")
    except Exception:
        pass
    return None


def llm_generate(prompt, timeout=120):
    """call boron LLM for query generation."""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
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
    except Exception as e:
        print(f"  llm error: {e}")
    return None


def generate_queries_llm(topic, start_date, end_date):
    """use LLM to generate multilingual queries + subreddit suggestions."""
    prompt = f"""Generate search queries for a media analysis study.

Topic: {topic}
Date range: {start_date} to {end_date}

Return JSON only (no markdown fences):
{{
  "description": "2-3 sentence description of the event/topic",
  "event_type": "military|political_scandal|economic|humanitarian|social_movement|other",
  "gdelt_queries": ["5-8 English search queries for GDELT"],
  "worldnews_queries": {{
    "default": ["2-3 English queries"],
    "fr": ["1-2 French queries using native terms"],
    "de": ["1-2 German queries"],
    "es": ["1-2 Spanish queries"],
    "ar": ["1-2 Arabic queries"],
    "ru": ["1-2 Russian queries"],
    "zh": ["1-2 Chinese queries"],
    "tr": ["1-2 Turkish queries"],
    "ja": ["1-2 Japanese queries"],
    "ko": ["1-2 Korean queries"],
    "pt": ["1-2 Portuguese queries"],
    "he": ["1-2 Hebrew queries"],
    "hi": ["1-2 Hindi queries"],
    "fa": ["1-2 Persian queries"],
    "it": ["1-2 Italian queries"],
    "nl": ["1-2 Dutch queries"],
    "pl": ["1-2 Polish queries"],
    "sv": ["1-2 Swedish queries"],
    "id": ["1-2 Indonesian queries"]
  }},
  "reddit_queries": ["3-5 Reddit search terms"],
  "extra_subreddits": ["2-5 topic-specific subreddits beyond the default news subs"],
  "absence_examples": "what voices/perspectives might be structurally absent from coverage",
  "windows": [
    {{"label": "Phase 1 name", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
    {{"label": "Phase 2 name", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}
  ]
}}

Use native-language terms, not just transliterations. The queries should capture
how each language community would naturally search for this topic."""

    raw = llm_generate(prompt)
    if not raw:
        return None

    # parse JSON from response
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


def generate_queries_template(topic, start_date, end_date):
    """fallback: generate queries from topic string (no LLM needed)."""
    # extract key terms from topic
    words = topic.lower().split()
    # remove stop words
    stop = {"the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "was", "how", "global", "reaction", "world"}
    key_terms = [w for w in words if w not in stop and len(w) > 2]
    query_base = " ".join(key_terms[:4])

    return {
        "description": f"Media analysis of: {topic}. Date range: {start_date} to {end_date}.",
        "event_type": "other",
        "gdelt_queries": [
            query_base,
            f"{query_base} reaction",
            f"{query_base} response",
            f"{query_base} impact",
            f"{query_base} controversy",
        ],
        "worldnews_queries": {
            "default": [query_base, f"{query_base} reaction"],
        },
        "reddit_queries": key_terms[:4],
        "extra_subreddits": [],
        "absence_examples": "To be determined after corpus analysis.",
        "windows": [
            {"label": "Full period", "start": start_date, "end": end_date},
        ],
    }


def slug_from_topic(topic):
    """generate a URL-friendly slug from topic string."""
    slug = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')
    return slug[:50]


def build_yaml(topic, start_date, end_date, queries):
    """build the full topic config dict."""
    slug = slug_from_topic(topic)

    # build windows
    windows = {}
    for i, w in enumerate(queries.get("windows", [{"label": "Full period", "start": start_date, "end": end_date}])):
        key = f"w{i+1}_{re.sub(r'[^a-z0-9]+', '_', w['label'].lower()).strip('_')[:30]}"
        windows[key] = {
            "label": w["label"],
            "start": w["start"],
            "end": w["end"],
        }

    # build subreddits list
    subreddits = list(SUBREDDIT_TEMPLATES["default"])
    for extra_sub in queries.get("extra_subreddits", []):
        if isinstance(extra_sub, str):
            subreddits.append({
                "sub": extra_sub, "country": "International",
                "language": "English", "region": "Global",
            })

    config = {
        "name": topic,
        "slug": slug,
        "event_type": queries.get("event_type", "other"),
        "description": queries.get("description", f"Media analysis of: {topic}"),
        "windows": windows,
        "queries": {
            "gdelt": queries.get("gdelt_queries", []),
            "worldnews": queries.get("worldnews_queries", {"default": [topic]}),
            "reddit": {
                "subreddits": subreddits,
                "queries": queries.get("reddit_queries", []),
            },
        },
        "absence_examples": queries.get("absence_examples", ""),
        "llm_model": "qwen3-32b-q4km.gguf",
        "council_model": "google_gemma-3-27b-it-Q4_K_M.gguf",
        "council_strategy": "sample",
        "council_sample_size": 300,
    }
    return config


def main():
    parser = argparse.ArgumentParser(description="generate topic config from natural language")
    parser.add_argument("topic", type=str, help="topic description in natural language")
    parser.add_argument("--start", type=str, required=True, help="start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, required=True, help="end date YYYY-MM-DD")
    parser.add_argument("--no-llm", action="store_true", help="skip LLM, use template queries")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  NEW TOPIC: {args.topic}")
    print(f"  dates: {args.start} → {args.end}")
    print(f"{'='*60}")

    # check LLM
    queries = None
    if not args.no_llm:
        model = check_llm_available()
        if model:
            print(f"\n  LLM available: {model}")
            print(f"  generating multilingual queries...")
            queries = generate_queries_llm(args.topic, args.start, args.end)
            if queries:
                print(f"  generated {len(queries.get('worldnews_queries', {}))} language queries")
                print(f"  generated {len(queries.get('gdelt_queries', []))} GDELT queries")
                if queries.get("windows"):
                    print(f"  detected {len(queries['windows'])} time windows")
            else:
                print(f"  LLM generation failed, falling back to template")
        else:
            print(f"\n  LLM not available (boron offline?), using template queries")

    if not queries:
        queries = generate_queries_template(args.topic, args.start, args.end)

    # build config
    config = build_yaml(args.topic, args.start, args.end, queries)

    # write YAML
    os.makedirs(TOPICS_DIR, exist_ok=True)
    slug = config["slug"]
    outfile = os.path.join(TOPICS_DIR, f"{slug}.yaml")

    # avoid overwriting
    if os.path.exists(outfile):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        outfile = os.path.join(TOPICS_DIR, f"{slug}_{timestamp}.yaml")

    with open(outfile, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)

    print(f"\n  config written: {outfile}")
    print(f"\n  NEXT STEPS:")
    print(f"  1. review/edit the YAML if needed")
    print(f"  2. run the pipeline:")
    print(f"     python3 scripts/topic_runner.py {outfile}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
