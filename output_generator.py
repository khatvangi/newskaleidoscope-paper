#!/usr/bin/env python3
"""
output_generator.py — render the epistemic map from two-pass analysis results.

handles: emergent clusters (not predefined), singletons, internal tensions,
original-language framing, absence report, coverage gaps, transparency section.
"""

import json
import os
from datetime import datetime

ANALYSIS_FILE = "analysis/all_results.json"
CLUSTERS_FILE = "analysis/emergent_clusters.json"
ABSENCE_FILE = "analysis/absence_report.json"
COVERAGE_FILE = "analysis/coverage_gaps.json"
TENSION_FILE = "analysis/tension_analysis.json"
OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# color palette for emergent clusters (assigned dynamically)
CLUSTER_PALETTE = [
    "#457b9d", "#2d6a4f", "#e76f51", "#7b2cbf", "#d62828",
    "#8d99ae", "#bc6c25", "#606c38", "#c77dff", "#219ebc",
    "#e9c46a", "#264653",
]

# country → flag emoji
COUNTRY_FLAGS = {
    "United States": "🇺🇸", "United Kingdom": "🇬🇧", "France": "🇫🇷",
    "Germany": "🇩🇪", "Spain": "🇪🇸", "Italy": "🇮🇹", "Israel": "🇮🇱",
    "Qatar": "🇶🇦", "Saudi Arabia": "🇸🇦", "Egypt": "🇪🇬", "Pakistan": "🇵🇰",
    "India": "🇮🇳", "Japan": "🇯🇵", "China": "🇨🇳", "Hong Kong": "🇭🇰",
    "Singapore": "🇸🇬", "Bangladesh": "🇧🇩", "Indonesia": "🇮🇩",
    "South Korea": "🇰🇷", "South Africa": "🇿🇦", "Kenya": "🇰🇪",
    "Nigeria": "🇳🇬", "Uganda": "🇺🇬", "Brazil": "🇧🇷", "Colombia": "🇨🇴",
    "Mexico": "🇲🇽", "Argentina": "🇦🇷", "Canada": "🇨🇦", "Vatican": "🇻🇦",
    "Iran": "🇮🇷", "Iraq": "🇮🇶", "Turkey": "🇹🇷", "Russia": "🇷🇺",
    "Australia": "🇦🇺", "Albania": "🇦🇱", "Azerbaijan": "🇦🇿",
    "Belgium": "🇧🇪", "Bulgaria": "🇧🇬", "Croatia": "🇭🇷", "Czech Republic": "🇨🇿",
    "Ireland": "🇮🇪", "Kosovo": "🇽🇰", "Lithuania": "🇱🇹",
    "Netherlands": "🇳🇱", "New Zealand": "🇳🇿", "Norway": "🇳🇴",
    "Philippines": "🇵🇭", "Romania": "🇷🇴", "Slovak Republic": "🇸🇰",
    "Switzerland": "🇨🇭", "Syria": "🇸🇾", "Taiwan": "🇹🇼",
    "Ukraine": "🇺🇦", "Venezuela": "🇻🇪",
}


def get_flag(country):
    return COUNTRY_FLAGS.get(country, "🌐")


def esc(text):
    if not isinstance(text, str):
        return str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_card(r, color="#457b9d"):
    """render a single article card with the new schema."""
    a = r.get("analysis", {})
    name = esc(r.get("outlet_name", r.get("domain", "")))
    country = r.get("sourcecountry", "")
    flag = get_flag(country)

    # primary content
    framing_desc = esc(a.get("framing_description", a.get("one_sentence_summary", "")))
    tensions = a.get("internal_tensions")
    authority = a.get("authority_structure", "")

    # framing terms: original + english + contested
    original_terms = a.get("original_framing_terms", [])
    english_approx = a.get("english_approximations", [])
    contested = a.get("contested_translations", [])
    key_lang = a.get("key_framing_language", [])
    absence = a.get("absence_flags", [])
    translation_warn = a.get("translation_warning", "")
    register = a.get("emotional_register", "")

    html = f"""    <div class="card" style="border-left: 3px solid {color}">
      <div class="card-header">
        <span class="card-flag">{flag}</span>
        <span class="card-outlet">{name}</span>
        <span class="card-country">{esc(country)}</span>
      </div>
      <div class="card-summary">{framing_desc}</div>
"""

    # internal tensions — highlighted prominently
    if tensions:
        html += f'      <div class="card-tension">⚡ <strong>Internal tension:</strong> {esc(tensions)}</div>\n'

    # authority structure
    if authority:
        html += f'      <div class="card-authority">{esc(authority)}</div>\n'

    # emotional register
    if register and register != "unknown":
        html += f'      <span class="register-tag">{esc(register)}</span>\n'

    # original-language framing with translations
    if original_terms:
        orig_lang = a.get("original_language", "")
        html += f'      <div class="framing-section"><span class="framing-label">original ({esc(orig_lang)}):</span>\n'
        for j, term in enumerate(original_terms[:6]):
            approx = english_approx[j] if j < len(english_approx) else ""
            tooltip = f' title="{esc(approx)}"' if approx else ""
            html += f'        <span class="frame-tag original"{tooltip}>{esc(term)}</span>\n'
        html += '      </div>\n'

    # contested translations
    if contested:
        for note in contested[:3]:
            html += f'      <div class="contested-note">⚠ {esc(note)}</div>\n'

    # key framing language (english)
    if key_lang:
        html += '      <div class="framing-section"><span class="framing-label">key framing:</span>\n'
        for term in key_lang[:5]:
            html += f'        <span class="frame-tag">{esc(term)}</span>\n'
        html += '      </div>\n'

    if translation_warn:
        html += f'      <div class="translation-warn">⚠ {esc(translation_warn)}</div>\n'

    # absence flags
    if absence:
        html += '      <div class="framing-section"><span class="framing-label">absent frames:</span>\n'
        for flag_text in absence[:4]:
            html += f'        <span class="frame-tag absence">{esc(flag_text)}</span>\n'
        html += '      </div>\n'

    html += "    </div>\n"
    return html


def generate_html(results, clusters=None, absence=None, coverage=None, tensions=None):
    """generate the full HTML page."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_countries = len(set(r.get("sourcecountry", "") for r in results))
    n_langs = len(set(r.get("sourcelang", "") for r in results))
    n_tensions = sum(1 for r in results if r.get("analysis", {}).get("internal_tensions"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NewsKaleidoscope — Iran Strikes Epistemic Map</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,300;0,600;1,300&family=JetBrains+Mono:wght@400;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  :root {{
    --bg: #0f1419; --surface: #1a1f2e; --surface2: #232838;
    --text: #e8e6e3; --text-dim: #9ca3af; --accent: #60a5fa;
    --border: #2d3348; --warn: #fbbf24; --tension: #f472b6;
  }}
  body {{ font-family: 'Newsreader', Georgia, serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem; }}
  header {{ text-align: center; padding: 3rem 1rem 2rem; border-bottom: 1px solid var(--border); margin-bottom: 2rem; }}
  header h1 {{ font-family: 'JetBrains Mono', monospace; font-size: 1.1rem; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; color: var(--accent); margin-bottom: 1rem; }}
  header h2 {{ font-family: 'Newsreader', serif; font-size: 2.2rem; font-weight: 600; line-height: 1.2; margin-bottom: 0.75rem; }}
  header .meta {{ font-size: 0.9rem; color: var(--text-dim); font-style: italic; }}
  .section-title {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-dim); margin: 2.5rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }}
  .meta-observation {{ background: var(--surface); border: 1px solid var(--accent); border-radius: 8px; padding: 1.25rem; margin: 1rem 0; font-size: 0.95rem; line-height: 1.6; font-style: italic; }}
  .cluster-header {{ display: flex; align-items: baseline; gap: 0.75rem; margin: 2rem 0 0.5rem; flex-wrap: wrap; }}
  .cluster-name {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; padding: 0.25rem 0.75rem; border-radius: 4px; color: white; }}
  .cluster-meta {{ font-size: 0.8rem; color: var(--text-dim); }}
  .cluster-desc {{ font-size: 0.9rem; color: var(--text-dim); margin: 0.25rem 0 0.75rem; padding-left: 0.5rem; border-left: 2px solid var(--border); }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; transition: border-color 0.2s; }}
  .card:hover {{ border-color: var(--accent); }}
  .card-header {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }}
  .card-flag {{ font-size: 1.3rem; }}
  .card-outlet {{ font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; font-weight: 700; color: var(--accent); }}
  .card-country {{ font-size: 0.75rem; color: var(--text-dim); margin-left: auto; }}
  .card-summary {{ font-size: 0.95rem; line-height: 1.5; margin-bottom: 0.75rem; }}
  .card-tension {{ font-size: 0.85rem; color: var(--tension); background: rgba(244, 114, 182, 0.08); padding: 0.5rem 0.6rem; border-radius: 4px; margin-bottom: 0.6rem; border: 1px solid rgba(244, 114, 182, 0.2); line-height: 1.4; }}
  .card-authority {{ font-size: 0.8rem; color: var(--text-dim); margin-bottom: 0.5rem; font-style: italic; }}
  .register-tag {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 3px; font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; background: var(--surface2); border: 1px solid var(--border); color: var(--text-dim); margin-bottom: 0.5rem; }}
  .framing-section {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.3rem; margin-bottom: 0.4rem; }}
  .framing-label {{ font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; color: var(--text-dim); margin-right: 0.2rem; }}
  .frame-tag {{ display: inline-block; padding: 0.15rem 0.5rem; background: var(--surface2); border: 1px solid var(--border); border-radius: 3px; font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: var(--text-dim); }}
  .frame-tag.original {{ border-color: var(--accent); color: var(--accent); background: rgba(96, 165, 250, 0.08); cursor: help; }}
  .frame-tag.absence {{ border-color: #e76f51; color: #e76f51; background: rgba(231, 111, 81, 0.08); }}
  .contested-note {{ font-size: 0.7rem; color: var(--warn); margin: 0.2rem 0; font-family: 'JetBrains Mono', monospace; }}
  .translation-warn {{ font-size: 0.7rem; color: var(--warn); margin: 0.3rem 0; font-family: 'JetBrains Mono', monospace; }}
  .singleton-badge {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 3px; font-family: 'JetBrains Mono', monospace; font-size: 0.6rem; background: rgba(199, 125, 255, 0.15); border: 1px solid #c77dff; color: #c77dff; margin-bottom: 0.5rem; }}
  .corpus-warning {{ background: rgba(231, 111, 81, 0.1); border: 2px solid #e76f51; border-radius: 8px; padding: 1.25rem 1.5rem; margin: 1.5rem 0; font-size: 0.95rem; line-height: 1.5; }}
  .corpus-warning strong {{ color: #e76f51; }}
  .unspeakable-section {{ background: var(--surface); border: 2px solid var(--warn); border-radius: 8px; padding: 1.5rem; margin-top: 1rem; }}
  .unspeakable-item {{ padding: 0.75rem 0; border-bottom: 1px solid var(--border); font-size: 0.95rem; line-height: 1.6; }}
  .unspeakable-item:last-child {{ border-bottom: none; }}
  .tension-breakdown {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; margin-top: 1rem; }}
  .tension-type {{ display: flex; align-items: baseline; gap: 0.75rem; padding: 0.5rem 0; border-bottom: 1px solid var(--border); }}
  .tension-type:last-child {{ border-bottom: none; }}
  .tension-count {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; color: var(--tension); min-width: 2.5rem; text-align: right; }}
  .tension-name {{ font-size: 0.9rem; font-weight: 600; }}
  .tension-desc {{ font-size: 0.8rem; color: var(--text-dim); }}
  .absence-section, .gaps-section, .transparency-section {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; margin-top: 1rem; }}
  .absence-item {{ padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
  .absence-item:last-child {{ border-bottom: none; }}
  .absence-label {{ font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: var(--warn); margin-right: 0.5rem; }}
  .gap-item {{ padding: 0.4rem 0; font-size: 0.85rem; color: var(--text-dim); }}
  .gap-item strong {{ color: var(--text); }}
  .gap-warn {{ color: #e76f51; font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; }}
  .transparency-item {{ padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.85rem; line-height: 1.5; }}
  .transparency-item:last-child {{ border-bottom: none; }}
  .claims-section {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.5rem; margin-top: 1rem; }}
  .claim-item {{ padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
  .claim-item:last-child {{ border-bottom: none; }}
  .claim-status {{ font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: var(--warn); margin-right: 0.5rem; }}
  footer {{ text-align: center; padding: 2rem 1rem; margin-top: 3rem; border-top: 1px solid var(--border); font-size: 0.8rem; color: var(--text-dim); }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  @media (max-width: 600px) {{ .cards {{ grid-template-columns: 1fr; }} header h2 {{ font-size: 1.5rem; }} .container {{ padding: 1rem; }} }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>NewsKaleidoscope</h1>
    <h2>US-Israel Strikes on Iran: Global Epistemic Map</h2>
    <p class="meta">
      {len(results)} outlets analyzed across {n_countries} countries and {n_langs} languages
      &middot; {n_tensions} articles with internal tensions
      &middot; Generated {now}
    </p>
  </header>
"""

    # ── corpus gap warning — Iranian sources ─────────────────────
    # check if Iran is represented in the corpus
    iran_count = sum(1 for r in results if "Iran" in r.get("sourcecountry", ""))
    if iran_count == 0:
        html += '  <div class="corpus-warning"><strong>⚠ Critical gap:</strong> This corpus analyzes an event <em>about</em> Iran but contains zero Iranian domestic sources. Press TV, ISNA, Kayhan, Shargh — the outlets through which Iranians actually process this event — are structurally inaccessible to automated ingestion or excluded by GDELT. Every position map below is missing the position of the country being struck.</div>\n'
    elif iran_count < 5:
        html += f'  <div class="corpus-warning"><strong>⚠ Limited Iranian representation:</strong> Only {iran_count} article{"s" if iran_count != 1 else ""} from Iranian sources in a corpus analyzing an event primarily about Iran. Regime-side outlets (Kayhan, ISNA) and reformist press (Shargh) remain underrepresented relative to their analytical importance.</div>\n'

    # ── tension type breakdown ─────────────────────────────────────
    if tensions and "tension_types" in tensions:
        modal = tensions.get("modal_contradiction", "")
        modal_count = tensions.get("modal_count", "")
        analysis_text = tensions.get("analysis", "")

        html += f'  <div class="section-title">Internal Tensions — {n_tensions}/{len(results)} articles ({round(100*n_tensions/len(results))}%)</div>\n'
        if analysis_text:
            html += f'  <div class="meta-observation">{esc(analysis_text)}</div>\n'
        html += '  <div class="tension-breakdown">\n'
        for t in tensions["tension_types"]:
            html += f'    <div class="tension-type"><span class="tension-count">{t["count"]}</span><div><span class="tension-name">{esc(t["type_name"])}</span><br><span class="tension-desc">{esc(t["description"])}</span></div></div>\n'
        html += '  </div>\n'

    # ── emergent clusters ─────────────────────────────────────────
    if clusters and "emergent_clusters" in clusters:
        html += '  <div class="section-title">Emergent Framing Clusters</div>\n'

        # meta-observation first
        meta = clusters.get("meta_observation", "")
        if meta:
            html += f'  <div class="meta-observation">{esc(meta)}</div>\n'

        for ci, cluster in enumerate(clusters["emergent_clusters"]):
            color = CLUSTER_PALETTE[ci % len(CLUSTER_PALETTE)]
            name = esc(cluster.get("cluster_name", f"Cluster {ci+1}"))
            desc = esc(cluster.get("description", ""))
            geo = esc(cluster.get("geographic_pattern", ""))
            conventional = cluster.get("maps_to_conventional_category")
            indices = cluster.get("member_indices", [])

            conv_note = f' <span class="cluster-meta">(≈ {esc(conventional)})</span>' if conventional else ' <span class="cluster-meta" style="color:#c77dff">[novel pattern]</span>'

            html += f"""
  <div class="cluster-header">
    <span class="cluster-name" style="background:{color}">{name}</span>
    <span class="cluster-meta">{len(indices)} outlet{"s" if len(indices) != 1 else ""}</span>
    {conv_note}
  </div>
  <div class="cluster-desc">{desc} <em>({geo})</em></div>
  <div class="cards">
"""
            for idx in indices:
                if 0 <= idx < len(results):
                    html += render_card(results[idx], color=color)
            html += "  </div>\n"

        # singletons
        singletons = clusters.get("singletons", [])
        if singletons:
            html += '  <div class="section-title">Singletons — Framings That Resist Clustering</div>\n'
            html += '  <div class="cards">\n'
            for s in singletons:
                idx = s.get("index", -1)
                if 0 <= idx < len(results):
                    r = results[idx]
                    reason = s.get("why_unique", "")
                    # inject singleton reason into the card
                    card_html = render_card(r, color="#c77dff")
                    # add singleton badge after card-header
                    badge = f'      <span class="singleton-badge">singleton</span>\n'
                    if reason:
                        badge += f'      <div class="card-authority">Why unique: {esc(reason)}</div>\n'
                    card_html = card_html.replace('</div>\n      <div class="card-summary">',
                                                  f'</div>\n{badge}      <div class="card-summary">', 1)
                    html += card_html
            html += '  </div>\n'
    else:
        # fallback: no clustering available, show all cards ungrouped
        html += '  <div class="section-title">Article Analyses</div>\n'
        html += '  <div class="cards">\n'
        for r in results:
            html += render_card(r)
        html += '  </div>\n'

    # ── unspeakable positions — promoted to first-class section ──
    if absence and absence.get("unspeakable_positions"):
        html += '  <div class="section-title">Positions the Global Media Corpus Refuses to Articulate</div>\n'
        html += '  <div class="unspeakable-section">\n'
        for pos in absence["unspeakable_positions"]:
            html += f'    <div class="unspeakable-item">{esc(pos)}</div>\n'
        html += '  </div>\n'

    # ── corpus-level absence report ───────────────────────────────
    if absence:
        html += '  <div class="section-title">What This Corpus Doesn\'t Say</div>\n'
        html += '  <div class="absence-section">\n'

        for label, key in [
            ("UNREPRESENTED ACTORS", "unrepresented_actors"),
            ("UNMADE ARGUMENTS", "unmade_arguments"),
            ("VOICELESS POPULATIONS", "voiceless_populations"),
            ("TIER 3 PREDICTIONS", "tier3_predictions"),
        ]:
            items = absence.get(key, [])
            if items:
                html += f'    <div class="absence-item"><span class="absence-label">{label}:</span> {esc("; ".join(items[:5]))}</div>\n'

        assessment = absence.get("overall_assessment", "")
        if assessment:
            html += f'    <div class="absence-item" style="font-style:italic; margin-top: 0.5rem">{esc(assessment)}</div>\n'

        html += '  </div>\n'

    # ── factual claims ────────────────────────────────────────────
    all_claims = []
    for r in results:
        for c in r.get("analysis", {}).get("factual_claims", []):
            if c and c not in all_claims:
                all_claims.append(c)
    if all_claims:
        html += '  <div class="section-title">Factual Claims Under Verification</div>\n'
        html += '  <div class="claims-section">\n'
        for claim in all_claims[:40]:
            html += f'    <div class="claim-item"><span class="claim-status">[UNVERIFIED]</span> {esc(claim)}</div>\n'
        html += '  </div>\n'

    # ── coverage gaps ─────────────────────────────────────────────
    if coverage:
        html += '  <div class="section-title">Coverage Gaps</div>\n'
        html += '  <div class="gaps-section">\n'
        missing_regions = coverage.get("regions", {}).get("missing", [])
        if missing_regions:
            html += f'    <div class="gap-item"><span class="gap-warn">⚠ MISSING REGIONS:</span> <strong>{esc(", ".join(missing_regions))}</strong></div>\n'
        missing_langs = coverage.get("languages", {}).get("top_languages_missing", [])
        if missing_langs:
            html += f'    <div class="gap-item"><span class="gap-warn">⚠ TOP LANGUAGES ABSENT:</span> <strong>{esc(", ".join(missing_langs))}</strong></div>\n'
        source_types = coverage.get("source_types", {})
        if source_types:
            parts = [f"{v} from {k}" for k, v in source_types.items()]
            html += f'    <div class="gap-item">Source breakdown: {", ".join(parts)}</div>\n'
        html += '  </div>\n'

    # ── transparency section ──────────────────────────────────────
    html += '  <div class="section-title">Methodological Transparency</div>\n'
    html += '  <div class="transparency-section">\n'
    html += '    <div class="transparency-item"><strong>Western infrastructure analyzing non-Western sources.</strong> This system was built with English-language tools, a Western-trained LLM (Qwen 32B), and categories that emerged from an initial English-language analytical frame. That is itself a perspective, not a neutral vantage point.</div>\n'
    html += '    <div class="transparency-item"><strong>Translation destroys framing evidence.</strong> Original-language terms are preserved where possible, and contested translations are flagged. But interpretation across languages is inherently approximate. Key distinctions (e.g., Arabic العدوان "aggression" vs. الضربة "strike") may be flattened.</div>\n'
    html += '    <div class="transparency-item"><strong>Tier 3 is entirely absent.</strong> Oral media, radio, WhatsApp forwards, sermons, mosque and church networks, bazaar conversations — the channels through which most of the world actually forms opinions about geopolitics — are invisible to this system. What you see is the digitally legible fraction of global discourse.</div>\n'
    html += '    <div class="transparency-item"><strong>Clustering reflects builder choices.</strong> The two-pass method lets categories emerge from data rather than being imposed. But the prompts, the LLM, and the corpus selection still shape what can emerge. Alternative methods would produce different patterns.</div>\n'
    html += '    <div class="transparency-item"><strong>GDELT over-represents the legible.</strong> GDELT indexes web-published text, heavily skewing toward English-language and digitally accessible outlets. Direct RSS pulls from curated outlets partially compensate, but significant gaps remain in sub-Saharan Africa, Central Asia, and indigenous-language media.</div>\n'
    html += '  </div>\n'

    html += f"""
  <footer>
    <p>NewsKaleidoscope &middot; Epistemic Mapping System</p>
    <p>Two-pass analysis: open-ended framing extraction → emergent clustering.
       Categories emerged from data, not imposed on it.</p>
    <p>Data sources: <a href="https://www.gdeltproject.org/">GDELT Project</a> + curated RSS feeds</p>
  </footer>
</div>
</body>
</html>"""
    return html


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(ANALYSIS_FILE):
        print(f"[output] ERROR: {ANALYSIS_FILE} not found. run pipeline.py first.")
        return

    with open(ANALYSIS_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)
    if not results:
        print("[output] no results to render.")
        return

    # load supplementary data
    clusters = None
    if os.path.exists(CLUSTERS_FILE):
        with open(CLUSTERS_FILE, "r", encoding="utf-8") as f:
            clusters = json.load(f)

    absence = None
    if os.path.exists(ABSENCE_FILE):
        with open(ABSENCE_FILE, "r", encoding="utf-8") as f:
            absence = json.load(f)

    coverage = None
    if os.path.exists(COVERAGE_FILE):
        with open(COVERAGE_FILE, "r", encoding="utf-8") as f:
            coverage = json.load(f)

    tensions = None
    if os.path.exists(TENSION_FILE):
        with open(TENSION_FILE, "r", encoding="utf-8") as f:
            tensions = json.load(f)

    html = generate_html(results, clusters, absence, coverage, tensions)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    n_tensions = sum(1 for r in results if r.get("analysis", {}).get("internal_tensions"))
    n_singletons = sum(1 for r in results if r.get("analysis", {}).get("singleton"))
    n_clusters = len(clusters.get("emergent_clusters", [])) if clusters else 0

    print(f"[output] generated {OUTPUT_FILE}")
    print(f"  articles: {len(results)}")
    print(f"  emergent clusters: {n_clusters}")
    print(f"  singletons: {n_singletons}")
    print(f"  internal tensions: {n_tensions}")
    print(f"  file size: {len(html):,} bytes")


if __name__ == "__main__":
    main()
