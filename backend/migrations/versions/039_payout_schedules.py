"""Payout schedules: tenant payroll calendar (cutoff windows -> payout dates)

Revision ID: 039_payout_schedules
Revises: 038_schedule_enforcement
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "039_payout_schedules"
down_revision = "038_schedule_enforcement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payout_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False, server_default="semi_monthly"),
        sa.Column("cutoffs", JSONB(), nullable=False, server_default="[]"),
        sa.Column("payout_day_adjust", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payout_schedules_tenant_id", "payout_schedules", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_payout_schedules_tenant_id", table_name="payout_schedules")
    op.drop_table("payout_schedules")
