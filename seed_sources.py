#!/usr/bin/env python3
"""
seed_sources.py — populate sources table from outlets.json + known institutional sources.
"""

import json
from db import get_session, Source

# map country names to ISO 3166-1 alpha-2
COUNTRY_CODES = {
    "Qatar": "QA", "United Kingdom": "GB", "United States": "US", "France": "FR",
    "Germany": "DE", "China": "CN", "Japan": "JP", "India": "IN", "Pakistan": "PK",
    "Turkey": "TR", "South Korea": "KR", "Russia": "RU", "Brazil": "BR",
    "Nigeria": "NG", "South Africa": "ZA", "Egypt": "EG", "Kenya": "KE",
    "Israel": "IL", "Australia": "AU", "Canada": "CA", "Mexico": "MX",
    "Argentina": "AR", "Colombia": "CO", "Indonesia": "ID", "Singapore": "SG",
    "Taiwan": "TW", "Hong Kong": "HK", "Lebanon": "LB", "Iran": "IR",
    "Italy": "IT", "Spain": "ES", "Netherlands": "NL", "Belgium": "BE",
    "Switzerland": "CH", "Austria": "AT", "Poland": "PL", "Czech Republic": "CZ",
    "Sweden": "SE", "Norway": "NO", "Denmark": "DK", "Finland": "FI",
    "Ireland": "IE", "New Zealand": "NZ", "Thailand": "TH", "Malaysia": "MY",
    "Philippines": "PH", "Vietnam": "VN", "Bangladesh": "BD", "Sri Lanka": "LK",
    "UAE": "AE", "Saudi Arabia": "SA", "Iraq": "IQ", "Jordan": "JO",
    "Morocco": "MA", "Tunisia": "TN", "Algeria": "DZ", "Ghana": "GH",
    "Tanzania": "TZ", "Ethiopia": "ET", "Uganda": "UG", "Rwanda": "RW",
    "Vatican": "VA", "Palestine": "PS",
}

# map language names to ISO 639-1
LANGUAGE_CODES = {
    "English": "en", "Arabic": "ar", "French": "fr", "German": "de",
    "Spanish": "es", "Portuguese": "pt", "Russian": "ru", "Chinese": "zh",
    "Japanese": "ja", "Korean": "ko", "Turkish": "tr", "Hindi": "hi",
    "Urdu": "ur", "Bengali": "bn", "Indonesian": "id", "Malay": "ms",
    "Persian": "fa", "Hebrew": "he", "Italian": "it", "Dutch": "nl",
    "Polish": "pl", "Czech": "cs", "Swedish": "sv", "Norwegian": "no",
    "Danish": "da", "Finnish": "fi", "Thai": "th", "Vietnamese": "vi",
}

# infer source_type from bias_notes and tier
STATE_ADJACENT_KEYWORDS = ["state-funded", "state-owned", "government-affiliated",
                           "state media", "state-aligned", "state-adjacent"]


def infer_source_type(outlet):
    """infer source_type from outlet metadata."""
    tier = outlet.get("tier", 2)
    notes = outlet.get("bias_notes", "").lower()

    if any(kw in notes for kw in STATE_ADJACENT_KEYWORDS):
        return "state_wire"
    if tier == 1:
        return "regional_flagship"
    if tier == 2:
        return "regional_flagship"
    return "regional_flagship"


def is_state_adjacent(outlet):
    """check if outlet is state-adjacent from bias notes."""
    notes = outlet.get("bias_notes", "").lower()
    return any(kw in notes for kw in STATE_ADJACENT_KEYWORDS)


def seed_from_outlets_json():
    """load outlets.json and insert into sources table."""
    with open("outlets.json", "r", encoding="utf-8") as f:
        outlets = json.load(f)

    session = get_session()
    added = 0
    skipped = 0

    for outlet in outlets:
        domain = outlet.get("domain", "")
        url = f"https://{domain}" if domain else outlet.get("name", "")

        # check if already exists
        existing = session.query(Source).filter_by(url=url).first()
        if existing:
            skipped += 1
            continue

        country = outlet.get("country", "")
        country_code = COUNTRY_CODES.get(country, "")
        language = outlet.get("language", "English")
        language_code = LANGUAGE_CODES.get(language, "en")
        tier_num = outlet.get("tier", 2)
        tier_letter = {1: "A", 2: "B", 3: "C"}.get(tier_num, "B")

        source = Source(
            name=outlet.get("name", domain),
            url=url,
            rss_url=outlet.get("rss_url"),
            country_code=country_code,
            language_code=language_code,
            source_type=infer_source_type(outlet),
            editorial_language=language,
            tier=tier_letter,
            is_state_adjacent=is_state_adjacent(outlet),
        )
        session.add(source)
        added += 1

    # add institutional sources not in outlets.json
    institutional = [
        {
            "name": "UN Security Council Press", "url": "https://press.un.org",
            "country_code": "", "language_code": "en",
            "source_type": "un_security_council", "editorial_language": "English",
            "tier": "A", "is_state_adjacent": False,
        },
    ]

    for inst in institutional:
        existing = session.query(Source).filter_by(url=inst["url"]).first()
        if not existing:
            source = Source(**inst)
            session.add(source)
            added += 1
        else:
            skipped += 1

    session.commit()
    session.close()
    return added, skipped


def main():
    added, skipped = seed_from_outlets_json()
    print(f"sources seeded: {added} added, {skipped} skipped (already existed)")

    # verify
    session = get_session()
    total = session.query(Source).count()
    state_adj = session.query(Source).filter_by(is_state_adjacent=True).count()
    tiers = {}
    for source in session.query(Source).all():
        tiers[source.tier] = tiers.get(source.tier, 0) + 1
    session.close()

    print(f"total sources in db: {total}")
    print(f"state-adjacent: {state_adj}")
    print(f"by tier: {tiers}")


if __name__ == "__main__":
    main()
