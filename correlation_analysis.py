#!/usr/bin/env python3
"""
correlation_analysis.py — session 5, task 6.

tests hypotheses about relationships between syntactic features and
council confidence levels. specifically:

1. does passive_voice_ratio predict CONTESTED council confidence?
2. does attribution_rate predict CONTESTED?
3. does elaboration_ratio predict CONTESTED?
4. US articles vs non-US: syntactic profile comparison
5. technical_strategic register vs others: syntactic profile comparison

uses scipy for statistical tests. no LLM calls.
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
from scipy import stats
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("correlation")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
RUN_ID = "session_005"


def load_data(conn):
    """load syntactic features joined with council verdicts and analyses."""
    rows = conn.execute(text("""
        SELECT
            sf.article_id,
            sf.passive_voice_ratio,
            sf.attribution_rate,
            sf.elaboration_ratio,
            sf.tokenism_flag,
            sf.severe_tokenism_flag,
            sf.opening_subject,
            sf.direct_quotes_by_actor,
            sf.concessive_constructions,
            lcv.confidence_level,
            s.country_code,
            s.name as outlet,
            a.original_language
        FROM syntactic_features sf
        JOIN articles a ON sf.article_id = a.id
        LEFT JOIN sources s ON a.source_id = s.id
        LEFT JOIN llm_council_verdicts lcv ON sf.article_id = lcv.article_id
        WHERE sf.run_id = :rid
        ORDER BY sf.article_id
    """), {"rid": RUN_ID})

    data = []
    for r in rows:
        data.append({
            'article_id': r.article_id,
            'passive_voice_ratio': r.passive_voice_ratio or 0,
            'attribution_rate': r.attribution_rate or 0,
            'elaboration_ratio': r.elaboration_ratio,
            'tokenism_flag': r.tokenism_flag,
            'severe_tokenism_flag': r.severe_tokenism_flag,
            'opening_subject': r.opening_subject,
            'direct_quotes_by_actor': r.direct_quotes_by_actor or {},
            'concessive_constructions': r.concessive_constructions or [],
            'confidence_level': r.confidence_level,
            'country_code': r.country_code or '??',
            'outlet': r.outlet or '??',
            'language': r.original_language or 'en',
            'is_contested': 1 if r.confidence_level == 'contested' else 0,
            'is_us': 1 if r.country_code == 'US' else 0,
        })
    return data


def load_register_data(conn):
    """load session 4 register analysis results."""
    rows = conn.execute(text("""
        SELECT article_id, raw_llm_output
        FROM analyses
        WHERE model_used LIKE '%session_004%'
    """))
    register_map = {}
    for r in rows:
        output = r.raw_llm_output or {}
        registers = output.get('register', [])
        register_map[r.article_id] = registers
    return register_map


def load_actor_framing(conn):
    """load vocabulary asymmetry data."""
    rows = conn.execute(text("""
        SELECT article_id, actor, framing_score, outlet_domain
        FROM actor_framing
        WHERE run_id = :rid
    """), {"rid": RUN_ID})
    framing = defaultdict(dict)
    for r in rows:
        framing[r.article_id][r.actor] = r.framing_score
    return framing


def point_biserial(continuous, binary, label):
    """compute point-biserial correlation with p-value."""
    if len(set(binary)) < 2:
        return None
    r, p = stats.pointbiserialr(binary, continuous)
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
    return {"r": round(r, 4), "p": round(p, 4), "sig": sig, "label": label}


def main():
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        data = load_data(conn)
        register_map = load_register_data(conn)
        framing_data = load_actor_framing(conn)

    if not data:
        log.error("no syntactic feature data found — run syntax_analyzer.py first")
        return

    print("\n" + "=" * 70)
    print("SESSION 5 — CORRELATION ANALYSIS")
    print(f"  articles with syntactic features: {len(data)}")
    print("=" * 70)

    # ── hypothesis 1: passive voice predicts CONTESTED ─────────────
    pv = [d['passive_voice_ratio'] for d in data]
    contested = [d['is_contested'] for d in data]

    print(f"\n{'─' * 70}")
    print("HYPOTHESIS 1: Passive voice ratio predicts CONTESTED confidence")
    print(f"{'─' * 70}")

    result = point_biserial(pv, contested, "passive_voice × contested")
    if result:
        print(f"  r = {result['r']:+.4f}, p = {result['p']:.4f} ({result['sig']})")
        if result['p'] < 0.05:
            print(f"  → CONFIRMED: passive voice {'positively' if result['r'] > 0 else 'negatively'} "
                  f"correlates with contested confidence")
        else:
            print(f"  → NOT CONFIRMED: no significant correlation")

    # mean comparison
    contested_pv = [d['passive_voice_ratio'] for d in data if d['is_contested']]
    non_contested_pv = [d['passive_voice_ratio'] for d in data if not d['is_contested']]
    print(f"  contested mean PV: {np.mean(contested_pv):.3f} (n={len(contested_pv)})")
    print(f"  non-contested mean PV: {np.mean(non_contested_pv):.3f} (n={len(non_contested_pv)})")
    t, p = stats.ttest_ind(contested_pv, non_contested_pv)
    print(f"  t-test: t={t:.3f}, p={p:.4f}")

    # ── hypothesis 2: attribution rate predicts CONTESTED ──────────
    attr = [d['attribution_rate'] for d in data]

    print(f"\n{'─' * 70}")
    print("HYPOTHESIS 2: Attribution rate predicts CONTESTED confidence")
    print(f"{'─' * 70}")

    result = point_biserial(attr, contested, "attribution × contested")
    if result:
        print(f"  r = {result['r']:+.4f}, p = {result['p']:.4f} ({result['sig']})")
        if result['p'] < 0.05:
            print(f"  → CONFIRMED: attribution rate {'positively' if result['r'] > 0 else 'negatively'} "
                  f"correlates with contested confidence")
        else:
            print(f"  → NOT CONFIRMED: no significant correlation")

    contested_attr = [d['attribution_rate'] for d in data if d['is_contested']]
    non_contested_attr = [d['attribution_rate'] for d in data if not d['is_contested']]
    print(f"  contested mean attr: {np.mean(contested_attr):.3f} (n={len(contested_attr)})")
    print(f"  non-contested mean attr: {np.mean(non_contested_attr):.3f} (n={len(non_contested_attr)})")

    # ── hypothesis 3: elaboration ratio predicts CONTESTED ─────────
    elab_data = [(d['elaboration_ratio'], d['is_contested']) for d in data if d['elaboration_ratio'] is not None]

    print(f"\n{'─' * 70}")
    print("HYPOTHESIS 3: Elaboration ratio predicts CONTESTED confidence")
    print(f"{'─' * 70}")

    if elab_data:
        elab_vals = [e[0] for e in elab_data]
        elab_contested = [e[1] for e in elab_data]
        result = point_biserial(elab_vals, elab_contested, "elaboration × contested")
        if result:
            print(f"  r = {result['r']:+.4f}, p = {result['p']:.4f} ({result['sig']})")
        print(f"  articles with elaboration data: {len(elab_data)}")

    # ── US vs non-US comparison ────────────────────────────────────
    print(f"\n{'─' * 70}")
    print("US ARTICLES vs NON-US: SYNTACTIC PROFILE COMPARISON")
    print(f"{'─' * 70}")

    us_articles = [d for d in data if d['country_code'] == 'US']
    non_us = [d for d in data if d['country_code'] != 'US']

    print(f"  US articles: {len(us_articles)}")
    print(f"  non-US articles: {len(non_us)}")

    if us_articles and non_us:
        us_pv = [d['passive_voice_ratio'] for d in us_articles]
        nonus_pv = [d['passive_voice_ratio'] for d in non_us]
        t, p = stats.ttest_ind(us_pv, nonus_pv)
        print(f"\n  passive voice:")
        print(f"    US mean: {np.mean(us_pv):.3f}, non-US mean: {np.mean(nonus_pv):.3f}")
        print(f"    t={t:.3f}, p={p:.4f} {'*' if p < 0.05 else 'ns'}")

        us_attr = [d['attribution_rate'] for d in us_articles]
        nonus_attr = [d['attribution_rate'] for d in non_us]
        t, p = stats.ttest_ind(us_attr, nonus_attr)
        print(f"\n  attribution rate:")
        print(f"    US mean: {np.mean(us_attr):.3f}, non-US mean: {np.mean(nonus_attr):.3f}")
        print(f"    t={t:.3f}, p={p:.4f} {'*' if p < 0.05 else 'ns'}")

        # opening subject
        print(f"\n  opening subject distribution:")
        from syntax_analyzer import classify_actor
        us_openers = Counter()
        nonus_openers = Counter()
        for d in us_articles:
            if d['opening_subject']:
                us_openers[classify_actor(d['opening_subject'])] += 1
        for d in non_us:
            if d['opening_subject']:
                nonus_openers[classify_actor(d['opening_subject'])] += 1
        print(f"    US articles: {dict(us_openers)}")
        print(f"    non-US articles: {dict(nonus_openers)}")

    # ── technical_strategic register vs others ─────────────────────
    print(f"\n{'─' * 70}")
    print("TECHNICAL_STRATEGIC REGISTER vs OTHERS: SYNTACTIC COMPARISON")
    print(f"{'─' * 70}")

    tech_ids = {aid for aid, regs in register_map.items() if 'technical_strategic' in regs}
    tech_articles = [d for d in data if d['article_id'] in tech_ids]
    non_tech = [d for d in data if d['article_id'] not in tech_ids]

    print(f"  technical_strategic articles: {len(tech_articles)}")
    print(f"  other articles: {len(non_tech)}")

    if tech_articles and non_tech:
        tech_pv = [d['passive_voice_ratio'] for d in tech_articles]
        nontech_pv = [d['passive_voice_ratio'] for d in non_tech]
        t, p = stats.ttest_ind(tech_pv, nontech_pv)
        print(f"\n  passive voice:")
        print(f"    tech_strategic mean: {np.mean(tech_pv):.3f}, other mean: {np.mean(nontech_pv):.3f}")
        print(f"    t={t:.3f}, p={p:.4f} {'*' if p < 0.05 else 'ns'}")

        tech_attr = [d['attribution_rate'] for d in tech_articles]
        nontech_attr = [d['attribution_rate'] for d in non_tech]
        t, p = stats.ttest_ind(tech_attr, nontech_attr)
        print(f"\n  attribution rate:")
        print(f"    tech_strategic mean: {np.mean(tech_attr):.3f}, other mean: {np.mean(nontech_attr):.3f}")
        print(f"    t={t:.3f}, p={p:.4f} {'*' if p < 0.05 else 'ns'}")

        # concessive constructions
        tech_conc = [len(d['concessive_constructions']) for d in tech_articles]
        nontech_conc = [len(d['concessive_constructions']) for d in non_tech]
        t, p = stats.ttest_ind(tech_conc, nontech_conc)
        print(f"\n  concessive constructions per article:")
        print(f"    tech_strategic mean: {np.mean(tech_conc):.1f}, other mean: {np.mean(nontech_conc):.1f}")
        print(f"    t={t:.3f}, p={p:.4f} {'*' if p < 0.05 else 'ns'}")

    # ── vocabulary asymmetry × council confidence ──────────────────
    print(f"\n{'─' * 70}")
    print("VOCABULARY FRAMING × COUNCIL CONFIDENCE")
    print(f"{'─' * 70}")

    if framing_data:
        # for each article, compute us-iran framing gap
        article_gaps = {}
        for aid, actors in framing_data.items():
            us_scores = [v for k, v in actors.items() if k in ("US", "Israel", "IDF")]
            iran_scores = [v for k, v in actors.items() if k in ("Iran", "IRGC", "Hezbollah")]
            if us_scores and iran_scores:
                us_avg = sum(us_scores) / len(us_scores)
                iran_avg = sum(iran_scores) / len(iran_scores)
                article_gaps[aid] = us_avg - iran_avg

        # correlate with contested
        gap_data = []
        for d in data:
            if d['article_id'] in article_gaps:
                gap_data.append((article_gaps[d['article_id']], d['is_contested']))

        if gap_data:
            gaps = [g[0] for g in gap_data]
            gap_contested = [g[1] for g in gap_data]
            result = point_biserial(gaps, gap_contested, "vocab_gap × contested")
            if result:
                print(f"  framing gap (US-Iran) × contested: r={result['r']:+.4f}, p={result['p']:.4f} ({result['sig']})")
            print(f"  articles with both vocab and council data: {len(gap_data)}")

    # ── multi-variable profile of contested articles ───────────────
    print(f"\n{'─' * 70}")
    print("CONTESTED ARTICLE PROFILE (top candidates for presupposition extraction)")
    print(f"{'─' * 70}")

    # rank articles by "strategic ambiguity" score
    # high passive + high attribution + high elaboration = sophisticated concealment
    for d in data:
        elab = d['elaboration_ratio'] if d['elaboration_ratio'] else 1.0
        d['ambiguity_score'] = d['passive_voice_ratio'] * 0.3 + d['attribution_rate'] * 0.3 + min(elab / 10, 1.0) * 0.4

    contested_articles = sorted(
        [d for d in data if d['is_contested']],
        key=lambda x: x['ambiguity_score'],
        reverse=True
    )

    print(f"\n  top 15 contested articles by strategic ambiguity score:")
    print(f"  {'ID':>4} {'CC':>3} {'PV':>5} {'ATTR':>5} {'ELAB':>6} {'SCORE':>6} {'Outlet'}")
    for d in contested_articles[:15]:
        elab_str = f"{d['elaboration_ratio']:.1f}" if d['elaboration_ratio'] else "N/A"
        print(f"  {d['article_id']:>4} {d['country_code']:>3} {d['passive_voice_ratio']:.2f}"
              f"  {d['attribution_rate']:.2f}  {elab_str:>5}  {d['ambiguity_score']:.3f}"
              f"  {d['outlet'][:30]}")

    # save correlation results to json
    outfile = f"analysis/session5_correlations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(outfile, 'w') as f:
        json.dump({
            'run_id': RUN_ID,
            'created': datetime.now().isoformat(),
            'method': 'point-biserial correlation + t-tests',
            'n_articles': len(data),
            'note': 'see stdout for full report — this file captures the ranked article list',
            'top_ambiguity_articles': [
                {'article_id': d['article_id'], 'country_code': d['country_code'],
                 'outlet': d['outlet'], 'ambiguity_score': d['ambiguity_score'],
                 'passive_voice_ratio': d['passive_voice_ratio'],
                 'attribution_rate': d['attribution_rate'],
                 'elaboration_ratio': d['elaboration_ratio']}
                for d in contested_articles[:20]
            ],
        }, f, indent=2)
    print(f"\n  saved to {outfile}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
