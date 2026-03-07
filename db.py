#!/usr/bin/env python3
"""
db.py — SQLAlchemy models for NewsKaleidoscope PostgreSQL backend.

all tables and relationships for the epistemic mapping system.
"""

import os
from datetime import datetime, date

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float, Boolean,
    DateTime, Date, ForeignKey, Index, UniqueConstraint, Enum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://newskal:newskal_dev@localhost:5432/newskaleidoscope"
)

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ── events ────────────────────────────────────────────────────────
class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    event_type = Column(String(50))  # military/election/economic/disaster/diplomatic
    event_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    primary_actors = Column(JSONB, default=list)  # jsonb array
    geographic_scope = Column(String(50))  # global/regional/bilateral
    # prompt parameterization: event-specific text for LLM prompts
    prompt_context = Column(Text, nullable=True)  # e.g. "US-Israel military action against Iran"
    absence_examples = Column(Text, nullable=True)  # e.g. "Iranian domestic press, Kurdish media"
    # corpus versioning: incremented when new sources are added
    corpus_version = Column(String(20), nullable=True)  # e.g. "v3"

    articles = relationship("Article", back_populates="event")
    analyses = relationship("Analysis", back_populates="event")
    clusters = relationship("Cluster", back_populates="event")
    coverage_gaps = relationship("CoverageGap", back_populates="event")
    mirror_gaps = relationship("MirrorGap", back_populates="event")


# ── sources ───────────────────────────────────────────────────────
class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(300), nullable=False)
    url = Column(String(1000))
    rss_url = Column(String(1000))
    country_code = Column(String(2))  # ISO 3166-1 alpha-2
    language_code = Column(String(5))  # ISO 639-1
    source_type = Column(String(50))  # wire/regional_flagship/state_wire/think_tank/etc
    editorial_language = Column(String(50))  # separate from country_code
    tier = Column(String(1))  # A/B/C/D
    is_state_adjacent = Column(Boolean, default=False)
    reliability_score = Column(Float, nullable=True)

    articles = relationship("Article", back_populates="source")

    __table_args__ = (
        Index("ix_sources_country", "country_code"),
        Index("ix_sources_type", "source_type"),
    )


# ── articles ──────────────────────────────────────────────────────
class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    url = Column(String(2000), nullable=False, unique=True)
    title = Column(String(1000))
    original_language = Column(String(50))
    translation_language = Column(String(50))
    raw_text = Column(Text)
    translated_text = Column(Text)
    publication_date = Column(Date, nullable=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    original_language_terms = Column(JSONB, default=list)  # pre-translation terms
    absence_flags = Column(JSONB, default=list)
    needs_human_review = Column(Boolean, default=False)

    event = relationship("Event", back_populates="articles")
    source = relationship("Source", back_populates="articles")
    analyses = relationship("Analysis", back_populates="article")
    council_verdicts = relationship("LLMCouncilVerdict", back_populates="article")
    cluster_memberships = relationship("ClusterMembership", back_populates="article")

    __table_args__ = (
        Index("ix_articles_url", "url"),
        Index("ix_articles_event", "event_id"),
        Index("ix_articles_source", "source_id"),
        Index("ix_articles_original_language_terms", "original_language_terms",
              postgresql_using="gin"),
        Index("ix_articles_absence_flags", "absence_flags",
              postgresql_using="gin"),
    )


# ── analyses ──────────────────────────────────────────────────────
class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    model_used = Column(String(100))  # qwen3-32b / llama3.3-70b / etc
    primary_frame = Column(Text)
    frame_confidence = Column(Float, nullable=True)
    positions = Column(JSONB, default=list)  # multi-label, not single value
    internal_tensions = Column(JSONB, default=list)
    absence_flags = Column(JSONB, default=list)
    unspeakable_positions = Column(JSONB, default=list)
    uncertainty_score = Column(Float, nullable=True)
    raw_llm_output = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="analyses")
    event = relationship("Event", back_populates="analyses")

    __table_args__ = (
        Index("ix_analyses_positions", "positions", postgresql_using="gin"),
        Index("ix_analyses_internal_tensions", "internal_tensions",
              postgresql_using="gin"),
        Index("ix_analyses_absence", "absence_flags", postgresql_using="gin"),
        Index("ix_analyses_unspeakable", "unspeakable_positions",
              postgresql_using="gin"),
    )


# ── llm council verdicts ─────────────────────────────────────────
class LLMCouncilVerdict(Base):
    __tablename__ = "llm_council_verdicts"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    models_agree = Column(Boolean)
    consensus_frame = Column(Text, nullable=True)
    confidence_level = Column(String(20))  # high/medium/contested
    model_readings = Column(JSONB)  # all three model outputs, always preserved
    dissent_recorded = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="council_verdicts")


# ── clusters ─────────────────────────────────────────────────────
class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    run_id = Column(String(50), nullable=True)  # e.g. "session_001", "session_003"
    method = Column(String(100), nullable=True)  # "llm_pass2", "sentence_embedding", etc.
    valid = Column(Boolean, default=True)  # false = known-bad run, preserved for record
    label = Column(String(500))  # emergent, not imposed
    description = Column(Text, nullable=True)  # longer cluster description
    article_count = Column(Integer, default=0)
    geographic_signature = Column(JSONB)
    stability_score = Column(Float, nullable=True)
    is_singleton = Column(Boolean, default=False)
    maps_to_conventional = Column(String(200), nullable=True)  # political science label
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="clusters")
    memberships = relationship("ClusterMembership", back_populates="cluster")

    # pgvector centroid if available
    if HAS_PGVECTOR:
        centroid_vector = Column(Vector(768), nullable=True)
    else:
        centroid_vector = Column(JSONB, nullable=True)


# ── cluster memberships ──────────────────────────────────────────
class ClusterMembership(Base):
    __tablename__ = "cluster_memberships"

    article_id = Column(Integer, ForeignKey("articles.id"), primary_key=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), primary_key=True)
    distance_from_centroid = Column(Float, nullable=True)

    article = relationship("Article", back_populates="cluster_memberships")
    cluster = relationship("Cluster", back_populates="memberships")


# ── acled events ─────────────────────────────────────────────────
class ACLEDEvent(Base):
    __tablename__ = "acled_events"

    id = Column(Integer, primary_key=True)
    acled_event_id = Column(String(100))  # external ID
    event_date = Column(Date)
    event_type = Column(String(100))
    country = Column(String(100))
    location = Column(String(500))
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    actors = Column(JSONB)
    fatalities = Column(Integer, nullable=True)
    source_scale = Column(String(50))  # local/national/international
    raw_data = Column(JSONB)
    linked_event_id = Column(Integer, ForeignKey("events.id"), nullable=True)

    __table_args__ = (
        Index("ix_acled_date", "event_date"),
        Index("ix_acled_country", "country"),
        Index("ix_acled_actors", "actors", postgresql_using="gin"),
    )


# ── coverage gaps ─────────────────────────────────────────────────
class CoverageGap(Base):
    __tablename__ = "coverage_gaps"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    country_code = Column(String(2))
    source_type = Column(String(50))
    gap_description = Column(Text)
    attempted = Column(Boolean, default=False)
    retrieved = Column(Boolean, default=False)
    dark_layer_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="coverage_gaps")


# ── mirror gap ────────────────────────────────────────────────────
class MirrorGap(Base):
    __tablename__ = "mirror_gap"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    us_frame = Column(Text)
    world_frame = Column(Text)
    delta_score = Column(Float, nullable=True)
    us_domestic_ratio = Column(Float, nullable=True)
    us_sources_count = Column(Integer, default=0)
    world_sources_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    event = relationship("Event", back_populates="mirror_gaps")


# ── syntactic features ────────────────────────────────────────────
class SyntacticFeature(Base):
    __tablename__ = "syntactic_features"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    run_id = Column(String(50), nullable=False)
    passive_voice_ratio = Column(Float, nullable=True)
    attribution_rate = Column(Float, nullable=True)
    opening_subject = Column(Text, nullable=True)
    direct_quotes_by_actor = Column(JSONB, default=dict)
    precision_asymmetry = Column(JSONB, default=dict)
    casualty_specificity = Column(JSONB, default=dict)
    elaboration_ratio = Column(Float, nullable=True)
    tokenism_flag = Column(Boolean, default=False)
    severe_tokenism_flag = Column(Boolean, default=False)
    subordinated_positions = Column(JSONB, default=list)
    concessive_constructions = Column(JSONB, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_syntactic_run", "run_id"),
    )


# ── actor framing ────────────────────────────────────────────────
class ActorFraming(Base):
    __tablename__ = "actor_framing"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    outlet_domain = Column(String(300), nullable=True)
    actor = Column(String(100), nullable=False)
    sanitizing_terms = Column(JSONB, default=list)
    condemnatory_terms = Column(JSONB, default=list)
    neutral_terms = Column(JSONB, default=list)
    framing_score = Column(Float, nullable=True)
    run_id = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_actor_framing_run", "run_id"),
        Index("ix_actor_framing_actor", "actor"),
    )


# ── presuppositions ──────────────────────────────────────────────
class Presupposition(Base):
    __tablename__ = "presuppositions"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    run_id = Column(String(50), nullable=False)
    presupposition = Column(Text)
    carrier_phrase = Column(Text)
    favors_actor = Column(Text)
    consistency_check = Column(Text)
    would_be_contested_by = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_presuppositions_run", "run_id"),
    )


# ── utility ───────────────────────────────────────────────────────
def get_session():
    """get a new database session."""
    return SessionLocal()


def init_db():
    """create all tables (for testing/development only — use alembic in production)."""
    Base.metadata.create_all(engine)
