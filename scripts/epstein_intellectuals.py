#!/usr/bin/env python3
"""
epstein_intellectuals.py — build the "intellectual enablers" sub-corpus.

identifies articles about academics, scientists, doctors, spiritual gurus who
associated with epstein. builds entity database, filters media corpus,
and prepares for the "Academic Reckoning" report.

usage:
  python3 scripts/epstein_intellectuals.py build       # build entity DB + tag articles
  python3 scripts/epstein_intellectuals.py status      # show current stats
  python3 scripts/epstein_intellectuals.py export       # export tagged articles for analysis
"""

import json
import os
import re
import sys
from collections import defaultdict

import psycopg2

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
EVENT_ID = 5  # epstein files

# ── comprehensive intellectual entities ───────────────────────────
# source: DOJ files, Inside Higher Ed, Nature, CNN, Boston Globe, Harvard Crimson
INTELLECTUALS = {
    # ── MIT ──
    "Joi Ito": {
        "type": "tech_academic",
        "institution": "MIT Media Lab",
        "role": "former director, resigned 2019 over Epstein ties, resigned again March 2026",
        "money": "$850K to Media Lab, $1.7M to Ito personally",
        "doc_mentions": 40,
        "aliases": ["Joichi Ito"],
    },
    "Marvin Minsky": {
        "type": "scientist",
        "institution": "MIT",
        "role": "AI pioneer, allegedly directed to have sex with Epstein victim (Virginia Giuffre deposition)",
        "money": "unknown",
        "doc_mentions": 25,
        "aliases": [],
    },
    "Seth Lloyd": {
        "type": "scientist",
        "institution": "MIT",
        "role": "quantum computing professor, received $225K from Epstein",
        "money": "$225,000",
        "doc_mentions": 10,
        "aliases": [],
    },

    # ── Harvard ──
    "Martin Nowak": {
        "type": "scientist",
        "institution": "Harvard",
        "role": "math/biology professor, placed on paid leave Feb 2026, ran Epstein-funded program",
        "money": "multi-million (Program for Evolutionary Dynamics)",
        "doc_mentions": 20,
        "aliases": [],
    },
    "Lawrence Summers": {
        "type": "academic_leader",
        "institution": "Harvard",
        "role": "former Harvard president, former Treasury Secretary, resigned positions 2026",
        "money": "Epstein donated after Summers became president",
        "doc_mentions": 30,
        "aliases": ["Larry Summers"],
    },
    "George Church": {
        "type": "scientist",
        "institution": "Harvard/MIT",
        "role": "genomics pioneer, met Epstein multiple times, discussed genetics projects",
        "money": "research funding",
        "doc_mentions": 15,
        "aliases": [],
    },
    "Steven Pinker": {
        "type": "scientist",
        "institution": "Harvard",
        "role": "cognitive psychologist, appeared in Epstein flight logs, provided legal opinion",
        "money": "none documented",
        "doc_mentions": 20,
        "aliases": ["Stephen Pinker"],
    },
    "Lisa Randall": {
        "type": "scientist",
        "institution": "Harvard",
        "role": "theoretical physicist, correspondence with Epstein in files",
        "money": "unknown",
        "doc_mentions": 8,
        "aliases": [],
    },
    "Andrew Strominger": {
        "type": "scientist",
        "institution": "Harvard",
        "role": "string theorist, correspondence in files",
        "money": "unknown",
        "doc_mentions": 5,
        "aliases": [],
    },
    "Elisa New": {
        "type": "academic",
        "institution": "Harvard",
        "role": "English professor emerita, partner of Lawrence Summers, ties in files",
        "money": "unknown",
        "doc_mentions": 5,
        "aliases": [],
    },

    # ── Yale ──
    "David Gelernter": {
        "type": "scientist",
        "institution": "Yale",
        "role": "computer science professor, suspended from teaching 2026",
        "money": "unknown",
        "doc_mentions": 10,
        "aliases": [],
    },
    "Nicholas Christakis": {
        "type": "scientist",
        "institution": "Yale",
        "role": "sociologist/physician, met Epstein 2013, corresponded 2013-2016",
        "money": "unknown",
        "doc_mentions": 8,
        "aliases": [],
    },

    # ── Columbia ──
    "Richard Axel": {
        "type": "scientist",
        "institution": "Columbia",
        "role": "Nobel Prize molecular biologist, stepped down as co-director of Zuckerman Institute",
        "money": "unknown",
        "doc_mentions": 10,
        "aliases": [],
    },

    # ── other universities ──
    "Leon Botstein": {
        "type": "academic_leader",
        "institution": "Bard College",
        "role": "president, received $150K from Epstein for college",
        "money": "$150,000",
        "doc_mentions": 8,
        "aliases": [],
    },

    # ── spiritual / wellness ──
    "Deepak Chopra": {
        "type": "spiritual_guru",
        "institution": "UCSD / Chopra Foundation",
        "role": "wellness guru, 3500+ mentions in files, emails about 'cute girls', $50K from Epstein foundation",
        "money": "$50,000 from Gratitude America (Epstein foundation)",
        "doc_mentions": 100,  # 3500 mentions in raw files
        "aliases": [],
    },

    # ── doctors / medical ──
    "Peter Attia": {
        "type": "doctor",
        "institution": "longevity medicine",
        "role": "longevity doctor, Epstein associate, relationship exposed in files",
        "money": "unknown",
        "doc_mentions": 15,
        "aliases": [],
    },
    "Dean Ornish": {
        "type": "doctor",
        "institution": "UCSF",
        "role": "preventive medicine pioneer, Epstein associate",
        "money": "unknown",
        "doc_mentions": 10,
        "aliases": [],
    },

    # ── other intellectuals ──
    "Noam Chomsky": {
        "type": "intellectual",
        "institution": "MIT/Arizona",
        "role": "linguist, met Epstein for dinner, discussed finances, post-conviction meetings",
        "money": "Epstein moved $270K through Chomsky's account for tax purposes",
        "doc_mentions": 15,
        "aliases": [],
    },
    "Stephen Hawking": {
        "type": "scientist",
        "institution": "Cambridge",
        "role": "physicist, attended Epstein's 2006 conference in USVI, photographed on Epstein's island",
        "money": "conference sponsorship",
        "doc_mentions": 10,
        "aliases": [],
    },
    "Murray Gell-Mann": {
        "type": "scientist",
        "institution": "Caltech/Santa Fe Institute",
        "role": "Nobel physicist, attended Epstein dinners",
        "money": "Santa Fe Institute donations",
        "doc_mentions": 5,
        "aliases": [],
    },
    "Oliver Sacks": {
        "type": "scientist",
        "institution": "Columbia/NYU",
        "role": "neurologist/author, attended Epstein dinners",
        "money": "unknown",
        "doc_mentions": 3,
        "aliases": [],
    },
    "Danny Hillis": {
        "type": "tech_academic",
        "institution": "MIT/Applied Minds",
        "role": "computer scientist, long-time Epstein associate",
        "money": "business relationships",
        "doc_mentions": 15,
        "aliases": ["W. Daniel Hillis"],
    },
    "Nathan Myhrvold": {
        "type": "tech_academic",
        "institution": "Microsoft/Intellectual Ventures",
        "role": "former Microsoft CTO, attended Epstein events",
        "money": "unknown",
        "doc_mentions": 8,
        "aliases": [],
    },
}

# search terms for finding articles about intellectual enablers
SEARCH_TERMS = [
    # names (will also search aliases)
    *[name.lower() for name in INTELLECTUALS.keys()],
    *[alias.lower() for intel in INTELLECTUALS.values() for alias in intel.get("aliases", [])],
    # institutions
    "mit media lab", "harvard epstein", "yale epstein", "columbia epstein",
    "bard college epstein",
    # generic terms
    "epstein academic", "epstein scientist", "epstein professor",
    "epstein university", "epstein intellectual", "epstein research",
    "epstein donation university", "epstein guru", "epstein wellness",
    "epstein doctor",
]


def get_conn():
    return psycopg2.connect(DB_URL)


def build_entity_db():
    """insert all intellectual entities into epstein_entities table."""
    print(f"\n{'='*60}")
    print(f"BUILDING INTELLECTUAL ENTITIES DATABASE")
    print(f"{'='*60}")

    conn = get_conn()
    cur = conn.cursor()
    inserted = 0

    for name, info in INTELLECTUALS.items():
        try:
            cur.execute("""
                INSERT INTO epstein_entities (name, entity_type, doc_mentions, source, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (name, source) DO UPDATE SET
                    doc_mentions = EXCLUDED.doc_mentions,
                    notes = EXCLUDED.notes,
                    entity_type = EXCLUDED.entity_type
            """, (
                name,
                info["type"],
                info["doc_mentions"],
                "intellectual_enablers",
                json.dumps({
                    "institution": info["institution"],
                    "role": info["role"],
                    "money": info["money"],
                    "aliases": info.get("aliases", []),
                }),
            ))
            inserted += 1
        except Exception as e:
            conn.rollback()
            print(f"  error: {name}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"  inserted/updated {inserted} intellectual entities")


def tag_articles():
    """scan all epstein articles for intellectual mentions, tag in DB."""
    print(f"\n{'='*60}")
    print(f"SCANNING ARTICLES FOR INTELLECTUAL MENTIONS")
    print(f"{'='*60}")

    conn = get_conn()
    cur = conn.cursor()

    # get all articles with text
    cur.execute("""
        SELECT id, title, COALESCE(translated_text, raw_text, '') as text
        FROM articles
        WHERE event_id = %s AND (raw_text IS NOT NULL OR translated_text IS NOT NULL)
    """, (EVENT_ID,))
    articles = cur.fetchall()
    print(f"  scanning {len(articles)} articles...")

    # build name lookup (lowercase -> canonical name)
    name_lookup = {}
    for name, info in INTELLECTUALS.items():
        name_lookup[name.lower()] = name
        for alias in info.get("aliases", []):
            name_lookup[alias.lower()] = name

    # also match last names for common names
    for name in INTELLECTUALS.keys():
        parts = name.split()
        if len(parts) >= 2:
            last = parts[-1].lower()
            # only if last name is distinctive enough (>5 chars)
            if len(last) > 5 and last not in ["church"]:  # skip ambiguous names
                name_lookup[last] = name

    tagged_count = 0
    entity_article_counts = defaultdict(int)
    articles_with_intellectuals = set()

    for article_id, title, text in articles:
        full_text = f"{title} {text}".lower()
        mentions = set()

        for search_name, canonical in name_lookup.items():
            if search_name in full_text:
                mentions.add(canonical)

        # also check generic terms
        has_academic_angle = any(term in full_text for term in [
            "academic", "professor", "university", "scientist", "research",
            "mit media lab", "harvard", "yale", "stanford", "columbia",
            "guru", "wellness", "chopra", "spiritual",
        ])

        if mentions or has_academic_angle:
            articles_with_intellectuals.add(article_id)

            for entity_name in mentions:
                entity_article_counts[entity_name] += 1
                try:
                    cur.execute("""
                        INSERT INTO epstein_media_mentions (entity_name, article_id, mention_count)
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (entity_name, article_id, 1))
                    tagged_count += 1
                except Exception:
                    conn.rollback()

        if (article_id % 500 == 0):
            conn.commit()

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n  RESULTS:")
    print(f"  articles mentioning intellectuals: {len(articles_with_intellectuals)} / {len(articles)}")
    print(f"  entity-article tags created: {tagged_count}")
    print(f"\n  ENTITY MEDIA COVERAGE:")
    for name, count in sorted(entity_article_counts.items(), key=lambda x: -x[1]):
        info = INTELLECTUALS.get(name, {})
        doc_mentions = info.get("doc_mentions", 0)
        ratio = count / max(doc_mentions, 1)
        print(f"    {name:25s}  media={count:4d}  docs={doc_mentions:4d}  ratio={ratio:.1f}x")

    return len(articles_with_intellectuals), tagged_count


def show_status():
    """show intellectual sub-corpus stats."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT entity_name, COUNT(DISTINCT article_id) as media_mentions
        FROM epstein_media_mentions
        GROUP BY entity_name
        ORDER BY media_mentions DESC
    """)
    media = cur.fetchall()

    cur.execute("""
        SELECT name, doc_mentions FROM epstein_entities
        WHERE source = 'intellectual_enablers'
        ORDER BY doc_mentions DESC
    """)
    docs = cur.fetchall()

    print(f"\n{'='*60}")
    print(f"INTELLECTUAL ENABLERS — SUPPRESSION INDEX")
    print(f"{'='*60}")
    print(f"{'Name':25s} {'Type':15s} {'Docs':>5s} {'Media':>6s} {'Ratio':>7s}")
    print(f"{'-'*60}")

    # merge docs and media
    media_dict = {name: count for name, count in media}
    for name, doc_count in docs:
        media_count = media_dict.get(name, 0)
        info = INTELLECTUALS.get(name, {})
        etype = info.get("type", "?")
        if doc_count > 0:
            ratio = f"{media_count/doc_count:.1f}x"
        else:
            ratio = "n/a"
        print(f"  {name:25s} {etype:15s} {doc_count:5d} {media_count:6d} {ratio:>7s}")

    # total articles in sub-corpus
    cur.execute("SELECT COUNT(DISTINCT article_id) FROM epstein_media_mentions")
    total = cur.fetchone()[0]
    print(f"\n  total articles in intellectual sub-corpus: {total}")

    cur.close()
    conn.close()


def export_subcorpus():
    """export intellectual sub-corpus article IDs for pass 1 analysis."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT a.id, a.title, a.original_language,
               array_agg(DISTINCT m.entity_name) as mentioned_entities
        FROM epstein_media_mentions m
        JOIN articles a ON m.article_id = a.id
        GROUP BY a.id, a.title, a.original_language
        ORDER BY array_length(array_agg(DISTINCT m.entity_name), 1) DESC
    """)
    rows = cur.fetchall()

    outfile = "analysis/epstein_intellectual_subcorpus.json"
    os.makedirs("analysis", exist_ok=True)

    export = []
    for aid, title, lang, entities in rows:
        export.append({
            "article_id": aid,
            "title": title,
            "language": lang,
            "mentioned_entities": entities,
        })

    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print(f"\n  exported {len(export)} articles to {outfile}")
    cur.close()
    conn.close()
    return export


def main():
    if len(sys.argv) < 2:
        print("usage: python3 scripts/epstein_intellectuals.py <build|status|export>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "build":
        build_entity_db()
        tag_articles()
        show_status()
    elif cmd == "status":
        show_status()
    elif cmd == "export":
        export_subcorpus()
    else:
        print(f"unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
