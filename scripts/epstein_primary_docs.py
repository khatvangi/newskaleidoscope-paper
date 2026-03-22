#!/usr/bin/env python3
"""
epstein_primary_docs.py — fetch primary document references for intellectual entities.

queries community APIs to get actual DOJ document context for each intellectual.
builds a per-entity dossier from primary sources.

usage:
  python3 scripts/epstein_primary_docs.py fetch     # download from APIs
  python3 scripts/epstein_primary_docs.py status    # show what we have
  python3 scripts/epstein_primary_docs.py compare   # primary docs vs media coverage
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

import psycopg2

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
OUTPUT_DIR = "sources/epstein_primary"
INVESTIGATION_API = "https://www.epsteininvestigation.org/api/v1"

# intellectuals to look up in primary docs
SEARCH_NAMES = [
    "Joi Ito", "Joichi Ito",
    "Lawrence Summers", "Larry Summers",
    "Martin Nowak",
    "George Church",
    "Steven Pinker", "Stephen Pinker",
    "Marvin Minsky",
    "Noam Chomsky",
    "Deepak Chopra",
    "Danny Hillis", "W. Daniel Hillis",
    "Seth Lloyd",
    "David Gelernter",
    "Nicholas Christakis",
    "Richard Axel",
    "Nathan Myhrvold",
    "Lisa Randall",
    "Leon Botstein",
    "Peter Attia",
    "Dean Ornish",
    "Stephen Hawking",
    "Murray Gell-Mann",
    "Oliver Sacks",
    "Andrew Strominger",
    "Elisa New",
    # institutions
    "MIT Media Lab",
    "Harvard University",
    "Yale University",
    "Columbia University",
    "Bard College",
]


def get_conn():
    return psycopg2.connect(DB_URL)


def search_entity_api(name):
    """search the investigation API for a specific name."""
    encoded = urllib.parse.quote(name)
    url = f"{INVESTIGATION_API}/search?q={encoded}&limit=50"

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "NewsKaleidoscope/0.1",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except Exception as e:
        # try alternate endpoint
        try:
            url2 = f"{INVESTIGATION_API}/entities?search={encoded}"
            req = urllib.request.Request(url2, headers={
                "User-Agent": "NewsKaleidoscope/0.1",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass
    return None


def search_documents_api(name):
    """search for documents mentioning a name."""
    encoded = urllib.parse.quote(name)

    endpoints = [
        f"{INVESTIGATION_API}/documents?search={encoded}&limit=20",
        f"{INVESTIGATION_API}/documents?q={encoded}&limit=20",
    ]

    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "NewsKaleidoscope/0.1",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data:
                return data
        except Exception:
            continue
    return None


def fetch_all():
    """fetch primary doc references for all intellectual entities."""
    print(f"\n{'='*60}")
    print(f"FETCHING PRIMARY DOCUMENT REFERENCES")
    print(f"{'='*60}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_results = {}

    for name in SEARCH_NAMES:
        print(f"\n  searching: {name}...")

        # search entities
        entity_data = search_entity_api(name)
        if entity_data:
            items = entity_data if isinstance(entity_data, list) else entity_data.get("data", entity_data.get("results", []))
            if isinstance(items, list) and items:
                print(f"    entity results: {len(items)}")
            else:
                items = []
        else:
            items = []

        # search documents
        doc_data = search_documents_api(name)
        docs = []
        if doc_data:
            docs = doc_data if isinstance(doc_data, list) else doc_data.get("data", doc_data.get("results", []))
            if isinstance(docs, list) and docs:
                print(f"    document results: {len(docs)}")
            else:
                docs = []

        all_results[name] = {
            "entity_matches": items if isinstance(items, list) else [],
            "document_matches": docs if isinstance(docs, list) else [],
            "raw_entity": entity_data,
            "raw_docs": doc_data,
        }

        time.sleep(0.5)

    # save
    outfile = os.path.join(OUTPUT_DIR, "intellectual_primary_docs.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\n  saved to {outfile}")

    # insert into DB
    conn = get_conn()
    cur = conn.cursor()
    updated = 0

    for name, data in all_results.items():
        doc_count = len(data.get("document_matches", []))
        entity_matches = data.get("entity_matches", [])

        # update doc_mentions if we got better data
        if doc_count > 0 or entity_matches:
            best_count = doc_count
            for em in entity_matches:
                if isinstance(em, dict):
                    dc = em.get("document_count", 0)
                    if dc > best_count:
                        best_count = dc

            if best_count > 0:
                try:
                    cur.execute("""
                        UPDATE epstein_entities
                        SET doc_mentions = GREATEST(doc_mentions, %s),
                            notes = COALESCE(notes, '') || %s
                        WHERE name = %s AND source = 'intellectual_enablers'
                    """, (best_count, f" | API doc_count: {best_count}", name))
                    if cur.rowcount > 0:
                        updated += 1
                except Exception:
                    conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    print(f"  updated {updated} entity doc counts in DB")

    return all_results


def show_status():
    """show what primary doc data we have per intellectual."""
    outfile = os.path.join(OUTPUT_DIR, "intellectual_primary_docs.json")
    if not os.path.exists(outfile):
        print("  no primary doc data yet. run: python3 scripts/epstein_primary_docs.py fetch")
        return

    with open(outfile) as f:
        data = json.load(f)

    print(f"\n{'='*70}")
    print(f"PRIMARY DOCUMENT REFERENCES — INTELLECTUAL ENTITIES")
    print(f"{'='*70}")
    print(f"{'Name':25s} {'Entity Matches':>15s} {'Doc Matches':>12s}")
    print(f"{'-'*55}")

    for name, info in sorted(data.items(), key=lambda x: -(len(x[1].get("document_matches", [])) + len(x[1].get("entity_matches", [])))):
        entities = len(info.get("entity_matches", []))
        docs = len(info.get("document_matches", []))
        if entities > 0 or docs > 0:
            print(f"  {name:25s} {entities:15d} {docs:12d}")


def compare():
    """compare primary doc presence vs media coverage for each intellectual."""
    conn = get_conn()
    cur = conn.cursor()

    # get primary doc mentions
    cur.execute("""
        SELECT name, doc_mentions, entity_type, notes
        FROM epstein_entities
        WHERE source = 'intellectual_enablers'
        ORDER BY doc_mentions DESC
    """)
    primary = {row[0]: {"docs": row[1], "type": row[2], "notes": row[3]} for row in cur.fetchall()}

    # get media mentions (from epstein_media_mentions for event_id=5)
    cur.execute("""
        SELECT entity_name, COUNT(DISTINCT article_id) as media_count
        FROM epstein_media_mentions
        GROUP BY entity_name
    """)
    media = {row[0]: row[1] for row in cur.fetchall()}

    # get entity context extractions (deeper analysis)
    cur.execute("""
        SELECT entity_name, involvement_level, COUNT(*) as ctx_count
        FROM epstein_entity_contexts
        GROUP BY entity_name, involvement_level
    """)
    contexts = {}
    for name, level, count in cur.fetchall():
        if name not in contexts:
            contexts[name] = {}
        contexts[name][level] = count

    cur.close()
    conn.close()

    print(f"\n{'='*90}")
    print(f"SUPPRESSION INDEX — PRIMARY DOCS vs MEDIA COVERAGE vs DEEP CONTEXT")
    print(f"{'='*90}")
    print(f"{'Name':25s} {'Type':15s} {'Docs':>5s} {'Media':>6s} {'Ratio':>7s} {'Context':>8s} {'Top Level':>20s}")
    print(f"{'-'*90}")

    for name in sorted(primary.keys(), key=lambda n: -primary[n]["docs"]):
        info = primary[name]
        media_count = media.get(name, 0)
        ctx = contexts.get(name, {})
        ctx_total = sum(ctx.values())
        top_level = max(ctx.keys(), key=lambda l: ctx[l]) if ctx else "—"

        ratio = f"{media_count/info['docs']:.1f}x" if info["docs"] > 0 else "n/a"

        # flag suppressed
        flag = ""
        if info["docs"] >= 10 and media_count == 0:
            flag = " ⚠ SUPPRESSED"
        elif info["docs"] >= 10 and media_count / info["docs"] < 0.2:
            flag = " ⚠ UNDER-COVERED"

        print(f"  {name:25s} {info['type']:15s} {info['docs']:5d} {media_count:6d} {ratio:>7s} {ctx_total:8d} {top_level:>20s}{flag}")

    print(f"\n  Legend: Docs = primary document mentions, Media = news articles mentioning name")
    print(f"  Ratio = media/docs (higher = amplified, lower = suppressed)")
    print(f"  Context = entity-level involvement extractions")


def main():
    if len(sys.argv) < 2:
        print("usage: python3 scripts/epstein_primary_docs.py <fetch|status|compare>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "fetch":
        fetch_all()
    elif cmd == "status":
        show_status()
    elif cmd == "compare":
        compare()
    else:
        print(f"unknown: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
