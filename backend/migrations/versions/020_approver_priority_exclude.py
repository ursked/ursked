"""add priority and exclude columns to leave_approver_assignments

Revision ID: 020_approver_priority_exclude
Revises: 019_approver_cascade
Create Date: 2026-02-02
"""

from alembic import op
import sqlalchemy as sa

revision = "020_approver_priority_exclude"
down_revision = "019_approver_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leave_approver_assignments",
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
    )
    op.add_column(
        "leave_approver_assignments",
        sa.Column("exclude", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("leave_approver_assignments", "exclude")
    op.drop_column("leave_approver_assignments", "priority")
