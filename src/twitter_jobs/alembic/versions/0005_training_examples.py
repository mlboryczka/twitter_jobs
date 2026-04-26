"""training_examples table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_examples",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column("image_media_type", sa.Text(), nullable=True),
        sa.Column("tweet_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_handle", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("role_category", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "decision IN ('accept', 'dismiss')", name="ck_training_examples_decision"
        ),
    )
    op.create_index(
        "ix_training_examples_created_at",
        "training_examples",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_examples_created_at", table_name="training_examples")
    op.drop_table("training_examples")
