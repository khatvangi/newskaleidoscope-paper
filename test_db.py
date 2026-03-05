#!/usr/bin/env python3
"""
test_db.py — verify PostgreSQL schema by inserting and reading test records.
"""

from datetime import date, datetime
from db import get_session, Event, Source, Article, Analysis

def test_roundtrip():
    session = get_session()
    try:
        # create test event
        event = Event(
            title="US-Israel Military Strikes on Iran",
            description="Operation Epic Fury — coordinated US-Israeli military action against Iranian nuclear and missile infrastructure",
            event_type="military",
            event_date=date(2026, 2, 28),
            primary_actors=["United States", "Israel", "Iran"],
            geographic_scope="regional",
        )
        session.add(event)
        session.flush()

        # create test source
        source = Source(
            name="Press TV",
            url="https://www.presstv.ir",
            rss_url=None,
            country_code="IR",
            language_code="en",
            source_type="state_wire",
            editorial_language="English",
            tier="A",
            is_state_adjacent=True,
        )
        session.add(source)
        session.flush()

        # create test article
        article = Article(
            event_id=event.id,
            source_id=source.id,
            url="https://www.presstv.ir/test-article",
            title="IRGC: 650 casualties for US military in two days",
            original_language="English",
            translated_text="Iran's IRGC reports 650 US military casualties...",
            original_language_terms=["شهادت", "مقاومت", "تجاوز"],
            absence_flags=["no mention of civilian casualties in Iran"],
        )
        session.add(article)
        session.flush()

        # create test analysis
        analysis = Analysis(
            article_id=article.id,
            event_id=event.id,
            model_used="qwen3-32b-q4km",
            primary_frame="Iran frames military action as justified self-defense under Article 51",
            positions=["self-defense", "anti-imperialism", "Islamic resistance"],
            internal_tensions=[{
                "type": "Sovereignty vs. Regional Ambition",
                "description": "Invokes sovereignty while claiming right to strike US bases in neighboring countries"
            }],
            absence_flags=["no mention of nuclear program"],
            unspeakable_positions=["Iran as aggressor rather than victim"],
            raw_llm_output={"framing_description": "test output"},
        )
        session.add(analysis)
        session.commit()

        # read back
        read_event = session.query(Event).filter_by(title="US-Israel Military Strikes on Iran").first()
        assert read_event is not None, "event not found"
        assert read_event.primary_actors == ["United States", "Israel", "Iran"]
        print(f"✓ event: {read_event.title} ({read_event.event_type})")

        read_source = session.query(Source).filter_by(name="Press TV").first()
        assert read_source is not None, "source not found"
        assert read_source.is_state_adjacent == True
        print(f"✓ source: {read_source.name} ({read_source.country_code}, state_adjacent={read_source.is_state_adjacent})")

        read_article = session.query(Article).filter_by(url="https://www.presstv.ir/test-article").first()
        assert read_article is not None, "article not found"
        assert len(read_article.original_language_terms) == 3
        print(f"✓ article: {read_article.title[:50]}... (terms: {read_article.original_language_terms})")

        read_analysis = session.query(Analysis).filter_by(article_id=read_article.id).first()
        assert read_analysis is not None, "analysis not found"
        assert len(read_analysis.positions) == 3
        assert len(read_analysis.internal_tensions) == 1
        print(f"✓ analysis: {read_analysis.primary_frame[:60]}...")
        print(f"  tensions: {read_analysis.internal_tensions[0]['type']}")
        print(f"  unspeakable: {read_analysis.unspeakable_positions}")

        # test relationships
        assert read_article.event.title == read_event.title
        assert read_article.source.name == read_source.name
        assert len(read_event.articles) == 1
        print(f"✓ relationships: article→event, article→source, event→articles")

        # cleanup test data
        session.delete(analysis)
        session.delete(article)
        session.delete(source)
        session.delete(event)
        session.commit()
        print(f"\n✓ all tests passed, test data cleaned up")

    except Exception as e:
        session.rollback()
        print(f"✗ FAILED: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    test_roundtrip()
