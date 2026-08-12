"""Schedule snapshots table

Revision ID: 025_schedule_snapshots
Revises: 024_overtime_leave_credit_type
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "025_schedule_snapshots"
down_revision = "024_overtime_leave_credit_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_start_date", sa.Date(), nullable=False),
        sa.Column("source_end_date", sa.Date(), nullable=False),
        sa.Column("range_type", sa.String(20), nullable=False, server_default="week"),
        sa.Column("snapshot_data", JSONB(), nullable=False),
        sa.Column("employee_count", sa.Integer(), server_default="0"),
        sa.Column("shift_count", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("schedule_snapshots")
