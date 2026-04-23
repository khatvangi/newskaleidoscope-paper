#!/usr/bin/env python3
"""
parse nexisuni PDF exports, deduplicate against DB, insert into event_id=6.
each PDF contains multiple articles with standard LexisNexis structure:
  title → publication → date → copyright → Length → Body → ... → End of Document
"""

import subprocess, re, hashlib, sys, os, json
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

# -- db setup --
import psycopg2

DB_DSN = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
EVENT_ID = 6
PDF_DIR = Path("/storage/news/epstein-intellectual/nexisuni_pdfs")

# -- map zip names to search subjects for relevance filtering --
SUBJECT_MAP = {
    "brockman": ["brockman", "edge foundation", "edge.org"],
    "church": ["george church", "church"],
    "david": ["gelernter", "david gelernter"],
    "f3-vetting": ["donor vetting", "gift acceptance", "due diligence", "fundraising oversight", "donor screening"],
    "joi": ["joi ito", "media lab", "joichi ito"],
    "krauss": ["krauss", "lawrence krauss", "origins project"],
    "leon": ["botstein", "leon botstein", "bard college"],
    "martin-nowak": ["nowak", "martin nowak", "evolutionary dynamics"],
    "marvin": ["minsky", "marvin minsky"],
    "pinker": ["pinker", "steven pinker"],
    "seth": ["seth lloyd", "lloyd"],
}


def pdf_to_text(pdf_path):
    """extract text from pdf using pdftotext."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True
    )
    return result.stdout


def parse_articles(text):
    """split nexisuni text into individual articles."""
    articles = []
    # split on "End of Document" which marks article boundaries
    chunks = re.split(r'End of Document', text)

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or len(chunk) < 200:
            continue

        # find Body marker
        body_match = re.search(r'\nBody\n', chunk)
        if not body_match:
            continue

        header = chunk[:body_match.start()]
        body = chunk[body_match.end():]

        # clean body: remove Load-Date line and everything after
        body = re.split(r'\nLoad-Date:', body)[0].strip()
        # remove LexisNexis footer lines
        body = re.sub(r'\| About LexisNexis.*?Kiran Boggvarapu', '', body, flags=re.DOTALL)
        body = body.strip()

        if len(body) < 100:
            continue

        # parse header
        title = ""
        publication = ""
        date_str = ""

        # title is usually the first substantial line after page header
        header_lines = [l.strip() for l in header.split('\n') if l.strip()]

        # find title: skip "Page X of Y", copyright lines, search metadata
        for i, line in enumerate(header_lines):
            # skip page numbers, copyright, LexisNexis branding, metadata
            if re.match(r'^Page \d+ of \d+', line):
                continue
            if 'LexisNexis' in line or 'Copyright' in line:
                continue
            if line.startswith('Client/') or line.startswith('Search') or line.startswith('Content'):
                continue
            if re.match(r'^\d+\.', line):  # TOC entries like "1. Title"
                continue
            if line.startswith('Length:') or line.startswith('Narrowed by'):
                continue
            if 'Kiran Boggvarapu' in line:
                continue
            if line in ('news', ':'):
                continue
            # first substantial line is likely the title
            if len(line) > 10 and not title:
                title = line
                continue
            # next substantial line is publication
            if title and not publication and len(line) > 3:
                # check if it looks like a publication name (not a date)
                if not re.match(r'^(January|February|March|April|May|June|July|August|September|October|November|December)', line):
                    publication = line
                    continue
                else:
                    date_str = line
                    continue
            # date line
            if title and publication and not date_str and len(line) > 5:
                date_str = line
                break

        # parse date
        pub_date = None
        if date_str:
            # try common formats: "February 21, 2026 Saturday", "September 12, 2019"
            date_clean = re.sub(r'\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*', '', date_str).strip()
            for fmt in ['%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%d %B %Y']:
                try:
                    pub_date = datetime.strptime(date_clean, fmt).date()
                    break
                except ValueError:
                    continue

        if title:
            articles.append({
                'title': title[:1000],
                'publication': publication[:200],
                'date': pub_date,
                'text': body,
                'length': len(body.split()),
            })

    return articles


def is_relevant(article, subject_terms):
    """check if article actually discusses the subject + epstein together."""
    text_lower = article['text'].lower()
    title_lower = article['title'].lower()

    # must mention epstein
    if 'epstein' not in text_lower and 'epstein' not in title_lower:
        return False

    # for f3-vetting, any mention of donor/vetting terms is enough
    if subject_terms == SUBJECT_MAP.get("f3-vetting"):
        return any(term in text_lower for term in subject_terms)

    # must mention the subject intellectual
    has_subject = any(term in text_lower or term in title_lower for term in subject_terms)
    return has_subject


def title_similarity(t1, t2):
    """normalized title similarity."""
    t1 = re.sub(r'[^\w\s]', '', t1.lower().strip())
    t2 = re.sub(r'[^\w\s]', '', t2.lower().strip())
    return SequenceMatcher(None, t1, t2).ratio()


def text_hash(text):
    """hash first 500 chars of body for dedup."""
    return hashlib.md5(text[:500].encode()).hexdigest()


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    # get existing titles for dedup
    cur.execute("SELECT id, title FROM articles WHERE event_id = %s", (EVENT_ID,))
    existing = [(row[0], row[1]) for row in cur.fetchall()]
    existing_titles = [t for _, t in existing if t]
    print(f"existing articles in event_id={EVENT_ID}: {len(existing)}")

    # also get existing text hashes
    cur.execute("SELECT md5(left(raw_text, 500)) FROM articles WHERE event_id = %s AND raw_text IS NOT NULL", (EVENT_ID,))
    existing_hashes = set(row[0] for row in cur.fetchall() if row[0])

    # get source_id for nexisuni (create if needed)
    cur.execute("SELECT id FROM sources WHERE name = 'NexisUni'")
    row = cur.fetchone()
    if row:
        source_id = row[0]
    else:
        cur.execute("INSERT INTO sources (name) VALUES ('NexisUni') RETURNING id")
        source_id = cur.fetchone()[0]
        conn.commit()

    total_parsed = 0
    total_relevant = 0
    total_dupes = 0
    total_inserted = 0

    pdfs = sorted(PDF_DIR.glob("*.pdf"))

    for pdf_path in pdfs:
        stem = pdf_path.stem  # e.g. "seth", "brockman"
        subject_terms = SUBJECT_MAP.get(stem, [stem])

        print(f"\n{'='*60}")
        print(f"processing: {pdf_path.name} (subject: {subject_terms})")

        text = pdf_to_text(pdf_path)
        articles = parse_articles(text)
        total_parsed += len(articles)
        print(f"  parsed: {len(articles)} articles")

        # filter for relevance
        relevant = [a for a in articles if is_relevant(a, subject_terms)]
        total_relevant += len(relevant)
        print(f"  relevant: {len(relevant)} (filtered {len(articles) - len(relevant)} noise)")

        dupes = 0
        inserted = 0

        for article in relevant:
            # dedup by title similarity
            is_dupe = False
            for existing_title in existing_titles:
                if title_similarity(article['title'], existing_title) > 0.85:
                    is_dupe = True
                    break

            # also dedup by text hash
            h = text_hash(article['text'])
            if h in existing_hashes:
                is_dupe = True

            if is_dupe:
                dupes += 1
                continue

            # generate a synthetic URL for the article
            url = f"nexisuni://{stem}/{hashlib.md5(article['title'].encode()).hexdigest()[:12]}"

            # detect language (simple heuristic)
            lang = "English"  # default
            non_ascii = sum(1 for c in article['text'][:500] if ord(c) > 127)
            if non_ascii > 50:
                # likely non-English, try to detect
                text_sample = article['text'][:200].lower()
                if any(w in text_sample for w in ['der ', 'die ', 'und ', 'von ']):
                    lang = "German"
                elif any(w in text_sample for w in ['les ', 'des ', 'une ', 'dans ']):
                    lang = "French"
                elif any(w in text_sample for w in ['los ', 'las ', 'del ', 'una ', 'para ']):
                    lang = "Spanish"
                elif any(w in text_sample for w in ['com ', 'para ', 'uma ', 'são ']):
                    lang = "Portuguese"
                elif any(w in text_sample for w in ['che ', 'della ', 'nel ']):
                    lang = "Italian"
                else:
                    lang = "Unknown"

            # insert
            cur.execute("""
                INSERT INTO articles (event_id, source_id, url, title, raw_text, translated_text,
                                     original_language, publication_date, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (url) DO NOTHING
                RETURNING id
            """, (
                EVENT_ID, source_id, url, article['title'],
                article['text'],
                article['text'] if lang == "English" else None,  # english articles get copied to translated
                lang,
                article['date'],
            ))

            result = cur.fetchone()
            if result:
                inserted += 1
                existing_titles.append(article['title'])  # add to dedup list
                existing_hashes.add(h)

        conn.commit()
        total_dupes += dupes
        total_inserted += inserted
        print(f"  dupes: {dupes}, inserted: {inserted}")

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"  total parsed:   {total_parsed}")
    print(f"  total relevant: {total_relevant}")
    print(f"  duplicates:     {total_dupes}")
    print(f"  NEW inserted:   {total_inserted}")
    print(f"{'='*60}")

    # final count
    cur.execute("SELECT COUNT(*) FROM articles WHERE event_id = %s", (EVENT_ID,))
    print(f"  event_id={EVENT_ID} total: {cur.fetchone()[0]}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
