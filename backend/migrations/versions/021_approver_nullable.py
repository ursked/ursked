"""make approver_id nullable for exclude rules

Revision ID: 021_approver_nullable
Revises: 020_approver_priority_exclude
Create Date: 2026-02-02
"""

from alembic import op
import sqlalchemy as sa

revision = "021_approver_nullable"
down_revision = "020_approver_priority_exclude"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "leave_approver_assignments",
        "approver_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "leave_approver_assignments",
        "approver_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
