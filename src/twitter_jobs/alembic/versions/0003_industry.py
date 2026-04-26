"""industry column on job_postings

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("industry", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_job_postings_industry", "job_postings", ["industry"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_postings_industry", table_name="job_postings")
    op.drop_column("job_postings", "industry")
