"""Payroll engine: deduction brackets, premium settings, compute progress

Revision ID: 034_payroll_engine
Revises: 033_job_runs
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "034_payroll_engine"
down_revision = "033_job_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tiered deduction bracket tables (tenant-editable, no country hardcoding).
    op.create_table(
        "deduction_brackets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deduction_type_id", sa.Integer(),
                  sa.ForeignKey("deduction_types.id", ondelete="CASCADE"), nullable=False),
        sa.Column("over_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("up_to_amount", sa.Float(), nullable=True),
        sa.Column("base_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rate_basis", sa.String(length=10), nullable=False, server_default="excess"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_deduction_brackets_tenant_id", "deduction_brackets", ["tenant_id"])
    op.create_index("ix_deduction_brackets_type", "deduction_brackets", ["deduction_type_id"])

    op.add_column(
        "deduction_types",
        sa.Column("calculation_basis", sa.String(length=10), nullable=False, server_default="gross"),
    )

    # Payroll premium + rate-derivation settings on app_settings.
    op.add_column("app_settings", sa.Column("working_days_per_month", sa.Integer(), server_default="22"))
    op.add_column("app_settings", sa.Column("night_diff_multiplier", sa.Float(), server_default="1.10"))
    op.add_column("app_settings", sa.Column("night_shift_start", sa.Time(), nullable=True))
    op.add_column("app_settings", sa.Column("night_shift_end", sa.Time(), nullable=True))
    op.add_column("app_settings", sa.Column("holiday_worked_multiplier", sa.Float(), server_default="2.0"))
    op.add_column("app_settings", sa.Column("special_holiday_worked_multiplier", sa.Float(), server_default="1.3"))
    op.add_column("app_settings", sa.Column("holiday_unworked_paid", sa.Boolean(), server_default=sa.text("false")))

    # Progress payload for backgrounded payroll compute.
    op.add_column("payroll_periods", sa.Column("compute_progress", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("payroll_periods", "compute_progress")
    for col in (
        "holiday_unworked_paid",
        "special_holiday_worked_multiplier",
        "holiday_worked_multiplier",
        "night_shift_end",
        "night_shift_start",
        "night_diff_multiplier",
        "working_days_per_month",
    ):
        op.drop_column("app_settings", col)
    op.drop_column("deduction_types", "calculation_basis")
    op.drop_index("ix_deduction_brackets_type", table_name="deduction_brackets")
    op.drop_index("ix_deduction_brackets_tenant_id", table_name="deduction_brackets")
    op.drop_table("deduction_brackets")
