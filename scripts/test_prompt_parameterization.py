#!/usr/bin/env python3
"""
test_prompt_parameterization.py — verify no hardcoded event strings in prompts.

checks:
1. all four prompt templates accept {event_context} and render without error
2. no Iran-specific strings remain in rendered prompts when a different event is used
3. DB events have prompt_context populated
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import (
    FRAMING_EXTRACT_PROMPT,
    PASS1_PROMPT,
    PASS2_CLUSTER_PROMPT,
    ABSENCE_PROMPT,
)

TARIFF_CONTEXT = "US reciprocal tariffs on trading partners"
TARIFF_ABSENCE = "small-business owners, informal-sector workers, subsistence farmers"

IRAN_STRINGS = [
    "Iran", "iran", "Israeli", "Israel",
    "military action against", "military tensions",
]


def test_templates_accept_event_context():
    """all templates must format cleanly with event_context."""
    errors = []

    # FRAMING_EXTRACT_PROMPT
    try:
        rendered = FRAMING_EXTRACT_PROMPT.format(
            language="French", text="sample text", event_context=TARIFF_CONTEXT)
        assert TARIFF_CONTEXT in rendered, "event_context not in FRAMING_EXTRACT_PROMPT"
    except KeyError as e:
        errors.append(f"FRAMING_EXTRACT_PROMPT missing key: {e}")

    # PASS1_PROMPT
    try:
        rendered = PASS1_PROMPT.format(
            article_text="sample text", country_context="", event_context=TARIFF_CONTEXT)
        assert TARIFF_CONTEXT in rendered, "event_context not in PASS1_PROMPT"
    except KeyError as e:
        errors.append(f"PASS1_PROMPT missing key: {e}")

    # PASS2_CLUSTER_PROMPT
    try:
        rendered = PASS2_CLUSTER_PROMPT.format(
            n=10, n_countries=5, descriptions="sample", event_context=TARIFF_CONTEXT)
        assert TARIFF_CONTEXT in rendered, "event_context not in PASS2_CLUSTER_PROMPT"
    except KeyError as e:
        errors.append(f"PASS2_CLUSTER_PROMPT missing key: {e}")

    # ABSENCE_PROMPT
    try:
        rendered = ABSENCE_PROMPT.format(
            n=10, n_countries=5, country_list="US, FR", lang_list="en, fr",
            cluster_summary="sample", event_context=TARIFF_CONTEXT,
            absence_examples=TARIFF_ABSENCE)
        assert TARIFF_CONTEXT in rendered, "event_context not in ABSENCE_PROMPT"
        assert TARIFF_ABSENCE in rendered, "absence_examples not in ABSENCE_PROMPT"
    except KeyError as e:
        errors.append(f"ABSENCE_PROMPT missing key: {e}")

    return errors


def test_no_hardcoded_iran_in_tariff_render():
    """when rendering with tariff context, no Iran strings should appear."""
    errors = []

    rendered_all = ""
    rendered_all += FRAMING_EXTRACT_PROMPT.format(
        language="French", text="sample", event_context=TARIFF_CONTEXT)
    rendered_all += PASS1_PROMPT.format(
        article_text="sample", country_context="", event_context=TARIFF_CONTEXT)
    rendered_all += PASS2_CLUSTER_PROMPT.format(
        n=10, n_countries=5, descriptions="sample", event_context=TARIFF_CONTEXT)
    rendered_all += ABSENCE_PROMPT.format(
        n=10, n_countries=5, country_list="US", lang_list="en",
        cluster_summary="sample", event_context=TARIFF_CONTEXT,
        absence_examples=TARIFF_ABSENCE)

    for s in IRAN_STRINGS:
        if s in rendered_all:
            errors.append(f"hardcoded string '{s}' found in rendered tariff prompts")

    return errors


def test_db_events_have_prompt_context():
    """both events in DB should have prompt_context populated."""
    errors = []
    try:
        from db import get_session, Event
        session = get_session()
        events = session.query(Event).all()
        for ev in events:
            if not ev.prompt_context:
                errors.append(f"event {ev.id} ({ev.title}) has no prompt_context")
        session.close()
    except Exception as e:
        errors.append(f"DB check failed: {e}")
    return errors


if __name__ == "__main__":
    all_errors = []
    passed = 0

    print("test 1: templates accept event_context...", end=" ")
    errs = test_templates_accept_event_context()
    if errs:
        print("FAIL")
        all_errors.extend(errs)
    else:
        print("PASS")
        passed += 1

    print("test 2: no hardcoded Iran strings in tariff render...", end=" ")
    errs = test_no_hardcoded_iran_in_tariff_render()
    if errs:
        print("FAIL")
        all_errors.extend(errs)
    else:
        print("PASS")
        passed += 1

    print("test 3: DB events have prompt_context...", end=" ")
    errs = test_db_events_have_prompt_context()
    if errs:
        print("FAIL")
        all_errors.extend(errs)
    else:
        print("PASS")
        passed += 1

    print(f"\n{passed}/3 tests passed")
    if all_errors:
        print("\nerrors:")
        for e in all_errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("all clear — prompts are fully parameterized")
