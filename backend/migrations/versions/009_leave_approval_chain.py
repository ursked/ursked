"""Add leave_approver_assignments table and approval chain columns to leave_policies.

Revision ID: 009_leave_approval_chain
Revises: 008_leave_policies_overtime
Create Date: 2026-01-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "009_leave_approval_chain"
down_revision = "008_leave_policies_overtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── leave_approver_assignments ────────────────────────────────────
    op.create_table(
        "leave_approver_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("org_node_id", sa.Integer(), sa.ForeignKey("org_nodes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Add approval columns to leave_policies ────────────────────────
    op.add_column(
        "leave_policies",
        sa.Column("approval_mode", sa.String(20), nullable=False, server_default="auto"),
    )
    op.add_column(
        "leave_policies",
        sa.Column("required_approval_levels", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("leave_policies", "required_approval_levels")
    op.drop_column("leave_policies", "approval_mode")
    op.drop_table("leave_approver_assignments")
