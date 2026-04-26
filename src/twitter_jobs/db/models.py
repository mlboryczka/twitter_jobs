"""SQLAlchemy 2.0 declarative models.

Tables:
  - authors          denormalized author info
  - tweets           canonical store of every tweet we've seen
  - tweet_sources    m2m: same tweet can arrive via multiple sources
  - worker_state     generic key-value for cursor state
  - api_calls        cost ledger
  - job_postings     classifier output

Tweet IDs are stored as text because X uses 64-bit numeric IDs that can overflow
JavaScript numbers and cause subtle comparison bugs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "authors"

    author_id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tweets: Mapped[list["Tweet"]] = relationship(back_populates="author")


class Tweet(Base):
    __tablename__ = "tweets"

    tweet_id: Mapped[str] = mapped_column(Text, primary_key=True)
    author_id: Mapped[str] = mapped_column(
        Text, ForeignKey("authors.author_id"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lang: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    entities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_reply_to_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    referenced_tweets: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    author: Mapped[Author] = relationship(back_populates="tweets")

    __table_args__ = (
        Index("ix_tweets_created_at", "created_at", postgresql_using="btree"),
        Index("ix_tweets_author_id", "author_id"),
    )


class TweetSource(Base):
    __tablename__ = "tweet_sources"

    tweet_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tweets.tweet_id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("tweet_id", "source_type", name="pk_tweet_sources"),
        CheckConstraint(
            "source_type IN ('feed', 'bookmark', 'thread_reconstruction', 'search')",
            name="ck_tweet_sources_source_type",
        ),
        Index(
            "ix_tweet_sources_source_seen",
            "source_type",
            "seen_at",
        ),
    )


class WorkerState(Base):
    __tablename__ = "worker_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ApiCall(Base):
    __tablename__ = "api_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    tweets_returned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_api_calls_called_at", "called_at"),)


class JobPosting(Base):
    __tablename__ = "job_postings"

    tweet_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tweets.tweet_id", ondelete="CASCADE"), primary_key=True
    )
    role_category: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_remote: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    seniority: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_us_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    classifier_reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    needs_manual_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    tweet: Mapped[Tweet] = relationship()

    __table_args__ = (
        CheckConstraint(
            "role_category IN ('corp_dev', 'strategy', 'bd', 'ops', 'cos', 'unknown')",
            name="ck_job_postings_role_category",
        ),
        CheckConstraint(
            "seniority IS NULL OR seniority IN "
            "('ic', 'senior', 'lead', 'director', 'vp', 'exec', 'unknown')",
            name="ck_job_postings_seniority",
        ),
        CheckConstraint(
            "status IN ('new', 'accepted', 'dismissed')",
            name="ck_job_postings_status",
        ),
        Index("ix_job_postings_status_classified", "status", "classified_at"),
        Index("ix_job_postings_role_category", "role_category"),
        Index("ix_job_postings_industry", "industry"),
    )
