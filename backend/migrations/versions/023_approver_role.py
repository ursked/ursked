"""add approver_role to leave_approver_assignments

Revision ID: 023_approver_role
Revises: 022_schedule_change_requests
Create Date: 2026-02-03
"""

from alembic import op
import sqlalchemy as sa

revision = "023_approver_role"
down_revision = "022_schedule_change_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leave_approver_assignments",
        sa.Column("approver_role", sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leave_approver_assignments", "approver_role")
