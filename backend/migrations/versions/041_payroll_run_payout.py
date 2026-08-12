"""Payroll periods: optional payout_date + schedule_id for payout scheduling

Revision ID: 041_payroll_run_payout
Revises: 040_compensation_items
"""
from alembic import op
import sqlalchemy as sa

revision = "041_payroll_run_payout"
down_revision = "040_compensation_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_periods", sa.Column("payout_date", sa.Date(), nullable=True))
    op.add_column("payroll_periods", sa.Column("schedule_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payroll_periods_schedule",
        "payroll_periods",
        "payout_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_payroll_periods_payout_date", "payroll_periods", ["payout_date"])


def downgrade() -> None:
    op.drop_index("ix_payroll_periods_payout_date", table_name="payroll_periods")
    op.drop_constraint("fk_payroll_periods_schedule", "payroll_periods", type_="foreignkey")
    op.drop_column("payroll_periods", "schedule_id")
    op.drop_column("payroll_periods", "payout_date")
