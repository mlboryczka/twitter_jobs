"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-24

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "authors",
        sa.Column("author_id", sa.Text(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "public_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "tweets",
        sa.Column("tweet_id", sa.Text(), primary_key=True),
        sa.Column(
            "author_id",
            sa.Text(),
            sa.ForeignKey("authors.author_id"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lang", sa.Text(), nullable=True),
        sa.Column(
            "public_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("in_reply_to_user_id", sa.Text(), nullable=True),
        sa.Column(
            "referenced_tweets",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "raw_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_tweets_created_at", "tweets", ["created_at"])
    op.create_index("ix_tweets_author_id", "tweets", ["author_id"])

    op.create_table(
        "tweet_sources",
        sa.Column(
            "tweet_id",
            sa.Text(),
            sa.ForeignKey("tweets.tweet_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("tweet_id", "source_type", name="pk_tweet_sources"),
        sa.CheckConstraint(
            "source_type IN ('feed', 'bookmark', 'thread_reconstruction', 'search')",
            name="ck_tweet_sources_source_type",
        ),
    )
    op.create_index(
        "ix_tweet_sources_source_seen",
        "tweet_sources",
        ["source_type", "seen_at"],
    )

    op.create_table(
        "worker_state",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "api_calls",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("tweets_returned", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_api_calls_called_at", "api_calls", ["called_at"])

    op.create_table(
        "job_postings",
        sa.Column(
            "tweet_id",
            sa.Text(),
            sa.ForeignKey("tweets.tweet_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role_category", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("is_remote", sa.Boolean(), nullable=True),
        sa.Column("seniority", sa.Text(), nullable=True),
        sa.Column("apply_link", sa.Text(), nullable=True),
        sa.Column(
            "classifier_reasoning",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "needs_manual_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="new",
        ),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissal_reason", sa.Text(), nullable=True),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role_category IN ('corp_dev', 'strategy', 'bd', 'ops', 'cos', 'unknown')",
            name="ck_job_postings_role_category",
        ),
        sa.CheckConstraint(
            "seniority IS NULL OR seniority IN "
            "('ic', 'senior', 'lead', 'director', 'vp', 'exec', 'unknown')",
            name="ck_job_postings_seniority",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'seen', 'applied', 'dismissed')",
            name="ck_job_postings_status",
        ),
    )
    op.create_index(
        "ix_job_postings_status_classified",
        "job_postings",
        ["status", "classified_at"],
    )
    op.create_index(
        "ix_job_postings_role_category",
        "job_postings",
        ["role_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_postings_role_category", table_name="job_postings")
    op.drop_index("ix_job_postings_status_classified", table_name="job_postings")
    op.drop_table("job_postings")

    op.drop_index("ix_api_calls_called_at", table_name="api_calls")
    op.drop_table("api_calls")

    op.drop_table("worker_state")

    op.drop_index("ix_tweet_sources_source_seen", table_name="tweet_sources")
    op.drop_table("tweet_sources")

    op.drop_index("ix_tweets_author_id", table_name="tweets")
    op.drop_index("ix_tweets_created_at", table_name="tweets")
    op.drop_table("tweets")

    op.drop_table("authors")
