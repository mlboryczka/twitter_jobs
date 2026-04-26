"""is_us_eligible column on job_postings

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("is_us_eligible", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_postings", "is_us_eligible")
