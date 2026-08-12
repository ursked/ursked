"""Leave rule enforcement config and application rule warnings

Revision ID: 031_leave_enforcement
Revises: 030_session_revocation_and_indexes
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "031_leave_enforcement"
down_revision = "030_session_revocation_and_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-rule enforcement mode: {rule: "block"|"warn"|"off"}. Missing key = off,
    # so existing policies keep their current (unenforced) behavior.
    op.add_column(
        "leave_policies",
        sa.Column("enforcement", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "leave_policies",
        sa.Column("shared_max_consecutive_days", sa.Float(), nullable=True),
    )
    op.add_column(
        "leave_policy_entitlements",
        sa.Column("max_consecutive_days", sa.Float(), nullable=True),
    )
    # Snapshot of warn-mode violations at filing time, surfaced to approvers.
    op.add_column(
        "leave_applications",
        sa.Column("rule_warnings", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leave_applications", "rule_warnings")
    op.drop_column("leave_policy_entitlements", "max_consecutive_days")
    op.drop_column("leave_policies", "shared_max_consecutive_days")
    op.drop_column("leave_policies", "enforcement")
