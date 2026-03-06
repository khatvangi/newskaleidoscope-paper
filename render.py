#!/usr/bin/env python3
"""
render.py — HTML report generator for NewsKaleidoscope.

produces a static, self-contained HTML page for each event.
no JavaScript framework. no external CDN. all inline CSS.
mobile-first, print-friendly, progressive enhancement.
"""

import json
import logging
import os
from datetime import datetime
from html import escape

from sqlalchemy import create_engine, text

log = logging.getLogger("render")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"


# ── data loading ────────────────────────────────────────────────

def load_event_data(event_id, run_id):
    """load all data needed for rendering from DB and JSON files."""
    engine = create_engine(DB_URL)
    data = {}

    with engine.connect() as conn:
        # event info
        row = conn.execute(text("SELECT * FROM events WHERE id = :eid"), {"eid": event_id})
        event = row.fetchone()
        data["event"] = {
            "id": event.id, "title": event.title, "description": event.description,
            "event_type": event.event_type,
            "event_date": str(event.event_date) if event.event_date else "",
        }

        # articles with source info
        rows = conn.execute(text("""
            SELECT a.id, a.title, a.original_language, s.country_code, s.name as outlet,
                   s.source_type
            FROM articles a
            LEFT JOIN sources s ON a.source_id = s.id
            WHERE a.event_id = :eid ORDER BY a.id
        """), {"eid": event_id})
        data["articles"] = [dict(r._mapping) for r in rows]

        # clusters
        rows = conn.execute(text("""
            SELECT c.id, c.label, c.description, c.article_count,
                   c.geographic_signature, c.maps_to_conventional, c.is_singleton
            FROM clusters c
            WHERE c.event_id = :eid AND c.valid = true
            ORDER BY c.article_count DESC
        """), {"eid": event_id})
        data["clusters"] = [dict(r._mapping) for r in rows]

        # cluster memberships
        for cluster in data["clusters"]:
            rows = conn.execute(text("""
                SELECT cm.article_id FROM cluster_memberships cm
                WHERE cm.cluster_id = :cid
            """), {"cid": cluster["id"]})
            cluster["article_ids"] = [r[0] for r in rows]

        # council verdicts
        rows = conn.execute(text("""
            SELECT article_id, confidence_level, consensus_frame
            FROM llm_council_verdicts WHERE article_id IN
                (SELECT id FROM articles WHERE event_id = :eid)
        """), {"eid": event_id})
        data["verdicts"] = {r.article_id: {"confidence": r.confidence_level,
                                            "frame": r.consensus_frame} for r in rows}

        # syntactic features
        rows = conn.execute(text("""
            SELECT article_id, passive_voice_ratio, attribution_rate,
                   elaboration_ratio, tokenism_flag, direct_quotes_by_actor
            FROM syntactic_features
            WHERE article_id IN (SELECT id FROM articles WHERE event_id = :eid)
            ORDER BY article_id
        """), {"eid": event_id})
        data["syntax"] = {r.article_id: dict(r._mapping) for r in rows}

        # actor framing (aggregated)
        rows = conn.execute(text("""
            SELECT actor, AVG(framing_score) as avg_score, COUNT(*) as n
            FROM actor_framing
            WHERE article_id IN (SELECT id FROM articles WHERE event_id = :eid)
            GROUP BY actor ORDER BY avg_score DESC
        """), {"eid": event_id})
        data["actor_framing"] = [dict(r._mapping) for r in rows]

        # outlet asymmetry
        rows = conn.execute(text("""
            SELECT outlet_domain, actor,
                   AVG(framing_score) as avg_score
            FROM actor_framing
            WHERE article_id IN (SELECT id FROM articles WHERE event_id = :eid)
            GROUP BY outlet_domain, actor
        """), {"eid": event_id})
        outlet_data = {}
        for r in rows:
            outlet_data.setdefault(r.outlet_domain, {})[r.actor] = float(r.avg_score)
        data["outlet_asymmetry"] = outlet_data

        # presuppositions
        rows = conn.execute(text("""
            SELECT article_id, presupposition, carrier_phrase,
                   favors_actor, would_be_contested_by
            FROM presuppositions
            WHERE article_id IN (SELECT id FROM articles WHERE event_id = :eid)
        """), {"eid": event_id})
        data["presuppositions"] = [dict(r._mapping) for r in rows]

        # mirror gap
        rows = conn.execute(text("""
            SELECT us_frame, world_frame, us_domestic_ratio,
                   us_sources_count, world_sources_count
            FROM mirror_gap WHERE event_id = :eid
            ORDER BY created_at DESC LIMIT 1
        """), {"eid": event_id})
        mg = rows.fetchone()
        if mg:
            us_frame = json.loads(mg.us_frame) if isinstance(mg.us_frame, str) else mg.us_frame
            world_frame = json.loads(mg.world_frame) if isinstance(mg.world_frame, str) else mg.world_frame
            data["mirror_gap"] = {
                "us_frame": us_frame,
                "world_frame": world_frame,
                "domestic_ratio": mg.us_domestic_ratio,
                "us_sources": mg.us_sources_count,
                "world_sources": mg.world_sources_count,
            }
        else:
            data["mirror_gap"] = None

        # register analysis (session 4)
        rows = conn.execute(text("""
            SELECT article_id, raw_llm_output
            FROM analyses
            WHERE model_used LIKE '%%session_004%%'
              AND article_id IN (SELECT id FROM articles WHERE event_id = :eid)
        """), {"eid": event_id})
        data["registers"] = {}
        for r in rows:
            output = r.raw_llm_output or {}
            data["registers"][r.article_id] = {
                "register": output.get("register", []),
                "novel_frame": output.get("novel_frame"),
                "embedded_assumptions": output.get("embedded_assumptions", {}),
            }

    # load absence report if exists — sort by modification time, newest first
    import glob
    absence_files = sorted(glob.glob("analysis/absence_report_*.json"), key=os.path.getmtime, reverse=True)
    if absence_files:
        with open(absence_files[0]) as f:
            data["absence"] = json.load(f)
    else:
        data["absence"] = None

    return data


# ── HTML generation ──────────────────────────────────────────────

def e(text):
    """html escape shorthand."""
    return escape(str(text)) if text else ""


def render_css():
    """inline CSS — mobile-first, print-friendly."""
    return """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
        line-height: 1.6; color: #1a1a1a; background: #fafafa;
        max-width: 1100px; margin: 0 auto; padding: 1rem;
    }
    h1 { font-size: 2rem; font-weight: 800; margin-bottom: 0.5rem; color: #1a3a5c; }
    h2 { font-size: 1.4rem; font-weight: 700; margin: 2rem 0 0.75rem; color: #1a3a5c;
         border-bottom: 2px solid #e8f0f8; padding-bottom: 0.3rem; }
    h3 { font-size: 1.1rem; font-weight: 600; margin: 1rem 0 0.5rem; }
    p { margin-bottom: 0.75rem; }
    a { color: #1a3a5c; }

    .meta { color: #666; font-size: 0.85rem; margin-bottom: 2rem; }
    .section { margin-bottom: 3rem; }

    /* mirror gap */
    .mirror-gap { display: flex; gap: 2rem; margin: 1.5rem 0; flex-wrap: wrap; }
    .mirror-col {
        flex: 1; min-width: 280px; padding: 1.5rem; border-radius: 8px;
    }
    .mirror-us { background: #e8f0f8; border-left: 4px solid #1a3a5c; }
    .mirror-world { background: #f0f8e8; border-left: 4px solid #3a5c1a; }
    .mirror-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.1em;
                     color: #666; margin-bottom: 0.5rem; }
    .mirror-8words { font-size: 1.3rem; font-weight: 700; line-height: 1.3; margin-bottom: 0.75rem; }
    .mirror-detail { font-size: 0.9rem; color: #444; }

    /* cluster cards */
    .cluster-card {
        background: white; border: 1px solid #e0e0e0; border-radius: 8px;
        padding: 1.25rem; margin-bottom: 1rem;
    }
    .cluster-header { display: flex; justify-content: space-between; align-items: baseline;
                       flex-wrap: wrap; gap: 0.5rem; }
    .cluster-name { font-weight: 700; font-size: 1.05rem; }
    .cluster-count { font-size: 0.8rem; color: #666; }
    .cluster-geo { font-size: 0.8rem; color: #888; margin-top: 0.3rem; }
    .cluster-desc { margin-top: 0.5rem; font-size: 0.9rem; }

    /* confidence badges */
    .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px;
             font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
    .badge-high { background: #d4edda; color: #155724; }
    .badge-medium { background: #fff3cd; color: #856404; }
    .badge-contested { background: #f8d7da; color: #721c24; }

    /* tables */
    table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.85rem; }
    th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #eee; }
    th { font-weight: 600; background: #f8f8f8; }

    /* asymmetry colors */
    .score-pos { color: #155724; }
    .score-neg { color: #721c24; }

    /* absence */
    .coverage-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(40px, 1fr));
                      gap: 3px; margin: 1rem 0; }
    .coverage-cell { padding: 0.3rem; text-align: center; font-size: 0.65rem; font-weight: 600;
                      border-radius: 3px; }
    .cell-present { background: #d4edda; color: #155724; }
    .cell-absent { background: #f8f8f8; color: #ccc; }

    /* warnings */
    .warning { background: #fff3cd; border: 1px solid #ffc107; padding: 1rem;
               border-radius: 6px; margin: 1rem 0; font-size: 0.85rem; }

    /* quote box */
    .quote { border-left: 3px solid #1a3a5c; padding-left: 1rem; margin: 0.75rem 0;
             font-style: italic; color: #444; }

    /* presupposition cards */
    .presup-card { background: #fff8f0; border: 1px solid #ffe0b2; border-radius: 6px;
                    padding: 1rem; margin-bottom: 0.75rem; font-size: 0.85rem; }
    .presup-carrier { font-style: italic; color: #666; margin-top: 0.3rem; }
    .presup-favors { font-size: 0.75rem; color: #888; margin-top: 0.25rem; }

    /* confidence section */
    .conf-item { margin-bottom: 0.5rem; padding: 0.5rem; border-radius: 4px; }
    .conf-high { background: #d4edda; }
    .conf-medium { background: #fff3cd; }
    .conf-low { background: #f8d7da; }

    @media print {
        body { max-width: 100%; padding: 0; }
        .section { page-break-inside: avoid; }
        .mirror-gap { page-break-inside: avoid; }
    }
    @media (max-width: 600px) {
        h1 { font-size: 1.5rem; }
        .mirror-gap { flex-direction: column; }
        table { font-size: 0.75rem; }
    }
    """


def render_mirror_gap(data):
    """section 1: mirror gap."""
    mg = data.get("mirror_gap")
    if not mg:
        return '<div class="section"><h2>Mirror Gap</h2><p>Insufficient data for mirror gap analysis.</p></div>'

    us = mg.get("us_frame", {})
    world = mg.get("world_frame", {})

    us_8 = e(us.get("eight_words", "Data insufficient"))
    world_8 = e(world.get("eight_words", "Data insufficient"))
    us_summary = e(us.get("summary", ""))
    world_summary = e(world.get("summary", ""))

    return f"""
    <div class="section">
        <div class="mirror-gap">
            <div class="mirror-col mirror-us">
                <div class="mirror-label">US Frame ({mg.get('us_sources', 0)} sources)</div>
                <div class="mirror-8words">{us_8}</div>
                <div class="mirror-detail">{us_summary}</div>
            </div>
            <div class="mirror-col mirror-world">
                <div class="mirror-label">World Frame ({mg.get('world_sources', 0)} sources)</div>
                <div class="mirror-8words">{world_8}</div>
                <div class="mirror-detail">{world_summary}</div>
            </div>
        </div>
    </div>"""


def render_factual_core(data):
    """section 2: factual core."""
    event = data["event"]
    n_articles = len(data["articles"])
    countries = set(a.get("country_code", "") for a in data["articles"] if a.get("country_code") and a["country_code"].strip())
    languages = set(a.get("original_language", "") for a in data["articles"] if a.get("original_language"))

    verdicts = data.get("verdicts", {})
    high = sum(1 for v in verdicts.values() if v["confidence"] == "high")
    medium = sum(1 for v in verdicts.values() if v["confidence"] == "medium")
    contested = sum(1 for v in verdicts.values() if v["confidence"] == "contested")

    return f"""
    <div class="section">
        <h2>Corpus Overview</h2>
        <table>
            <tr><td>Articles analyzed</td><td><strong>{n_articles}</strong></td></tr>
            <tr><td>Countries</td><td><strong>{len(countries)}</strong></td></tr>
            <tr><td>Languages</td><td><strong>{len(languages)}</strong></td></tr>
            <tr><td>Council consensus</td>
                <td><span class="badge badge-high">HIGH {high}</span>
                    <span class="badge badge-medium">MEDIUM {medium}</span>
                    <span class="badge badge-contested">CONTESTED {contested}</span></td></tr>
        </table>
    </div>"""


def render_clusters(data):
    """section 4: cluster narratives."""
    clusters = data.get("clusters", [])
    if not clusters:
        return '<div class="section"><h2>Epistemic Clusters</h2><p>No clusters available.</p></div>'

    cards = []
    for c in clusters:
        if c.get("is_singleton"):
            continue
        geo = c.get("geographic_signature", {})
        # filter out empty/null country codes displayed as "??"
        geo_str = ", ".join(f"{k}: {v}" for k, v in (geo or {}).items() if k and k != "??") if geo else ""

        # count confidence levels for articles in this cluster
        h = m = ct = 0
        for aid in c.get("article_ids", []):
            v = data.get("verdicts", {}).get(aid, {})
            conf = v.get("confidence", "")
            if conf == "high": h += 1
            elif conf == "medium": m += 1
            elif conf == "contested": ct += 1

        cards.append(f"""
        <div class="cluster-card">
            <div class="cluster-header">
                <span class="cluster-name">{e(c['label'])}</span>
                <span class="cluster-count">{c.get('article_count', 0)} articles</span>
            </div>
            <div class="cluster-geo">{e(geo_str)}</div>
            <div class="cluster-desc">{e(c.get('description', ''))}</div>
            <div style="margin-top:0.5rem">
                <span class="badge badge-high">H:{h}</span>
                <span class="badge badge-medium">M:{m}</span>
                <span class="badge badge-contested">C:{ct}</span>
            </div>
        </div>""")

    return f"""
    <div class="section">
        <h2>Epistemic Clusters</h2>
        {''.join(cards)}
    </div>"""


def render_double_standard(data):
    """section 9: vocabulary asymmetry."""
    actor_framing = data.get("actor_framing", [])
    outlet_asym = data.get("outlet_asymmetry", {})

    # actor-level table
    actor_rows = ""
    for af in actor_framing:
        score = float(af.get("avg_score", 0))
        cls = "score-pos" if score > 0 else "score-neg" if score < 0 else ""
        actor_rows += f'<tr><td>{e(af["actor"])}</td><td class="{cls}">{score:+.2f}</td><td>{af.get("n", 0)}</td></tr>'

    # outlet asymmetry table
    outlet_rows_list = []
    for outlet, actors in outlet_asym.items():
        us_score = sum(v for k, v in actors.items() if k in ("US", "Israel", "IDF")) / max(1, sum(1 for k in actors if k in ("US", "Israel", "IDF")))
        iran_score = sum(v for k, v in actors.items() if k in ("Iran", "IRGC", "Hezbollah")) / max(1, sum(1 for k in actors if k in ("Iran", "IRGC", "Hezbollah")))
        gap = us_score - iran_score
        outlet_rows_list.append((outlet, us_score, iran_score, gap))

    outlet_rows_list.sort(key=lambda x: abs(x[3]), reverse=True)
    outlet_rows = ""
    for outlet, us, iran, gap in outlet_rows_list[:15]:
        cls = "score-pos" if gap > 0 else "score-neg"
        outlet_rows += f'<tr><td>{e(outlet[:35])}</td><td>{us:+.1f}</td><td>{iran:+.1f}</td><td class="{cls}">{gap:+.1f}</td></tr>'

    # quote asymmetry
    total_quotes = {}
    for aid, syn in data.get("syntax", {}).items():
        quotes = syn.get("direct_quotes_by_actor") or {}
        for actor, count in quotes.items():
            total_quotes[actor] = total_quotes.get(actor, 0) + count

    quote_rows = ""
    for actor, count in sorted(total_quotes.items(), key=lambda x: -x[1]):
        quote_rows += f'<tr><td>{e(actor)}</td><td>{count}</td></tr>'

    return f"""
    <div class="section">
        <h2>The Double Standard</h2>
        <h3>Actor Framing Scores</h3>
        <p style="font-size:0.8rem;color:#666">Positive = sanitized language. Negative = condemnatory language.</p>
        <table>
            <tr><th>Actor</th><th>Avg Score</th><th>Articles</th></tr>
            {actor_rows}
        </table>

        <h3>Outlet Asymmetry</h3>
        <p style="font-size:0.8rem;color:#666">Ranked by gap between US/Israel framing and Iran framing.</p>
        <table>
            <tr><th>Outlet</th><th>US/Israel</th><th>Iran</th><th>Gap</th></tr>
            {outlet_rows}
        </table>

        <h3>Direct Quote Distribution</h3>
        <table>
            <tr><th>Speaker Type</th><th>Quotes</th></tr>
            {quote_rows}
        </table>
    </div>"""


def render_presuppositions(data):
    """presupposition findings."""
    presups = data.get("presuppositions", [])
    if not presups:
        return ""

    # group by article
    by_article = {}
    for p in presups:
        by_article.setdefault(p["article_id"], []).append(p)

    cards = []
    for aid, plist in sorted(by_article.items()):
        # find article info
        art = next((a for a in data["articles"] if a["id"] == aid), {})
        outlet = art.get("outlet", "?")
        cc = art.get("country_code") or "?"
        # include article title to disambiguate multiple articles from same outlet
        art_title = art.get("title", "")
        title_suffix = f' — "{art_title[:60]}"' if art_title else ""

        items = ""
        for p in plist[:3]:  # show max 3 per article
            contested_by = p.get('would_be_contested_by', '')
            items += f"""
            <div class="presup-card">
                <div class="presup-carrier">"{e(p.get('carrier_phrase', ''))}"</div>
                <div style="margin-top:0.4rem"><strong>Presupposes:</strong> {e(p.get('presupposition', ''))}</div>
                {"<div class='presup-favors'>Contested by: " + e(contested_by[:150]) + "</div>" if contested_by else ""}
            </div>"""

        cards.append(f"""
            <h3>{e(outlet)} ({e(cc)}) — {len(plist)} presuppositions</h3>
            <p style="font-size:0.75rem;color:#888;margin-top:-0.3rem">{e(title_suffix)}</p>
            {items}""")

    return f"""
    <div class="section">
        <h2>Presuppositional Framing</h2>
        <p>These are claims treated as background fact rather than argued positions.
           The carrier phrase (quoted text) embeds an assumption that is never explicitly
           defended. "Contested by" names who would reject that assumption.
           Identified via LLM analysis of articles with highest strategic ambiguity scores.</p>
        {''.join(cards)}
    </div>"""


def render_absence(data):
    """section 8: what nobody said."""
    absence = data.get("absence")
    if not absence:
        return '<div class="section"><h2>What Nobody Said</h2><p>Absence report not yet generated.</p></div>'

    # coverage grid
    all_countries = set()
    for region_data in absence.get("geographic_gaps", {}).values():
        all_countries.update(region_data.get("present", []))
        all_countries.update(region_data.get("absent", []))
    covered = set(absence.get("covered_countries", []))

    cells = ""
    for cc in sorted(all_countries):
        cls = "cell-present" if cc in covered else "cell-absent"
        cells += f'<div class="coverage-cell {cls}">{cc}</div>'

    # position gaps
    pos_gaps = ""
    for pg in absence.get("position_gaps", []):
        pos_gaps += f"<li>{e(pg)}</li>"

    # unspeakable
    unspeakable = ""
    for up in absence.get("unspeakable_positions", []):
        unspeakable += f"<li>{e(up)}</li>"

    # voiceless
    voiceless = ""
    for vp in absence.get("voiceless_populations", []):
        voiceless += f"<li>{e(vp)}</li>"

    # linguistic gaps
    lang_gaps = ", ".join(absence.get("linguistic_gaps", []))

    return f"""
    <div class="section">
        <h2>What Nobody Said</h2>

        <h3>Geographic Coverage</h3>
        <div class="coverage-grid">{cells}</div>
        <p style="font-size:0.8rem;color:#666">
            Green = represented. Grey = absent from corpus.</p>

        <h3>Missing Languages</h3>
        <p>{e(lang_gaps)}</p>

        {"<h3>Positions Absent from Corpus</h3><ul>" + pos_gaps + "</ul>" if pos_gaps else ""}
        {"<h3>Structurally Unspeakable</h3><ul>" + unspeakable + "</ul>" if unspeakable else ""}
        {"<h3>Voiceless Populations</h3><ul>" + voiceless + "</ul>" if voiceless else ""}
    </div>"""


def render_confidence(data):
    """section 10: confidence and methodology."""
    event = data["event"]
    n = len(data["articles"])
    verdicts = data.get("verdicts", {})
    high = sum(1 for v in verdicts.values() if v["confidence"] == "high")
    contested = sum(1 for v in verdicts.values() if v["confidence"] == "contested")

    return f"""
    <div class="section">
        <h2>Confidence &amp; Methodology</h2>

        <div class="conf-item conf-high">
            <strong>HIGH confidence:</strong> {high} articles where three independent LLM models
            (Qwen3-32B, Gemma-3-27B, Mistral-Small-3.1-24B) agreed on the article's epistemic position.
        </div>
        <div class="conf-item conf-medium">
            <strong>MEDIUM confidence:</strong> Two of three models agreed. The dissenting model's
            reading is preserved in the database.
        </div>
        <div class="conf-item conf-low">
            <strong>CONTESTED:</strong> {contested} articles where no two models agreed.
            These are genuinely ambiguous — the position is not a stable textual property.
        </div>

        <h3>Pipeline</h3>
        <table>
            <tr><td>Corpus</td><td>{n} articles, {len(set(a.get('country_code') for a in data['articles'] if a.get('country_code')))} countries</td></tr>
            <tr><td>Translation</td><td>Helsinki-NLP + NLLB-200</td></tr>
            <tr><td>LLM analysis</td><td>Qwen3-32B via llama-server (two-pass)</td></tr>
            <tr><td>Council</td><td>3-model consensus with sentence-transformer similarity</td></tr>
            <tr><td>Syntactic</td><td>spaCy en_core_web_lg — passive voice, attribution, elaboration</td></tr>
            <tr><td>Vocabulary</td><td>Proximity-based sanitizing/condemnatory term detection</td></tr>
            <tr><td>Presupposition</td><td>LLM extraction on targeted high-ambiguity articles</td></tr>
        </table>

        <div class="warning">
            <strong>This system has limitations.</strong> LLM analysis reflects model training biases.
            Translation may lose nuance. Syntactic features are unreliable on translated text.
            The 5:1 quote asymmetry reflects structural access patterns, not solely editorial choice.
            All findings require validation across additional events.
        </div>
    </div>"""


def render_event_page(event_id, run_id, output_dir):
    """generate the full HTML report for an event."""
    log.info(f"loading data for event {event_id}...")
    data = load_event_data(event_id, run_id)

    event = data["event"]
    title = event.get("title", "Unknown Event")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{e(title)} — NewsKaleidoscope</title>
    <meta name="description" content="Epistemic mapping: how the world frames {e(title)}">
    <meta property="og:title" content="{e(title)} — NewsKaleidoscope">
    <meta property="og:type" content="article">
    <style>{render_css()}</style>
</head>
<body>
    <header>
        <h1>{e(title)}</h1>
        <div class="meta">
            NewsKaleidoscope — Epistemic Mapping System<br>
            Event date: {e(event.get('event_date', ''))} |
            Type: {e(event.get('event_type', ''))} |
            Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </header>

    {render_mirror_gap(data)}
    {render_factual_core(data)}
    {render_clusters(data)}
    {render_double_standard(data)}
    {render_presuppositions(data)}
    {render_absence(data)}
    {render_confidence(data)}

    <footer style="margin-top:3rem; padding-top:1rem; border-top:1px solid #eee;
                    font-size:0.75rem; color:#999;">
        NewsKaleidoscope | run_id: {e(run_id)} |
        <a href="https://github.com/newskaleidoscope">methodology</a>
    </footer>
</body>
</html>"""

    # write output
    os.makedirs(output_dir, exist_ok=True)
    outfile = os.path.join(output_dir, "index.html")
    with open(outfile, 'w', encoding='utf-8') as f:
        f.write(html)

    log.info(f"rendered to {outfile} ({len(html)} bytes)")
    return {"output_file": outfile, "size_bytes": len(html)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import sys
    event_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "docs/events/test"
    run_id = f"render_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    render_event_page(event_id, run_id, output_dir)
