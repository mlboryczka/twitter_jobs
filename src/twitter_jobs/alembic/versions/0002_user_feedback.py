"""user feedback column and accepted status

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("user_feedback", sa.Text(), nullable=True),
    )

    # Replace status check constraint: drop seen/applied, add accepted.
    # Existing 'applied' rows are migrated to 'accepted'; existing 'seen' rows
    # are migrated to 'new' (they weren't really triaged either way).
    op.execute("UPDATE job_postings SET status = 'accepted' WHERE status = 'applied'")
    op.execute("UPDATE job_postings SET status = 'new' WHERE status = 'seen'")
    op.drop_constraint("ck_job_postings_status", "job_postings", type_="check")
    op.create_check_constraint(
        "ck_job_postings_status",
        "job_postings",
        "status IN ('new', 'accepted', 'dismissed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_postings_status", "job_postings", type_="check")
    op.execute("UPDATE job_postings SET status = 'applied' WHERE status = 'accepted'")
    op.create_check_constraint(
        "ck_job_postings_status",
        "job_postings",
        "status IN ('new', 'seen', 'applied', 'dismissed')",
    )
    op.drop_column("job_postings", "user_feedback")
