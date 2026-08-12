"""add cascade column to leave_approver_assignments

Revision ID: 019_approver_cascade
Revises: 018_user_invite_tokens
Create Date: 2026-02-02
"""

from alembic import op
import sqlalchemy as sa

revision = "019_approver_cascade"
down_revision = "018_user_invite_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leave_approver_assignments",
        sa.Column("cascade", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("leave_approver_assignments", "cascade")
