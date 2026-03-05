#!/usr/bin/env python3
"""
migrate_iran_corpus.py — migrate existing 94 articles + analyses + clusters into PostgreSQL.

reads from:
    analysis/all_results.json
    analysis/emergent_clusters.json
    analysis/absence_report.json

writes to:
    events, sources, articles, analyses, clusters, cluster_memberships, coverage_gaps
"""

import json
import hashlib
import os
from datetime import date, datetime

from db import get_session, Event, Source, Article, Analysis, Cluster, ClusterMembership, CoverageGap
from seed_sources import COUNTRY_CODES

# all ISO 3166-1 alpha-2 codes for coverage gap detection
ALL_COUNTRY_CODES = set(COUNTRY_CODES.values())
# add common codes not in seed_sources
ALL_COUNTRY_CODES.update([
    "AF", "AM", "AZ", "BH", "BY", "BO", "CL", "CU", "CY", "EC", "GE",
    "GT", "HN", "HU", "IS", "JM", "KW", "KZ", "LY", "MM", "MN", "MZ",
    "NA", "NE", "NI", "OM", "PA", "PE", "QA", "RS", "SD", "SN", "SO",
    "SY", "TJ", "TM", "TT", "UY", "UZ", "VE", "YE", "ZM", "ZW",
])


def find_or_create_source(session, article_data):
    """find source by domain match, or create a minimal source record."""
    domain = article_data.get("domain", "")
    url = f"https://{domain}" if domain else article_data.get("url", "")

    # try exact domain match against existing sources
    source = session.query(Source).filter(
        Source.url.ilike(f"%{domain}%")
    ).first() if domain else None

    if source:
        return source

    # create minimal source record
    country = article_data.get("sourcecountry", "")
    country_code = COUNTRY_CODES.get(country, "")
    lang = article_data.get("sourcelang", "English")

    # map language name to iso code
    lang_codes = {
        "English": "en", "Arabic": "ar", "Chinese": "zh", "French": "fr",
        "German": "de", "Spanish": "es", "Portuguese": "pt", "Russian": "ru",
        "Turkish": "tr", "Korean": "ko", "Italian": "it", "Albanian": "sq",
        "Bulgarian": "bg", "Croatian": "hr", "Czech": "cs", "Norwegian": "no",
        "Romanian": "ro", "Slovak": "sk", "Lithuanian": "lt", "Persian": "fa",
    }
    lang_code = lang_codes.get(lang, "en")

    # determine source type from article metadata
    source_type_map = {
        "gdelt": "gdelt_discovered",
        "rss_curated": "regional_flagship",
        "iranian_targeted": "regional_flagship",
        "un_security_council": "un_security_council",
    }
    source_type = source_type_map.get(article_data.get("source_type", "gdelt"), "gdelt_discovered")

    source = Source(
        name=article_data.get("outlet_name", domain),
        url=f"https://{domain}",
        country_code=country_code,
        language_code=lang_code,
        source_type=source_type,
        editorial_language=lang,
        tier="C" if source_type == "gdelt_discovered" else "B",
        is_state_adjacent=False,
    )
    session.add(source)
    session.flush()  # get the id
    return source


def migrate_articles(session, event, results):
    """migrate all articles and their analyses into the DB."""
    articles_migrated = 0
    articles_skipped = 0
    articles_failed = []
    analyses_migrated = 0

    # build url -> article_id map for cluster membership later
    url_to_article_id = {}

    for i, r in enumerate(results):
        url = r.get("url", "")
        if not url:
            articles_failed.append(f"[{i}] no url")
            continue

        # check for duplicate
        existing = session.query(Article).filter_by(url=url).first()
        if existing:
            articles_skipped += 1
            url_to_article_id[url] = existing.id
            continue

        # find or create source
        source = find_or_create_source(session, r)

        # get cached text
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join("cache", f"{url_hash}.txt")
        raw_text = None
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                raw_text = f.read()

        analysis = r.get("analysis", {})
        lang = r.get("sourcelang", "English")
        is_english = lang.lower() in ("english", "eng", "en")

        # build original_language_terms from analysis data
        orig_terms = analysis.get("original_framing_terms", [])
        eng_approx = analysis.get("english_approximations", [])
        # combine into structured list
        terms_data = []
        for j, term in enumerate(orig_terms):
            entry = {"term": term}
            if j < len(eng_approx):
                entry["english"] = eng_approx[j]
            terms_data.append(entry)

        article = Article(
            event_id=event.id,
            source_id=source.id,
            url=url,
            title=r.get("title", ""),
            original_language=lang if not is_english else "English",
            translation_language="English" if not is_english else None,
            raw_text=raw_text,
            translated_text=raw_text if is_english else None,  # existing corpus used qwen translation inline
            publication_date=None,  # not available in existing data
            original_language_terms=terms_data if terms_data else [],
            absence_flags=analysis.get("absence_flags", []),
        )
        session.add(article)
        session.flush()
        url_to_article_id[url] = article.id
        articles_migrated += 1

        # migrate analysis
        positions = analysis.get("key_framing_language", [])
        internal_tensions = []
        tension_text = analysis.get("internal_tensions")
        if tension_text:
            internal_tensions = [{"description": tension_text}] if isinstance(tension_text, str) else tension_text

        absence_flags = analysis.get("absence_flags", [])
        # extract unspeakable positions from analysis if present
        unspeakable = []
        whose_absent = analysis.get("whose_voice_is_absent", [])
        if whose_absent:
            unspeakable = [f"voice absent: {v}" for v in whose_absent]

        analysis_record = Analysis(
            article_id=article.id,
            event_id=event.id,
            model_used="qwen3:32b",
            primary_frame=analysis.get("framing_description", analysis.get("one_sentence_summary", "")),
            frame_confidence=None,
            positions=positions,
            internal_tensions=internal_tensions,
            absence_flags=absence_flags,
            unspeakable_positions=unspeakable,
            uncertainty_score=None,
            raw_llm_output=analysis,
        )
        session.add(analysis_record)
        analyses_migrated += 1

    return articles_migrated, articles_skipped, articles_failed, analyses_migrated, url_to_article_id


def migrate_clusters(session, event, cluster_data, results, url_to_article_id):
    """migrate clusters and memberships into DB."""
    clusters_written = 0
    memberships_written = 0

    if not cluster_data or "emergent_clusters" not in cluster_data:
        return clusters_written, memberships_written

    for c in cluster_data["emergent_clusters"]:
        indices = c.get("member_indices", [])

        # build geographic signature
        geo_sig = {}
        for idx in indices:
            if 0 <= idx < len(results):
                country = results[idx].get("sourcecountry", "unknown")
                geo_sig[country] = geo_sig.get(country, 0) + 1

        cluster = Cluster(
            event_id=event.id,
            label=c.get("cluster_name", ""),
            article_count=len(indices),
            geographic_signature=geo_sig,
            stability_score=None,
        )
        session.add(cluster)
        session.flush()
        clusters_written += 1

        # write memberships
        for idx in indices:
            if 0 <= idx < len(results):
                url = results[idx].get("url", "")
                article_id = url_to_article_id.get(url)
                if article_id:
                    membership = ClusterMembership(
                        article_id=article_id,
                        cluster_id=cluster.id,
                        distance_from_centroid=None,
                    )
                    session.add(membership)
                    memberships_written += 1

    # write singletons as individual clusters
    for s in cluster_data.get("singletons", []):
        idx = s.get("index", -1)
        if 0 <= idx < len(results):
            url = results[idx].get("url", "")
            article_id = url_to_article_id.get(url)
            title_frag = results[idx].get("title", "")[:60]

            cluster = Cluster(
                event_id=event.id,
                label=f"Singleton: {title_frag}",
                article_count=1,
                geographic_signature={results[idx].get("sourcecountry", "unknown"): 1},
                stability_score=None,
            )
            session.add(cluster)
            session.flush()
            clusters_written += 1

            if article_id:
                membership = ClusterMembership(
                    article_id=article_id,
                    cluster_id=cluster.id,
                    distance_from_centroid=0.0,
                )
                session.add(membership)
                memberships_written += 1

    return clusters_written, memberships_written


def seed_coverage_gaps(session, event, results):
    """seed coverage_gaps for countries with zero articles."""
    # collect countries that have coverage
    covered_countries = set()
    for r in results:
        country = r.get("sourcecountry", "")
        code = COUNTRY_CODES.get(country, "")
        if code:
            covered_countries.add(code)

    # find gaps
    gaps_written = 0
    for code in sorted(ALL_COUNTRY_CODES - covered_countries):
        gap = CoverageGap(
            event_id=event.id,
            country_code=code,
            source_type="all",
            gap_description="no sources in current corpus",
            attempted=False,
            retrieved=False,
            dark_layer_notes=None,
        )
        session.add(gap)
        gaps_written += 1

    return gaps_written


def main():
    # load existing analysis data
    with open("analysis/all_results.json", "r", encoding="utf-8") as f:
        results = json.load(f)

    cluster_data = None
    if os.path.exists("analysis/emergent_clusters.json"):
        with open("analysis/emergent_clusters.json", "r", encoding="utf-8") as f:
            cluster_data = json.load(f)

    print(f"loaded {len(results)} articles, {len(cluster_data.get('emergent_clusters', [])) if cluster_data else 0} clusters")

    session = get_session()
    try:
        # create the iran event
        event = Event(
            title="US-Israeli Military Strikes on Iran",
            description="Operation Epic Fury — coordinated US-Israeli military action against Iranian nuclear and missile infrastructure",
            event_type="military",
            event_date=date(2025, 2, 28),
            primary_actors=["United States", "Israel", "Iran"],
            geographic_scope="regional",
        )
        session.add(event)
        session.flush()
        print(f"\nevent created: id={event.id}, title='{event.title}'")

        # migrate articles + analyses
        art_migrated, art_skipped, art_failed, analyses_migrated, url_to_article_id = \
            migrate_articles(session, event, results)

        # migrate clusters
        clusters_written, memberships_written = \
            migrate_clusters(session, event, cluster_data, results, url_to_article_id)

        # seed coverage gaps
        gaps_written = seed_coverage_gaps(session, event, results)

        session.commit()

        # report
        print(f"\n{'='*60}")
        print(f"MIGRATION REPORT")
        print(f"{'='*60}")
        print(f"  event id: {event.id}")
        print(f"  articles migrated: {art_migrated} / {len(results)}")
        print(f"  articles skipped (duplicate URL): {art_skipped}")
        if art_failed:
            print(f"  articles failed: {len(art_failed)}")
            for f_msg in art_failed:
                print(f"    {f_msg}")
        print(f"  analyses migrated: {analyses_migrated}")
        print(f"  clusters written: {clusters_written}")
        print(f"  cluster memberships written: {memberships_written}")
        print(f"  coverage gaps seeded: {gaps_written}")

        # count new sources created
        new_sources = session.query(Source).filter_by(source_type="gdelt_discovered").count()
        print(f"  new sources created (GDELT-discovered): {new_sources}")

        print(f"\n  IRAN EVENT ID: {event.id}")
        print(f"  (record this for Session 3)")
        print(f"{'='*60}")

    except Exception as e:
        session.rollback()
        print(f"MIGRATION FAILED: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
