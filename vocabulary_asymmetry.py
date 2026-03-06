#!/usr/bin/env python3
"""
vocabulary_asymmetry.py — session 5: vocabulary framing analysis.

measures sanitizing vs condemnatory vocabulary used in proximity to different actors.
detects the double standard: same action described differently depending on who does it.

uses spaCy NER + token proximity. no LLM calls.
stores results in actor_framing table.

run_id: session_005
"""

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

import spacy
from sqlalchemy import create_engine, text

log = logging.getLogger("vocab")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
RUN_ID = "session_005"

# actor detection — entity names and patterns
ACTOR_GROUPS = {
    "US": [
        "united states", "u.s.", "america", "american", "washington",
        "pentagon", "white house", "trump", "biden", "state department",
        "us military", "us forces", "cia",
    ],
    "Israel": [
        "israel", "israeli", "idf", "netanyahu", "tel aviv",
        "jerusalem", "mossad", "shin bet", "israel defense",
    ],
    "Iran": [
        "iran", "iranian", "tehran", "islamic republic",
        "khamenei", "raisi", "rouhani", "zarif",
    ],
    "IRGC": [
        "irgc", "revolutionary guard", "quds force", "basij",
    ],
    "Hezbollah": [
        "hezbollah", "hizballah", "hizbollah", "nasrallah",
    ],
    "IDF": [
        "idf", "israel defense forces", "israeli military",
        "israeli air force", "israeli army",
    ],
}

SANITIZING_TERMS = [
    "strike", "operation", "targeted", "precision",
    "surgical", "objective", "neutralize", "eliminate",
    "respond", "coalition", "forces", "assets",
    "intervention", "collateral", "defensive",
    "self-defense", "deterrence", "retaliation",
    "preemptive", "preventive", "proportional",
]

CONDEMNATORY_TERMS = [
    "attack", "assault", "aggression", "invasion",
    "regime", "militants", "terrorists", "massacre",
    "indiscriminate", "bombing", "occupation",
    "provocation", "hostile", "threat", "escalation",
    "illegal", "violation", "reckless", "brutal",
    "destabilize", "proxy",
]

PROXIMITY_WINDOW = 15  # tokens


def load_nlp():
    nlp = spacy.load("en_core_web_lg")
    return nlp


def get_articles(conn):
    """fetch all articles for event 2 with source info."""
    rows = conn.execute(text("""
        SELECT a.id, a.title, a.original_language, a.translated_text, a.raw_text,
               s.country_code, s.name as outlet, s.url as outlet_url
        FROM articles a
        LEFT JOIN sources s ON a.source_id = s.id
        WHERE a.event_id = 2
        ORDER BY a.id
    """))
    articles = []
    for r in rows:
        article_text = r.translated_text or r.raw_text or ""
        articles.append({
            'id': r.id, 'title': r.title, 'lang': r.original_language or 'en',
            'cc': r.country_code or '??', 'outlet': r.outlet or '??',
            'outlet_url': r.outlet_url or '',
            'text': article_text,
        })
    return articles


def find_actor_mentions(doc):
    """find all token positions where each actor group is mentioned."""
    mentions = defaultdict(list)  # actor_group -> [token_indices]

    for i, token in enumerate(doc):
        token_lower = token.text.lower()
        # check bigram too
        bigram = ""
        if i + 1 < len(doc):
            bigram = f"{token_lower} {doc[i+1].text.lower()}"
        trigram = ""
        if i + 2 < len(doc):
            trigram = f"{bigram} {doc[i+2].text.lower()}"

        for actor, patterns in ACTOR_GROUPS.items():
            for p in patterns:
                if p == token_lower or p == bigram or p == trigram:
                    mentions[actor].append(i)
                    break

    return mentions


def find_vocabulary_near_actor(doc, actor_positions, window=PROXIMITY_WINDOW):
    """find sanitizing and condemnatory terms near actor mentions."""
    sanitizing_found = []
    condemnatory_found = []

    for pos in actor_positions:
        start = max(0, pos - window)
        end = min(len(doc), pos + window)

        for i in range(start, end):
            token_lower = doc[i].text.lower()
            if token_lower in SANITIZING_TERMS:
                sanitizing_found.append(token_lower)
            elif token_lower in CONDEMNATORY_TERMS:
                condemnatory_found.append(token_lower)

    return sanitizing_found, condemnatory_found


def analyze_article(nlp, article):
    """analyze vocabulary framing for each actor in one article."""
    text = article['text']
    if not text or len(text.strip()) < 50:
        return []

    doc = nlp(text[:100000])
    mentions = find_actor_mentions(doc)

    results = []
    for actor, positions in mentions.items():
        if not positions:
            continue

        sanitizing, condemnatory = find_vocabulary_near_actor(doc, positions)
        framing_score = len(sanitizing) - len(condemnatory)

        results.append({
            'article_id': article['id'],
            'event_id': 2,
            'outlet_domain': article['outlet'],
            'actor': actor,
            'sanitizing_terms': sanitizing,
            'condemnatory_terms': condemnatory,
            'neutral_terms': [],  # future expansion
            'framing_score': framing_score,
            'run_id': RUN_ID,
            'mention_count': len(positions),
        })

    return results


def write_results(conn, all_results):
    """write actor framing results to DB."""
    success = 0
    for r in all_results:
        conn.execute(text("""
            INSERT INTO actor_framing
                (article_id, event_id, outlet_domain, actor,
                 sanitizing_terms, condemnatory_terms, neutral_terms,
                 framing_score, run_id)
            VALUES
                (:aid, :eid, :outlet, :actor,
                 CAST(:san AS jsonb), CAST(:con AS jsonb), CAST(:neu AS jsonb),
                 :score, :rid)
        """), {
            'aid': r['article_id'],
            'eid': r['event_id'],
            'outlet': r['outlet_domain'],
            'actor': r['actor'],
            'san': json.dumps(r['sanitizing_terms']),
            'con': json.dumps(r['condemnatory_terms']),
            'neu': json.dumps(r['neutral_terms']),
            'score': r['framing_score'],
            'rid': r['run_id'],
        })
        success += 1
    conn.commit()
    return success


def print_report(all_results, articles):
    """print vocabulary asymmetry report."""
    print("\n" + "=" * 60)
    print("SESSION 5 — VOCABULARY ASYMMETRY REPORT")
    print(f"  run_id: {RUN_ID}")
    print(f"  actor-article pairs analyzed: {len(all_results)}")
    print("=" * 60)

    # group by actor
    by_actor = defaultdict(list)
    for r in all_results:
        by_actor[r['actor']].append(r)

    # merge US + Israel + IDF as "us_israeli" group
    us_israeli_results = by_actor.get("US", []) + by_actor.get("Israel", []) + by_actor.get("IDF", [])
    iran_group_results = by_actor.get("Iran", []) + by_actor.get("IRGC", []) + by_actor.get("Hezbollah", [])

    print(f"\nACTOR GROUP FRAMING SCORES (positive=sanitized, negative=condemnatory):")
    for actor in ["US", "Israel", "IDF", "Iran", "IRGC", "Hezbollah"]:
        scores = [r['framing_score'] for r in by_actor.get(actor, [])]
        if scores:
            avg = sum(scores) / len(scores)
            print(f"  {actor:>12}: avg={avg:>+6.1f}  (n={len(scores)} articles)")

    # composite groups
    if us_israeli_results:
        us_avg = sum(r['framing_score'] for r in us_israeli_results) / len(us_israeli_results)
    else:
        us_avg = 0
    if iran_group_results:
        iran_avg = sum(r['framing_score'] for r in iran_group_results) / len(iran_group_results)
    else:
        iran_avg = 0

    print(f"\n  US+Israel+IDF composite: {us_avg:>+.2f}")
    print(f"  Iran+IRGC+Hezbollah composite: {iran_avg:>+.2f}")
    print(f"  DOUBLE STANDARD SCORE: {abs(us_avg - iran_avg):.2f}")

    # per-outlet asymmetry
    outlet_scores = defaultdict(lambda: {"us_israeli": [], "iranian": []})
    for r in all_results:
        outlet = r['outlet_domain']
        if r['actor'] in ("US", "Israel", "IDF"):
            outlet_scores[outlet]["us_israeli"].append(r['framing_score'])
        elif r['actor'] in ("Iran", "IRGC", "Hezbollah"):
            outlet_scores[outlet]["iranian"].append(r['framing_score'])

    print(f"\nOUTLET ASYMMETRY (ranked by double standard):")
    outlet_asymmetries = []
    for outlet, scores in outlet_scores.items():
        us_avg = sum(scores["us_israeli"]) / len(scores["us_israeli"]) if scores["us_israeli"] else 0
        iran_avg = sum(scores["iranian"]) / len(scores["iranian"]) if scores["iranian"] else 0
        asymmetry = us_avg - iran_avg  # positive = sanitizes US, condemns Iran
        outlet_asymmetries.append((outlet, us_avg, iran_avg, asymmetry))

    outlet_asymmetries.sort(key=lambda x: abs(x[3]), reverse=True)
    for outlet, us_avg, iran_avg, asym in outlet_asymmetries[:20]:
        direction = "sanitizes US/condemns Iran" if asym > 0 else "condemns US/sanitizes Iran"
        print(f"  {outlet[:35]:>35}: US={us_avg:>+5.1f} Iran={iran_avg:>+5.1f} Δ={asym:>+5.1f} ({direction})")

    # most common sanitizing and condemnatory terms
    print(f"\nMOST COMMON SANITIZING TERMS (near US/Israel):")
    us_san = Counter()
    for r in us_israeli_results:
        us_san.update(r['sanitizing_terms'])
    for term, count in us_san.most_common(10):
        print(f"  {term}: {count}")

    print(f"\nMOST COMMON CONDEMNATORY TERMS (near Iran):")
    iran_con = Counter()
    for r in iran_group_results:
        iran_con.update(r['condemnatory_terms'])
    for term, count in iran_con.most_common(10):
        print(f"  {term}: {count}")

    print("\n" + "=" * 60)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/vocabulary_asymmetry.log"),
        ],
    )
    log.info("loading spaCy en_core_web_lg...")
    nlp = load_nlp()
    log.info("spaCy loaded")

    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        # immutability check
        existing = conn.execute(text(
            "SELECT count(*) FROM actor_framing WHERE run_id = :rid"
        ), {"rid": RUN_ID})
        count = existing.fetchone()[0]
        if count > 0:
            log.warning(f"found {count} existing rows for {RUN_ID} — aborting")
            sys.exit(1)

        articles = get_articles(conn)
        log.info(f"loaded {len(articles)} articles")

        all_results = []
        for i, art in enumerate(articles):
            log.info(f"  [{i+1}/{len(articles)}] article {art['id']} ({art['cc']}, {art['outlet'][:30]})")
            results = analyze_article(nlp, art)
            all_results.extend(results)
            actors_found = [r['actor'] for r in results]
            log.info(f"    actors: {actors_found}")

        log.info(f"\nwriting {len(all_results)} actor-framing rows to DB")
        success = write_results(conn, all_results)
        log.info(f"  {success} rows written")

        # save to json
        outfile = f"analysis/session5_vocabulary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(outfile, 'w') as f:
            json.dump({
                'run_id': RUN_ID,
                'created': datetime.now().isoformat(),
                'method': 'spaCy proximity-based vocabulary framing analysis',
                'sanitizing_lexicon': SANITIZING_TERMS,
                'condemnatory_lexicon': CONDEMNATORY_TERMS,
                'proximity_window': PROXIMITY_WINDOW,
                'results': all_results,
            }, f, indent=2, ensure_ascii=False)
        log.info(f"  saved to {outfile}")

        print_report(all_results, articles)


if __name__ == "__main__":
    main()
