#!/usr/bin/env python3
"""
absence_report.py — corpus-level absence analysis.

identifies what the corpus collectively doesn't say:
geographic gaps, linguistic gaps, position gaps,
unspeakable positions, voiceless populations.

uses llama-server on boron for position gap analysis.
"""

import json
import logging
import urllib.request
from datetime import datetime

from sqlalchemy import create_engine, text

log = logging.getLogger("absence")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
LLM_URL = "http://boron:11434"
TIMEOUT = 120

# top 20 world languages by speakers
TOP_LANGUAGES = [
    "English", "Chinese", "Hindi", "Spanish", "French", "Arabic",
    "Bengali", "Portuguese", "Russian", "Japanese", "German",
    "Korean", "Turkish", "Vietnamese", "Italian", "Thai",
    "Swahili", "Hausa", "Yoruba", "Amharic",
]

# major world regions
REGIONS = {
    "North America": ["US", "CA", "MX"],
    "Western Europe": ["GB", "FR", "DE", "IT", "ES", "NL", "BE", "CH", "AT", "IE", "PT"],
    "Eastern Europe": ["PL", "CZ", "SK", "HU", "RO", "BG", "HR", "RS", "UA", "BY", "AL", "XK", "LT", "NO"],
    "Middle East": ["IR", "IL", "SA", "AE", "QA", "EG", "SY", "IQ", "JO", "LB", "YE", "OM", "KW", "BH"],
    "South Asia": ["IN", "PK", "BD", "LK", "NP"],
    "East Asia": ["CN", "JP", "KR", "TW", "HK", "SG"],
    "Southeast Asia": ["PH", "TH", "VN", "MY", "ID", "MM"],
    "Africa": ["NG", "ZA", "KE", "ET", "GH", "SN", "TZ", "MZ", "NA", "ZM", "ZW"],
    "Latin America": ["BR", "AR", "CL", "CO", "PE", "MX", "VE", "EC", "BO", "CU"],
    "Oceania": ["AU", "NZ"],
    "Central Asia": ["KZ", "UZ", "TJ", "TM", "AZ", "GE", "AM"],
}


def llm_call(prompt):
    """send prompt to llama-server."""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
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
                content = choices[0].get("message", {}).get("content", "")
                # strip thinking tags
                if "<think>" in content:
                    idx = content.rfind("</think>")
                    if idx >= 0:
                        content = content[idx + len("</think>"):].strip()
                return content
            return ""
    except Exception as e:
        log.error(f"llm call failed: {e}")
        return None


def generate_absence_report(event_id, run_id):
    """generate full absence report for an event."""
    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        # get covered countries
        rows = conn.execute(text("""
            SELECT DISTINCT s.country_code
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            WHERE a.event_id = :eid AND s.country_code IS NOT NULL
        """), {"eid": event_id})
        covered_countries = {r[0] for r in rows}

        # get covered languages
        rows = conn.execute(text("""
            SELECT DISTINCT original_language
            FROM articles WHERE event_id = :eid
        """), {"eid": event_id})
        covered_languages = {r[0] for r in rows if r[0]}

        # get cluster summaries
        rows = conn.execute(text("""
            SELECT label, description, article_count
            FROM clusters
            WHERE event_id = :eid AND valid = true
            ORDER BY article_count DESC
        """), {"eid": event_id})
        clusters = [{"label": r[0], "description": r[1], "count": r[2]} for r in rows]

        # get event title
        event_row = conn.execute(text(
            "SELECT title FROM events WHERE id = :eid"
        ), {"eid": event_id})
        event_title = event_row.fetchone()[0] if event_row else "Unknown event"

    # geographic gaps
    geographic_gaps = {}
    for region, countries in REGIONS.items():
        present = [c for c in countries if c in covered_countries]
        absent = [c for c in countries if c not in covered_countries]
        if absent:
            geographic_gaps[region] = {
                "present": present,
                "absent": absent,
                "coverage_ratio": len(present) / len(countries),
            }

    # linguistic gaps
    linguistic_gaps = [lang for lang in TOP_LANGUAGES if lang not in covered_languages]

    # position gaps (LLM)
    position_gaps = []
    unspeakable = []
    cluster_summary = "\n".join(
        f"- {c['label']}: {c.get('description', '')[:100]} ({c['count']} articles)"
        for c in clusters
    )

    if cluster_summary:
        prompt = f"""This is a corpus of global news coverage about: {event_title}

The corpus identified these epistemic clusters:
{cluster_summary}

Countries represented: {', '.join(sorted(covered_countries))}
Countries absent: {', '.join(sorted(set(c for region in geographic_gaps.values() for c in region['absent']))[:20])}

Answer as JSON only:
{{
  "position_gaps": ["list of 5 positions that significant populations hold about this event but that do NOT appear in any of the clusters above"],
  "unspeakable_positions": ["list of 3 positions that are structurally suppressed — too politically dangerous to articulate in mainstream media from any country"],
  "voiceless_populations": ["list of 5 groups most directly affected by this event who have zero first-person representation in the corpus — they are spoken ABOUT but never speak"]
}}"""

        raw = llm_call(prompt)
        if raw:
            try:
                cleaned = raw.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    cleaned = "\n".join(lines)
                start = cleaned.find("{")
                end = cleaned.rfind("}") + 1
                if start >= 0 and end > start:
                    parsed = json.loads(cleaned[start:end])
                    position_gaps = parsed.get("position_gaps", [])
                    unspeakable = parsed.get("unspeakable_positions", [])
                    voiceless = parsed.get("voiceless_populations", [])
            except (json.JSONDecodeError, KeyError) as e:
                log.warning(f"failed to parse LLM absence response: {e}")
                voiceless = []
        else:
            voiceless = []
    else:
        voiceless = []

    report = {
        "event_id": event_id,
        "run_id": run_id,
        "created": datetime.now().isoformat(),
        "event_title": event_title,
        "geographic_gaps": geographic_gaps,
        "covered_countries": sorted(covered_countries),
        "covered_languages": sorted(covered_languages),
        "linguistic_gaps": linguistic_gaps,
        "position_gaps": position_gaps,
        "unspeakable_positions": unspeakable,
        "voiceless_populations": voiceless,
        "total_countries": len(covered_countries),
        "total_languages": len(covered_languages),
    }

    # save to json
    outfile = f"analysis/absence_report_{run_id}.json"
    with open(outfile, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log.info(f"absence report saved to {outfile}")

    # summary
    total_absent = sum(len(v["absent"]) for v in geographic_gaps.values())
    log.info(f"\nABSENCE REPORT:")
    log.info(f"  countries covered: {len(covered_countries)}")
    log.info(f"  countries absent: {total_absent}")
    log.info(f"  languages covered: {len(covered_languages)}")
    log.info(f"  languages absent: {len(linguistic_gaps)}")
    log.info(f"  position gaps: {len(position_gaps)}")
    log.info(f"  unspeakable positions: {len(unspeakable)}")

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import sys
    event_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    run_id = f"absence_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    result = generate_absence_report(event_id, run_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
