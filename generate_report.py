#!/usr/bin/env python3
"""
generate_report.py — render epistemic map HTML from PostgreSQL.

reads from DB, not from pipeline JSON artifacts.
this decouples report generation from pipeline runs:
a report can be regenerated at any time without re-running analysis.

usage:
    python3 generate_report.py                    # default event (latest)
    python3 generate_report.py --event-id 2       # specific event
"""

import argparse
import json
import os
from datetime import datetime

from db import get_session, Event, Source, Article, Analysis, Cluster, ClusterMembership
from sqlalchemy import func

OUTPUT_DIR = "docs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

# reuse rendering logic from output_generator.py
from output_generator import (
    generate_html, CLUSTER_PALETTE, COUNTRY_FLAGS, render_card, esc, get_flag
)


def load_event_data(session, event_id):
    """load all data for an event from PostgreSQL.

    returns (results, clusters, absence) in the same format
    that output_generator.generate_html() expects.
    """
    event = session.get(Event, event_id)
    if not event:
        print(f"event_id {event_id} not found")
        return None, None, None, None

    # load articles + analyses
    articles = session.query(Article).filter_by(event_id=event_id).all()
    results = []

    for art in articles:
        source = art.source
        analysis_record = session.query(Analysis).filter_by(
            article_id=art.id, event_id=event_id
        ).first()

        if not analysis_record:
            continue

        # reconstruct the analysis dict from DB fields
        raw = analysis_record.raw_llm_output or {}
        analysis = {
            "framing_description": analysis_record.primary_frame or "",
            "one_sentence_summary": raw.get("one_sentence_summary", ""),
            "authority_structure": raw.get("authority_structure", ""),
            "internal_tensions": raw.get("internal_tensions", ""),
            "who_is_quoted": raw.get("who_is_quoted", []),
            "whose_voice_is_absent": raw.get("whose_voice_is_absent", []),
            "factual_claims": raw.get("factual_claims", []),
            "absence_flags": analysis_record.absence_flags or [],
            "key_framing_language": analysis_record.positions or [],
            "original_framing_terms": raw.get("original_framing_terms", []),
            "english_approximations": raw.get("english_approximations", []),
            "contested_translations": raw.get("contested_translations", []),
            "original_language": raw.get("original_language", art.original_language or ""),
            "emotional_register": raw.get("emotional_register", ""),
            "translation_warning": raw.get("translation_warning", ""),
        }

        # check for cluster assignments
        memberships = session.query(ClusterMembership).filter_by(article_id=art.id).all()
        if memberships:
            clusters_for_article = []
            for m in memberships:
                cluster = session.get(Cluster, m.cluster_id)
                if cluster and not cluster.label.startswith("Singleton:"):
                    clusters_for_article.append(cluster.label)
            if clusters_for_article:
                analysis["emergent_cluster_assignments"] = clusters_for_article

            # check if singleton
            for m in memberships:
                cluster = session.get(Cluster, m.cluster_id)
                if cluster and cluster.label.startswith("Singleton:"):
                    analysis["singleton"] = True
                    analysis["singleton_reason"] = ""

        result = {
            "url": art.url,
            "title": art.title or "",
            "domain": (source.url or "").replace("https://", "").replace("http://", "").rstrip("/") if source else "",
            "sourcecountry": _code_to_country(source.country_code) if source else "",
            "sourcelang": art.original_language or "English",
            "source_type": source.source_type or "unknown" if source else "unknown",
            "outlet_name": source.name if source else "",
            "outlet_tier": {"A": 1, "B": 2, "C": 3}.get(source.tier, 0) if source else 0,
            "outlet_region": "unknown",
            "outlet_bias_notes": "",
            "analysis": analysis,
        }
        results.append(result)

    # load cluster data
    clusters = _load_clusters(session, event_id, results)

    # load absence report from analysis JSON (not yet stored in DB)
    absence = None
    absence_path = "analysis/absence_report.json"
    if os.path.exists(absence_path):
        with open(absence_path, "r", encoding="utf-8") as f:
            absence = json.load(f)

    # load coverage gaps
    coverage = _build_coverage(session, event_id, results)

    return results, clusters, absence, coverage


def _code_to_country(code):
    """reverse lookup: country code -> country name."""
    # build reverse map from seed_sources
    from seed_sources import COUNTRY_CODES
    reverse = {v: k for k, v in COUNTRY_CODES.items()}
    # add extra mappings
    reverse.update({
        "AL": "Albania", "AZ": "Azerbaijan", "BH": "Bahrain", "BG": "Bulgaria",
        "HR": "Croatia", "XK": "Kosovo", "LT": "Lithuania", "RO": "Romania",
        "SK": "Slovak Republic", "SY": "Syria", "UA": "Ukraine",
    })
    return reverse.get(code, code or "")


def _load_clusters(session, event_id, results):
    """load cluster data from DB in the format generate_html expects."""
    clusters_db = session.query(Cluster).filter_by(event_id=event_id).all()
    if not clusters_db:
        return None

    # build url -> index map
    url_to_idx = {r["url"]: i for i, r in enumerate(results)}

    emergent = []
    singletons = []

    for c in clusters_db:
        members = session.query(ClusterMembership).filter_by(cluster_id=c.id).all()
        member_article_ids = [m.article_id for m in members]

        # map article_ids to result indices
        indices = []
        for aid in member_article_ids:
            art = session.get(Article, aid)
            if art and art.url in url_to_idx:
                indices.append(url_to_idx[art.url])

        if c.label.startswith("Singleton:"):
            if indices:
                singletons.append({
                    "index": indices[0],
                    "why_unique": "",
                })
        else:
            emergent.append({
                "cluster_name": c.label,
                "description": "",  # not stored separately in DB
                "member_indices": indices,
                "geographic_pattern": json.dumps(c.geographic_signature) if c.geographic_signature else "",
                "maps_to_conventional_category": None,
            })

    if not emergent:
        return None

    return {
        "emergent_clusters": emergent,
        "singletons": singletons,
        "meta_observation": "",
    }


def _build_coverage(session, event_id, results):
    """build coverage report from DB data."""
    source_types = {}
    country_counts = {}
    for r in results:
        st = r.get("source_type", "unknown")
        source_types[st] = source_types.get(st, 0) + 1
        c = r.get("sourcecountry", "unknown")
        country_counts[c] = country_counts.get(c, 0) + 1

    return {
        "regions": {"covered": {}, "missing": []},
        "languages": {"covered": [], "top_languages_missing": []},
        "source_types": source_types,
        "countries": {"total": len(country_counts), "distribution": country_counts},
    }


def main():
    parser = argparse.ArgumentParser(description="generate epistemic map HTML from DB")
    parser.add_argument("--event-id", type=int, default=None,
                        help="event ID to generate report for (default: latest)")
    args = parser.parse_args()

    session = get_session()

    if args.event_id:
        event_id = args.event_id
    else:
        # find latest event
        event = session.query(Event).order_by(Event.id.desc()).first()
        if not event:
            print("no events in database")
            session.close()
            return
        event_id = event.id

    event = session.get(Event, event_id)
    print(f"generating report for event: {event.title} (id={event_id})")

    results, clusters, absence, coverage = load_event_data(session, event_id)
    if not results:
        print("no articles found for this event")
        session.close()
        return

    # load tension analysis if available
    tensions = None
    tension_path = "analysis/tension_analysis.json"
    if os.path.exists(tension_path):
        with open(tension_path, "r", encoding="utf-8") as f:
            tensions = json.load(f)

    html = generate_html(results, clusters, absence, coverage, tensions)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    n_tensions = sum(1 for r in results if r.get("analysis", {}).get("internal_tensions"))
    n_clusters = len(clusters.get("emergent_clusters", [])) if clusters else 0

    print(f"generated {OUTPUT_FILE}")
    print(f"  articles: {len(results)}")
    print(f"  clusters: {n_clusters}")
    print(f"  tensions: {n_tensions}")
    print(f"  file size: {len(html):,} bytes")

    session.close()


if __name__ == "__main__":
    main()
