"""applied status

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_job_postings_status", "job_postings", type_="check")
    op.create_check_constraint(
        "ck_job_postings_status",
        "job_postings",
        "status IN ('new', 'accepted', 'applied', 'dismissed')",
    )


def downgrade() -> None:
    op.execute("UPDATE job_postings SET status='accepted' WHERE status='applied'")
    op.drop_constraint("ck_job_postings_status", "job_postings", type_="check")
    op.create_check_constraint(
        "ck_job_postings_status",
        "job_postings",
        "status IN ('new', 'accepted', 'dismissed')",
    )
