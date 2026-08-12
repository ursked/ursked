"""scheduled exports

Revision ID: 017_scheduled_exports
Revises: 016_leave_schedule_night_holiday
Create Date: 2026-02-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "017_scheduled_exports"
down_revision = "016_leave_schedule_night_holiday"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_exports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("export_config_id", sa.Integer(), sa.ForeignKey("data_export_configs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_type", sa.String(20), nullable=False),  # daily, weekly, monthly
        sa.Column("schedule_day", sa.Integer(), nullable=True),  # day of week (0-6) or day of month (1-31)
        sa.Column("schedule_time", sa.Time(), nullable=False),
        sa.Column("recipient_emails", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(20), nullable=True),
        sa.Column("last_run_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("scheduled_exports")
