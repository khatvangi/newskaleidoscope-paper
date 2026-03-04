#!/usr/bin/env python3
"""
output_generator.py — generate static HTML from analysis results.
outputs docs/index.html for Cloudflare Pages deployment.
"""

import json
import os
from datetime import datetime

ANALYSIS_FILE = "analysis/all_results.json"
OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# position type → color + label
POSITION_COLORS = {
    "endorsement": ("#2d6a4f", "Endorsement"),
    "procedural_objection": ("#e76f51", "Procedural Objection"),
    "sovereignty_opposition": ("#d62828", "Sovereignty Opposition"),
    "great_power_framing": ("#457b9d", "Great Power Framing"),
    "non_aligned_ambiguity": ("#8d99ae", "Non-Aligned Ambiguity"),
    "religious_framing": ("#7b2cbf", "Religious Framing"),
    "whataboutism_cynical": ("#bc6c25", "Whataboutism (Cynical)"),
    "whataboutism_legitimate": ("#606c38", "Whataboutism (Legitimate)"),
}

# country → flag emoji (common ones)
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
    "Australia": "🇦🇺",
}


def get_flag(country):
    """return flag emoji for country, or globe if unknown."""
    return COUNTRY_FLAGS.get(country, "🌐")


def escape_html(text):
    """basic HTML escaping."""
    if not isinstance(text, str):
        return str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html(results):
    """generate the full HTML page from analysis results."""
    # separate tier 1 and tier 2
    tier1 = [r for r in results if r.get("outlet_tier", 0) != 2]
    tier2 = [r for r in results if r.get("outlet_tier", 0) == 2]

    # group tier1 by position_type
    clusters = {}
    for r in tier1:
        pt = r.get("analysis", {}).get("position_type", "unknown")
        clusters.setdefault(pt, []).append(r)

    # collect all factual claims
    all_claims = []
    for r in results:
        claims = r.get("analysis", {}).get("factual_claims", [])
        for c in claims:
            if c and c not in all_claims:
                all_claims.append(c)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── build HTML ────────────────────────────────────────────────
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
    --bg: #0f1419;
    --surface: #1a1f2e;
    --surface2: #232838;
    --text: #e8e6e3;
    --text-dim: #9ca3af;
    --accent: #60a5fa;
    --border: #2d3348;
  }}

  body {{
    font-family: 'Newsreader', Georgia, serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 0;
  }}

  .container {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem 1.5rem;
  }}

  header {{
    text-align: center;
    padding: 3rem 1rem 2rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 2rem;
  }}

  header h1 {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 1rem;
  }}

  header h2 {{
    font-family: 'Newsreader', serif;
    font-size: 2.2rem;
    font-weight: 600;
    line-height: 1.2;
    margin-bottom: 0.75rem;
  }}

  header .meta {{
    font-size: 0.9rem;
    color: var(--text-dim);
    font-style: italic;
  }}

  .section-title {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-dim);
    margin: 2.5rem 0 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
  }}

  .cluster-header {{
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin: 2rem 0 1rem;
  }}

  .cluster-badge {{
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: white;
  }}

  .cluster-count {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    color: var(--text-dim);
  }}

  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 1rem;
    margin-bottom: 1rem;
  }}

  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.25rem;
    transition: border-color 0.2s;
  }}

  .card:hover {{
    border-color: var(--accent);
  }}

  .card-header {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }}

  .card-flag {{
    font-size: 1.3rem;
  }}

  .card-outlet {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    font-weight: 700;
    color: var(--accent);
  }}

  .card-country {{
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-left: auto;
  }}

  .card-summary {{
    font-size: 1rem;
    line-height: 1.5;
    margin-bottom: 0.75rem;
    font-style: italic;
  }}

  .card-framing {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }}

  .frame-tag {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    color: var(--text-dim);
  }}

  .claims-section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem;
    margin-top: 1rem;
  }}

  .claim-item {{
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.9rem;
  }}

  .claim-item:last-child {{
    border-bottom: none;
  }}

  .claim-status {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    color: #fbbf24;
    margin-right: 0.5rem;
  }}

  footer {{
    text-align: center;
    padding: 2rem 1rem;
    margin-top: 3rem;
    border-top: 1px solid var(--border);
    font-size: 0.8rem;
    color: var(--text-dim);
  }}

  footer a {{
    color: var(--accent);
    text-decoration: none;
  }}

  @media (max-width: 600px) {{
    .cards {{ grid-template-columns: 1fr; }}
    header h2 {{ font-size: 1.5rem; }}
    .container {{ padding: 1rem; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>NewsKaleidoscope</h1>
    <h2>US-Israel Strikes on Iran: Global Epistemic Map</h2>
    <p class="meta">
      {len(results)} outlets analyzed &middot; Generated {now}
      &middot; Phase 1: Position Mapping
    </p>
  </header>
"""

    # ── position clusters ─────────────────────────────────────────
    html += '  <div class="section-title">Position Clusters — Tier 1 Flagship Outlets</div>\n'

    for pt, articles in sorted(clusters.items(), key=lambda x: -len(x[1])):
        color, label = POSITION_COLORS.get(pt, ("#6b7280", pt))
        html += f"""
  <div class="cluster-header">
    <span class="cluster-badge" style="background:{color}">{escape_html(label)}</span>
    <span class="cluster-count">{len(articles)} outlet{"s" if len(articles) != 1 else ""}</span>
  </div>
  <div class="cards">
"""
        for r in articles:
            analysis = r.get("analysis", {})
            name = escape_html(r.get("outlet_name", r.get("domain", "")))
            country = r.get("sourcecountry", "")
            flag = get_flag(country)
            summary = escape_html(analysis.get("one_sentence_summary", "No summary available"))
            framing = analysis.get("key_framing_language", [])

            html += f"""    <div class="card" style="border-left: 3px solid {color}">
      <div class="card-header">
        <span class="card-flag">{flag}</span>
        <span class="card-outlet">{name}</span>
        <span class="card-country">{escape_html(country)}</span>
      </div>
      <div class="card-summary">{summary}</div>
      <div class="card-framing">
"""
            for phrase in framing[:5]:
                html += f'        <span class="frame-tag">{escape_html(phrase)}</span>\n'

            html += """      </div>
    </div>
"""
        html += "  </div>\n"

    # ── tier 2 religious/institutional ────────────────────────────
    if tier2:
        html += '  <div class="section-title">Tier 2 — Religious &amp; Institutional Positions</div>\n'
        html += '  <div class="cards">\n'

        for r in tier2:
            analysis = r.get("analysis", {})
            name = escape_html(r.get("outlet_name", r.get("domain", "")))
            country = r.get("sourcecountry", "")
            flag = get_flag(country)
            summary = escape_html(analysis.get("one_sentence_summary", "No summary available"))
            pt = analysis.get("position_type", "unknown")
            color, label = POSITION_COLORS.get(pt, ("#6b7280", pt))

            html += f"""    <div class="card" style="border-left: 3px solid {color}">
      <div class="card-header">
        <span class="card-flag">{flag}</span>
        <span class="card-outlet">{name}</span>
        <span class="card-country">{escape_html(country)}</span>
      </div>
      <div class="card-summary">{summary}</div>
      <div class="card-framing">
        <span class="frame-tag">{escape_html(label)}</span>
      </div>
    </div>
"""
        html += "  </div>\n"

    # ── factual claims ────────────────────────────────────────────
    if all_claims:
        html += '  <div class="section-title">Factual Claims Under Verification</div>\n'
        html += '  <div class="claims-section">\n'

        for claim in all_claims[:30]:  # cap at 30
            html += f"""    <div class="claim-item">
      <span class="claim-status">[UNVERIFIED]</span>
      {escape_html(claim)}
    </div>
"""
        html += "  </div>\n"

    # ── footer ────────────────────────────────────────────────────
    html += f"""
  <footer>
    <p>NewsKaleidoscope &middot; Epistemic Mapping System</p>
    <p>Position extraction via LLM analysis. Claims require independent verification.</p>
    <p>Data source: <a href="https://www.gdeltproject.org/">GDELT Project</a></p>
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

    html = generate_html(results)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[output] generated {OUTPUT_FILE}")
    print(f"  articles rendered: {len(results)}")
    print(f"  file size: {len(html):,} bytes")


if __name__ == "__main__":
    main()
