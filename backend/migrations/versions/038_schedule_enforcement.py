"""Schedule enforcement settings

Revision ID: 038_schedule_enforcement
Revises: 037_export_fields

Adds tenant-level schedule guardrails applied at shift creation:
- app_settings.max_consecutive_work_days: block scheduling a run of work days
  longer than this (0 = disabled).
- app_settings.min_rest_days_per_week: require at least this many rest days in
  any rolling 7-day window (0 = disabled).
"""
from alembic import op
import sqlalchemy as sa

revision = "038_schedule_enforcement"
down_revision = "037_export_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("max_consecutive_work_days", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "app_settings",
        sa.Column("min_rest_days_per_week", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "min_rest_days_per_week")
    op.drop_column("app_settings", "max_consecutive_work_days")
