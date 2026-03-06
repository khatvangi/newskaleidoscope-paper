#!/usr/bin/env python3
"""
syntax_analyzer.py — session 5: syntactic feature extraction for covert bias detection.

extracts passive voice, attribution patterns, quote asymmetry, elaboration ratio,
concessive constructions, and casualty specificity from all 94 articles.
uses spaCy only — no LLM calls. stores results in syntactic_features table.

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/syntax_analyzer.log"),
    ],
)
log = logging.getLogger("syntax")

DB_URL = "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
RUN_ID = "session_005"

# actor classification patterns
US_ISRAELI_PATTERNS = [
    "united states", "u.s.", "us ", "america", "washington", "pentagon",
    "white house", "trump", "biden", "state department",
    "israel", "israeli", "idf", "netanyahu", "tel aviv", "jerusalem",
    "mossad", "shin bet",
]
IRANIAN_PATTERNS = [
    "iran", "iranian", "tehran", "irgc", "khamenei", "raisi",
    "rouhani", "zarif", "hezbollah", "houthi", "islamic republic",
    "revolutionary guard", "quds force",
]
INTERNATIONAL_PATTERNS = [
    "united nations", "un ", "iaea", "security council",
    "international court", "icj", "nato", "european union", "eu ",
]

# attribution verbs
ATTRIBUTION_VERBS = {
    "said", "say", "says", "noted", "claimed", "argued", "maintained",
    "insisted", "stated", "warned", "suggested", "asserted", "contended",
    "declared", "alleged", "told", "added", "explained", "stressed",
    "emphasized", "acknowledged", "confirmed", "denied", "accused",
    "according",
}

# concessive markers
CONCESSIVE_MARKERS = [
    "although", "though", "even though", "while",
    "despite", "in spite of", "notwithstanding",
    "however", "nevertheless", "nonetheless",
    "but", "yet",
]

# hedging language for precision asymmetry
HEDGING_TERMS = {
    "reportedly", "allegedly", "claimed", "unverified", "unconfirmed",
    "according to", "purported", "suspected", "believed to",
    "sources say", "reports suggest", "state media",
}

# casualty language patterns
CASUALTY_NAMED_RE = re.compile(
    r'(?:killed|died|dead|wounded|injured|martyred)\s.*?'
    r'(?:named|identified as|was\s)',
    re.IGNORECASE
)
CASUALTY_NUMBER_RE = re.compile(
    r'(\d+)\s+(?:people|civilians|soldiers|fighters|militants|casualties|dead|killed|wounded|injured)',
    re.IGNORECASE
)
CASUALTY_HEDGED_RE = re.compile(
    r'(?:reports?\s+(?:of|suggest)|casualties\s+(?:were|are)\s+(?:reported|estimated)|'
    r'(?:allegedly|reportedly)\s+(?:killed|wounded)|unconfirmed\s+(?:reports?|casualties))',
    re.IGNORECASE
)


def load_nlp():
    """load spacy model with optimized pipeline."""
    nlp = spacy.load("en_core_web_lg")
    return nlp


def get_articles(conn):
    """fetch all articles for event 2 with source info."""
    rows = conn.execute(text("""
        SELECT a.id, a.title, a.original_language, a.translated_text, a.raw_text,
               s.country_code, s.name as outlet
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
            'text': article_text,
        })
    return articles


def classify_actor(text_span):
    """classify a text span as us_israeli, iranian, international, civilian, or other."""
    lower = text_span.lower()
    for p in US_ISRAELI_PATTERNS:
        if p in lower:
            return "us_israeli_official"
    for p in IRANIAN_PATTERNS:
        if p in lower:
            return "iranian_official"
    for p in INTERNATIONAL_PATTERNS:
        if p in lower:
            return "international"
    # check for civilian indicators
    if any(w in lower for w in ["civilian", "resident", "family", "doctor", "nurse", "teacher"]):
        return "civilian"
    if any(w in lower for w in ["official", "minister", "spokesman", "spokesperson", "ambassador"]):
        return "unnamed_official"
    return "other"


def extract_passive_voice(doc):
    """count passive voice constructions."""
    passive_count = 0
    total_sents = 0
    for sent in doc.sents:
        total_sents += 1
        # check for passive: nsubjpass or agent (by-phrase in passive)
        has_passive = False
        for token in sent:
            if token.dep_ == "nsubjpass":
                has_passive = True
                break
            # also check for auxpass
            if token.dep_ == "auxpass":
                has_passive = True
                break
            # spacy 3.x sometimes uses "nsubj:pass" pattern via morph
            if token.dep_ == "nsubj" and token.head.morph.get("Voice") == ["Pass"]:
                has_passive = True
                break
        if has_passive:
            passive_count += 1
    ratio = passive_count / total_sents if total_sents > 0 else 0.0
    return ratio, passive_count, total_sents


def extract_attribution(doc):
    """count sentences with attribution verbs."""
    attributed = 0
    total_sents = 0
    for sent in doc.sents:
        total_sents += 1
        for token in sent:
            if token.lemma_.lower() in ATTRIBUTION_VERBS:
                attributed += 1
                break
    ratio = attributed / total_sents if total_sents > 0 else 0.0
    return ratio, attributed, total_sents


def extract_opening_subject(doc):
    """extract the grammatical subject of the first sentence."""
    for sent in doc.sents:
        # find root verb
        for token in sent:
            if token.dep_ == "ROOT":
                # find nsubj or nsubjpass of root
                for child in token.children:
                    if child.dep_ in ("nsubj", "nsubjpass"):
                        # get the full noun phrase
                        subtree = " ".join(t.text for t in child.subtree)
                        return subtree.strip()
                # if no nsubj found, try the first noun chunk
                break
        # fallback: first noun chunk
        for chunk in sent.noun_chunks:
            return chunk.text.strip()
        break
    return None


def extract_direct_quotes(doc, raw_text):
    """find direct quotes and attribute them to actors."""
    quotes_by_actor = defaultdict(int)

    # find quoted text using regex on raw text
    # handle both straight and curly quotes
    quote_pattern = re.compile(r'["\u201c](.*?)["\u201d]', re.DOTALL)
    matches = list(quote_pattern.finditer(raw_text))

    for match in matches:
        quote_text = match.group(1)
        # skip very short "quotes" (likely scare quotes)
        if len(quote_text) < 20:
            continue

        # look for attribution in surrounding context (100 chars before and after)
        start = max(0, match.start() - 150)
        end = min(len(raw_text), match.end() + 150)
        context = raw_text[start:end].lower()

        # identify speaker
        actor = classify_actor(context)
        quotes_by_actor[actor] += 1

    return dict(quotes_by_actor)


def extract_precision_asymmetry(doc, raw_text):
    """measure precision of language about US/Israeli vs Iranian actions."""
    text_lower = raw_text.lower()

    # find sentences mentioning each actor group
    us_sents = []
    iran_sents = []
    for sent in doc.sents:
        sent_lower = sent.text.lower()
        is_us = any(p in sent_lower for p in US_ISRAELI_PATTERNS)
        is_iran = any(p in sent_lower for p in IRANIAN_PATTERNS)
        if is_us:
            us_sents.append(sent.text)
        if is_iran:
            iran_sents.append(sent.text)

    def precision_score(sentences):
        """count precision indicators: numbers, specific locations, named targets."""
        numbers = 0
        hedges = 0
        for s in sentences:
            # count specific numbers
            numbers += len(re.findall(r'\b\d+\b', s))
            # count hedging
            s_lower = s.lower()
            for h in HEDGING_TERMS:
                if h in s_lower:
                    hedges += 1
        return {"numbers": numbers, "hedges": hedges, "sentence_count": len(sentences)}

    us_precision = precision_score(us_sents)
    iran_precision = precision_score(iran_sents)

    # normalize by sentence count
    us_norm = (us_precision["numbers"] - us_precision["hedges"]) / max(1, us_precision["sentence_count"])
    iran_norm = (iran_precision["numbers"] - iran_precision["hedges"]) / max(1, iran_precision["sentence_count"])

    return {
        "us_israeli": us_precision,
        "iranian": iran_precision,
        "asymmetry_score": round(us_norm - iran_norm, 3),
    }


def extract_casualty_specificity(raw_text):
    """analyze how casualties are described — named, numbered, or hedged."""
    named = len(CASUALTY_NAMED_RE.findall(raw_text))
    numbered = CASUALTY_NUMBER_RE.findall(raw_text)
    hedged = len(CASUALTY_HEDGED_RE.findall(raw_text))

    # try to determine whose casualties
    # split text into us/israeli context vs iranian context
    sentences = raw_text.split(". ")
    us_casualties = {"named": 0, "numbered": 0, "hedged": 0}
    iran_casualties = {"named": 0, "numbered": 0, "hedged": 0}

    for s in sentences:
        s_lower = s.lower()
        has_casualty = any(w in s_lower for w in ["killed", "died", "dead", "wounded", "injured", "casualties", "martyred"])
        if not has_casualty:
            continue
        is_us = any(p in s_lower for p in US_ISRAELI_PATTERNS[:10])
        is_iran = any(p in s_lower for p in IRANIAN_PATTERNS[:8])

        target = None
        if is_iran and not is_us:
            target = iran_casualties
        elif is_us and not is_iran:
            target = us_casualties

        if target:
            if CASUALTY_NAMED_RE.search(s):
                target["named"] += 1
            if CASUALTY_NUMBER_RE.search(s):
                target["numbered"] += 1
            if CASUALTY_HEDGED_RE.search(s):
                target["hedged"] += 1

    return {
        "total_named": named,
        "total_numbered": len(numbered),
        "total_hedged": hedged,
        "us_israeli_casualties": us_casualties,
        "iranian_casualties": iran_casualties,
    }


def extract_elaboration_ratio(doc, raw_text):
    """measure structural asymmetry in elaboration of different actor groups.

    instead of matching free-form positions to paragraphs,
    measures how much text/sourcing/quoting each actor group receives.
    """
    # split into paragraphs
    paragraphs = [p.strip() for p in raw_text.split("\n") if len(p.strip()) > 30]
    if not paragraphs:
        return None, False, False

    us_score = {"words": 0, "named_sources": 0, "quotes": 0, "paragraphs": 0}
    iran_score = {"words": 0, "named_sources": 0, "quotes": 0, "paragraphs": 0}

    for para in paragraphs:
        para_lower = para.lower()
        is_us = any(p in para_lower for p in US_ISRAELI_PATTERNS[:10])
        is_iran = any(p in para_lower for p in IRANIAN_PATTERNS[:8])

        if is_us and not is_iran:
            target = us_score
        elif is_iran and not is_us:
            target = iran_score
        else:
            continue

        target["words"] += len(para.split())
        target["paragraphs"] += 1
        # count named sources (capitalized word + attribution verb)
        if re.search(r'[A-Z][a-z]+\s+(?:said|told|stated|noted|argued)', para):
            target["named_sources"] += 1
        # count quotes
        target["quotes"] += len(re.findall(r'["\u201c]', para))

    # compute composite score
    def composite(s):
        return s["words"] + s["named_sources"] * 50 + s["quotes"] * 30

    us_comp = composite(us_score)
    iran_comp = composite(iran_score)

    if us_comp == 0 and iran_comp == 0:
        return None, False, False

    denom = min(us_comp, iran_comp)
    if denom == 0:
        ratio = float(max(us_comp, iran_comp))  # one side has zero
    else:
        ratio = max(us_comp, iran_comp) / denom

    tokenism = ratio > 4.0
    severe = ratio > 8.0

    return round(ratio, 2), tokenism, severe


def extract_concessive_constructions(doc):
    """find concessive/contrastive constructions and what they subordinate."""
    constructions = []

    for sent in doc.sents:
        sent_text = sent.text
        sent_lower = sent_text.lower()

        # check for concessive markers
        for marker in CONCESSIVE_MARKERS:
            if marker in sent_lower:
                # try to split into subordinated vs main clause
                parts = None

                if marker in ("although", "though", "even though", "while", "despite"):
                    # pattern: "Although X, Y" — X is subordinated
                    idx = sent_lower.find(marker)
                    rest = sent_text[idx + len(marker):]
                    # find comma separating clauses
                    comma_idx = rest.find(",")
                    if comma_idx > 5:
                        parts = {
                            "subordinated_claim": rest[:comma_idx].strip(),
                            "main_claim": rest[comma_idx+1:].strip(),
                            "pattern": marker,
                        }
                elif marker == "however":
                    # pattern: "X. However, Y" or "X, however, Y"
                    idx = sent_lower.find(marker)
                    parts = {
                        "subordinated_claim": sent_text[:idx].strip().rstrip(","),
                        "main_claim": sent_text[idx + len(marker):].strip().lstrip(",").strip(),
                        "pattern": marker,
                    }
                elif marker in ("but", "yet"):
                    idx = sent_lower.find(f" {marker} ")
                    if idx > 0:
                        parts = {
                            "subordinated_claim": sent_text[:idx].strip(),
                            "main_claim": sent_text[idx + len(marker) + 2:].strip(),
                            "pattern": marker,
                        }

                if parts and len(parts.get("subordinated_claim", "")) > 10:
                    constructions.append(parts)
                break  # one marker per sentence

    return constructions


def analyze_article(nlp, article):
    """run all syntactic analyses on a single article."""
    text = article['text']
    if not text or len(text.strip()) < 50:
        return None

    # spacy processing
    # limit to first 100k chars to avoid memory issues
    doc = nlp(text[:100000])

    # extract all features
    pv_ratio, pv_count, total_sents = extract_passive_voice(doc)
    attr_ratio, attr_count, _ = extract_attribution(doc)
    opening = extract_opening_subject(doc)
    quotes = extract_direct_quotes(doc, text)
    precision = extract_precision_asymmetry(doc, text)
    casualties = extract_casualty_specificity(text)
    elab_ratio, tokenism, severe = extract_elaboration_ratio(doc, text)
    concessives = extract_concessive_constructions(doc)

    return {
        "article_id": article['id'],
        "run_id": RUN_ID,
        "passive_voice_ratio": round(pv_ratio, 4),
        "attribution_rate": round(attr_ratio, 4),
        "opening_subject": opening,
        "direct_quotes_by_actor": quotes,
        "precision_asymmetry": precision,
        "casualty_specificity": casualties,
        "elaboration_ratio": elab_ratio,
        "tokenism_flag": tokenism,
        "severe_tokenism_flag": severe,
        "subordinated_positions": concessives,
        "concessive_constructions": [c["pattern"] for c in concessives],
    }


def write_results(conn, results):
    """write syntactic features to DB."""
    success = 0
    for r in results:
        if r is None:
            continue
        conn.execute(text("""
            INSERT INTO syntactic_features
                (article_id, run_id, passive_voice_ratio, attribution_rate,
                 opening_subject, direct_quotes_by_actor, precision_asymmetry,
                 casualty_specificity, elaboration_ratio, tokenism_flag,
                 severe_tokenism_flag, subordinated_positions, concessive_constructions)
            VALUES
                (:aid, :rid, :pv, :attr, :opening,
                 CAST(:quotes AS jsonb), CAST(:precision AS jsonb),
                 CAST(:casualties AS jsonb), :elab, :tokenism, :severe,
                 CAST(:subordinated AS jsonb), CAST(:concessives AS jsonb))
        """), {
            'aid': r['article_id'],
            'rid': r['run_id'],
            'pv': r['passive_voice_ratio'],
            'attr': r['attribution_rate'],
            'opening': r['opening_subject'],
            'quotes': json.dumps(r['direct_quotes_by_actor']),
            'precision': json.dumps(r['precision_asymmetry']),
            'casualties': json.dumps(r['casualty_specificity']),
            'elab': r['elaboration_ratio'],
            'tokenism': r['tokenism_flag'],
            'severe': r['severe_tokenism_flag'],
            'subordinated': json.dumps(r['subordinated_positions']),
            'concessives': json.dumps(r['concessive_constructions']),
        })
        success += 1
    conn.commit()
    return success


def print_report(results, conn):
    """print analysis report."""
    valid = [r for r in results if r is not None]

    print("\n" + "=" * 60)
    print("SESSION 5 — SYNTACTIC ANALYSIS REPORT")
    print(f"  run_id: {RUN_ID}")
    print(f"  articles analyzed: {len(valid)} / {len(results)}")
    print("=" * 60)

    # passive voice distribution
    pv_vals = [r['passive_voice_ratio'] for r in valid]
    buckets = {"0-20%": 0, "20-40%": 0, "40-60%": 0, "60%+": 0}
    for v in pv_vals:
        if v < 0.2: buckets["0-20%"] += 1
        elif v < 0.4: buckets["20-40%"] += 1
        elif v < 0.6: buckets["40-60%"] += 1
        else: buckets["60%+"] += 1

    print(f"\nPASSIVE VOICE DISTRIBUTION:")
    for bucket, count in buckets.items():
        bar = "█" * count
        print(f"  {bucket:>8}: {count:>3} {bar}")
    avg_pv = sum(pv_vals) / len(pv_vals) if pv_vals else 0
    print(f"  average: {avg_pv:.1%}")

    # attribution rate
    attr_vals = [r['attribution_rate'] for r in valid]
    avg_attr = sum(attr_vals) / len(attr_vals) if attr_vals else 0
    print(f"\nATTRIBUTION RATE:")
    print(f"  average: {avg_attr:.1%}")

    # top 10 by elaboration ratio
    elab_valid = [r for r in valid if r['elaboration_ratio'] is not None]
    elab_sorted = sorted(elab_valid, key=lambda x: x['elaboration_ratio'], reverse=True)
    print(f"\nTOP 10 BY ELABORATION RATIO:")
    for r in elab_sorted[:10]:
        flag = " *** SEVERE TOKENISM" if r['severe_tokenism_flag'] else (" * TOKENISM" if r['tokenism_flag'] else "")
        print(f"  article {r['article_id']:>3}: {r['elaboration_ratio']:>8.1f}{flag}")

    # tokenism counts
    tokenism_count = sum(1 for r in valid if r['tokenism_flag'])
    severe_count = sum(1 for r in valid if r['severe_tokenism_flag'])
    print(f"\nTOKENISM FLAGS:")
    print(f"  tokenism (>4.0): {tokenism_count} / {len(valid)}")
    print(f"  severe (>8.0):   {severe_count} / {len(valid)}")

    # opening subject distribution
    print(f"\nOPENING SUBJECT DISTRIBUTION:")
    opening_cats = Counter()
    for r in valid:
        if r['opening_subject']:
            cat = classify_actor(r['opening_subject'])
            opening_cats[cat] += 1
        else:
            opening_cats["none_detected"] += 1
    for cat, count in opening_cats.most_common():
        print(f"  {cat:>25}: {count}")

    # direct quote asymmetry
    print(f"\nDIRECT QUOTE DISTRIBUTION (corpus-wide):")
    total_quotes = Counter()
    for r in valid:
        for actor, count in r['direct_quotes_by_actor'].items():
            total_quotes[actor] += count
    for actor, count in total_quotes.most_common():
        print(f"  {actor:>25}: {count}")

    # concessive constructions
    conc_counts = [len(r['concessive_constructions']) for r in valid]
    heavy_qual = sum(1 for c in conc_counts if c > 3)
    print(f"\nCONCESSIVE CONSTRUCTIONS:")
    print(f"  average per article: {sum(conc_counts)/len(conc_counts):.1f}")
    print(f"  heavy qualification (>3): {heavy_qual} articles")

    # concessive marker frequency
    marker_counts = Counter()
    for r in valid:
        for m in r['concessive_constructions']:
            marker_counts[m] += 1
    print(f"  marker frequency:")
    for m, c in marker_counts.most_common():
        print(f"    {m}: {c}")

    print("\n" + "=" * 60)


def main():
    log.info("loading spaCy en_core_web_lg...")
    nlp = load_nlp()
    log.info("spaCy loaded")

    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        # check existing data
        existing = conn.execute(text(
            "SELECT count(*) FROM syntactic_features WHERE run_id = :rid"
        ), {"rid": RUN_ID})
        count = existing.fetchone()[0]
        if count > 0:
            log.warning(f"found {count} existing rows for {RUN_ID} — aborting to preserve immutability")
            log.warning("delete manually or use a different run_id if re-running")
            sys.exit(1)

        articles = get_articles(conn)
        log.info(f"loaded {len(articles)} articles")

        results = []
        for i, art in enumerate(articles):
            log.info(f"  [{i+1}/{len(articles)}] article {art['id']} ({art['cc']}, {art['lang']}, {art['outlet'][:30]})")

            # only analyze english text (original english or translated)
            result = analyze_article(nlp, art)
            if result:
                results.append(result)
                log.info(f"    PV={result['passive_voice_ratio']:.0%} ATTR={result['attribution_rate']:.0%} "
                         f"ELAB={result['elaboration_ratio'] or 'N/A'} conc={len(result['concessive_constructions'])}")
            else:
                log.warning(f"    skipped — no text")
                results.append(None)

        log.info(f"\nwriting {sum(1 for r in results if r)} results to DB")
        success = write_results(conn, results)
        log.info(f"  {success} rows written")

        # save to json (immutable, timestamped)
        outfile = f"analysis/session5_syntactic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(outfile, 'w') as f:
            json.dump({
                'run_id': RUN_ID,
                'created': datetime.now().isoformat(),
                'method': 'spaCy en_core_web_lg syntactic feature extraction',
                'articles_analyzed': len([r for r in results if r]),
                'results': [r for r in results if r],
            }, f, indent=2, ensure_ascii=False)
        log.info(f"  saved to {outfile}")

        print_report(results, conn)


if __name__ == "__main__":
    main()
