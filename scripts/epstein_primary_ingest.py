#!/usr/bin/env python3
"""
epstein_primary_ingest.py — download structured entity databases from community sources.

downloads:
  1. Epstein Research Data (GitHub CSVs: names, phones, emails, orgs)
  2. Epstein Investigation API (entities + document mention counts)
  3. Creates PostgreSQL tables for cross-referencing with media coverage

usage:
  python3 scripts/epstein_primary_ingest.py
"""

import csv
import io
import json
import os
import sys
import time
import urllib.request
import urllib.error

import psycopg2

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
OUTPUT_DIR = "sources/epstein_primary"
GITHUB_BASE = "https://raw.githubusercontent.com/rhowardstone/Epstein-research-data/main"
INVESTIGATION_API = "https://www.epsteininvestigation.org/api/v1"


def get_conn():
    return psycopg2.connect(DB_URL)


def create_tables():
    """create tables for primary document entities."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS epstein_entities (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            entity_type TEXT,
            doc_mentions INTEGER DEFAULT 0,
            source TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(name, source)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS epstein_connections (
            id SERIAL PRIMARY KEY,
            entity_a TEXT NOT NULL,
            entity_b TEXT NOT NULL,
            connection_type TEXT,
            doc_count INTEGER DEFAULT 0,
            source TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS epstein_media_mentions (
            id SERIAL PRIMARY KEY,
            entity_name TEXT NOT NULL,
            article_id INTEGER REFERENCES articles(id),
            mention_count INTEGER DEFAULT 1,
            context TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_epstein_entities_name ON epstein_entities(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_epstein_connections_a ON epstein_connections(entity_a)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_epstein_connections_b ON epstein_connections(entity_b)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_epstein_media_entity ON epstein_media_mentions(entity_name)")

    conn.commit()
    cur.close()
    conn.close()
    print("  tables created/verified")


def download_file(url, local_path):
    """download a file, skip if exists."""
    if os.path.exists(local_path):
        print(f"  cached: {local_path}")
        return True
    try:
        print(f"  downloading: {url[:80]}...")
        req = urllib.request.Request(url, headers={"User-Agent": "NewsKaleidoscope/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        print(f"  saved: {local_path} ({len(data):,} bytes)")
        return True
    except Exception as e:
        print(f"  download failed: {e}")
        return False


# ── phase 1: GitHub CSVs ────────────────────────────────────────
def ingest_github_csvs():
    """download and parse Epstein Research Data from GitHub."""
    print(f"\n{'='*60}")
    print(f"PHASE 1: GitHub Epstein Research Data")
    print(f"{'='*60}")

    # key files from the repo
    files = {
        "names.csv": f"{GITHUB_BASE}/names.csv",
        "phones.csv": f"{GITHUB_BASE}/phones.csv",
        "emails.csv": f"{GITHUB_BASE}/emails.csv",
        "organizations.csv": f"{GITHUB_BASE}/organizations.csv",
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()
    total_entities = 0

    for filename, url in files.items():
        local_path = os.path.join(OUTPUT_DIR, filename)
        if not download_file(url, local_path):
            # try alternate paths
            alt_url = url.replace("/main/", "/master/")
            if not download_file(alt_url, local_path):
                continue

        # parse CSV and insert entities
        try:
            with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # detect delimiter
            if "\t" in content[:500]:
                delimiter = "\t"
            else:
                delimiter = ","

            reader = csv.reader(io.StringIO(content), delimiter=delimiter)
            header = next(reader, None)
            if not header:
                continue

            entity_type = filename.replace(".csv", "")
            rows_inserted = 0

            for row in reader:
                if not row or not row[0].strip():
                    continue

                name = row[0].strip()
                # doc mentions column if available
                doc_mentions = 0
                if len(row) > 1:
                    try:
                        doc_mentions = int(row[1])
                    except (ValueError, IndexError):
                        doc_mentions = 1

                try:
                    cur.execute("""
                        INSERT INTO epstein_entities (name, entity_type, doc_mentions, source)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (name, source) DO UPDATE SET doc_mentions = GREATEST(epstein_entities.doc_mentions, EXCLUDED.doc_mentions)
                    """, (name, entity_type, doc_mentions, "github_research_data"))
                    rows_inserted += 1
                except Exception as e:
                    conn.rollback()
                    continue

            conn.commit()
            total_entities += rows_inserted
            print(f"  {filename}: {rows_inserted} entities inserted")

        except Exception as e:
            print(f"  error parsing {filename}: {e}")

    cur.close()
    conn.close()
    print(f"\n  GitHub total: {total_entities} entities")
    return total_entities


# ── phase 2: Epstein Investigation API ──────────────────────────
def ingest_investigation_api():
    """query Epstein Investigation API for entities and connections."""
    print(f"\n{'='*60}")
    print(f"PHASE 2: Epstein Investigation API")
    print(f"{'='*60}")

    conn = get_conn()
    cur = conn.cursor()
    total = 0

    # try the API
    endpoints = [
        "/entities",
        "/persons",
        "/organizations",
        "/flights",
    ]

    for endpoint in endpoints:
        url = f"{INVESTIGATION_API}{endpoint}"
        print(f"\n  trying: {url}")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "NewsKaleidoscope/0.1",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # save raw response
            local_path = os.path.join(OUTPUT_DIR, f"api_{endpoint.strip('/').replace('/', '_')}.json")
            with open(local_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # parse entities
            items = data if isinstance(data, list) else data.get("data", data.get("results", data.get("items", [])))
            if not isinstance(items, list):
                print(f"    unexpected format, saved raw to {local_path}")
                continue

            inserted = 0
            for item in items:
                name = item.get("name", item.get("full_name", item.get("entity", "")))
                if not name:
                    continue
                entity_type = item.get("type", item.get("entity_type", endpoint.strip("/")))
                doc_mentions = item.get("mention_count", item.get("doc_count", item.get("count", 1)))

                try:
                    cur.execute("""
                        INSERT INTO epstein_entities (name, entity_type, doc_mentions, source)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (name, source) DO UPDATE SET doc_mentions = GREATEST(epstein_entities.doc_mentions, EXCLUDED.doc_mentions)
                    """, (name, entity_type, doc_mentions, "investigation_api"))
                    inserted += 1
                except Exception:
                    conn.rollback()

            conn.commit()
            total += inserted
            print(f"    {inserted} entities from {endpoint}")
            time.sleep(1)

        except urllib.error.HTTPError as e:
            print(f"    HTTP {e.code}: {e.reason}")
        except Exception as e:
            print(f"    error: {e}")

    cur.close()
    conn.close()
    print(f"\n  API total: {total} entities")
    return total


# ── phase 3: CSV bulk downloads ─────────────────────────────────
def ingest_csv_downloads():
    """try to download CSV bulk exports from investigation sites."""
    print(f"\n{'='*60}")
    print(f"PHASE 3: CSV Bulk Downloads")
    print(f"{'='*60}")

    # try known CSV download URLs
    csv_urls = [
        ("investigation_entities.csv", "https://www.epsteininvestigation.org/download/entities.csv"),
        ("investigation_flights.csv", "https://www.epsteininvestigation.org/download/flights.csv"),
        ("investigation_documents.csv", "https://www.epsteininvestigation.org/download/documents.csv"),
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    downloaded = 0

    for filename, url in csv_urls:
        local_path = os.path.join(OUTPUT_DIR, filename)
        if download_file(url, local_path):
            downloaded += 1
        time.sleep(1)

    print(f"\n  downloaded: {downloaded}/{len(csv_urls)} files")
    return downloaded


# ── phase 4: known names list ───────────────────────────────────
def ingest_known_names():
    """insert the AG Bondi 305-name list and other known associates."""
    print(f"\n{'='*60}")
    print(f"PHASE 4: Known Names Database")
    print(f"{'='*60}")

    # high-profile names from research (with categories)
    known_names = {
        # political
        "Donald Trump": ("political", 50),
        "Bill Clinton": ("political", 80),
        "Hillary Clinton": ("political", 20),
        "Ehud Barak": ("political", 60),
        "Peter Mandelson": ("political", 40),
        "Bill Richardson": ("political", 30),
        "George Mitchell": ("political", 20),
        # royalty
        "Prince Andrew": ("royalty", 100),
        "Ghislaine Maxwell": ("associate", 200),
        # finance
        "Leslie Wexner": ("finance", 90),
        "Leon Black": ("finance", 60),
        "Jes Staley": ("finance", 40),
        "Glenn Dubin": ("finance", 30),
        "Thomas Pritzker": ("finance", 20),
        # tech
        "Bill Gates": ("tech", 50),
        "Elon Musk": ("tech", 30),
        "Sergey Brin": ("tech", 20),
        "Peter Thiel": ("tech", 15),
        "Reid Hoffman": ("tech", 20),
        # academia
        "Joi Ito": ("academia", 40),
        "Lawrence Summers": ("academia", 30),
        "Noam Chomsky": ("academia", 15),
        "Steven Pinker": ("academia", 20),
        "Marvin Minsky": ("academia", 25),
        "George Church": ("academia", 15),
        "Martin Nowak": ("academia", 20),
        "Stephen Hawking": ("academia", 10),
        # legal
        "Alan Dershowitz": ("legal", 70),
        "Alexander Acosta": ("legal", 40),
        "Ken Starr": ("legal", 20),
        # modeling/entertainment
        "Jean-Luc Brunel": ("modeling", 50),
        "Naomi Campbell": ("entertainment", 15),
        "Woody Allen": ("entertainment", 10),
        # associates/staff
        "Sarah Kellen": ("associate", 60),
        "Nadia Marcinkova": ("associate", 40),
        "Adriana Ross": ("associate", 30),
        "Lesley Groff": ("associate", 25),
        # institutions (as entities)
        "MIT Media Lab": ("institution", 40),
        "Harvard University": ("institution", 35),
        "JPMorgan Chase": ("institution", 45),
        "Deutsche Bank": ("institution", 25),
        "Victoria's Secret": ("institution", 30),
    }

    conn = get_conn()
    cur = conn.cursor()
    inserted = 0

    for name, (etype, est_mentions) in known_names.items():
        try:
            cur.execute("""
                INSERT INTO epstein_entities (name, entity_type, doc_mentions, source, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (name, source) DO UPDATE SET
                    doc_mentions = GREATEST(epstein_entities.doc_mentions, EXCLUDED.doc_mentions),
                    entity_type = EXCLUDED.entity_type
            """, (name, etype, est_mentions, "known_associates", f"category: {etype}"))
            inserted += 1
        except Exception:
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    print(f"  inserted {inserted} known names/institutions")
    return inserted


def show_summary():
    """show entity database summary."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT source, COUNT(*), SUM(doc_mentions) FROM epstein_entities GROUP BY source ORDER BY count DESC")
    rows = cur.fetchall()

    print(f"\n{'='*60}")
    print(f"EPSTEIN PRIMARY DOCUMENT DATABASE SUMMARY")
    print(f"{'='*60}")
    for source, count, total_mentions in rows:
        print(f"  {source}: {count} entities ({total_mentions} total doc mentions)")

    cur.execute("SELECT COUNT(DISTINCT name) FROM epstein_entities")
    unique = cur.fetchone()[0]
    print(f"\n  unique entity names: {unique}")

    cur.execute("SELECT entity_type, COUNT(*) FROM epstein_entities WHERE source = 'known_associates' GROUP BY entity_type ORDER BY count DESC")
    print(f"\n  known associates by type:")
    for etype, count in cur.fetchall():
        print(f"    {etype}: {count}")

    cur.close()
    conn.close()


def main():
    print(f"\n{'='*60}")
    print(f"EPSTEIN PRIMARY DOCUMENT INGESTION")
    print(f"{'='*60}")

    create_tables()
    ingest_known_names()
    ingest_github_csvs()
    ingest_investigation_api()
    ingest_csv_downloads()
    show_summary()


if __name__ == "__main__":
    main()
