"""Date leave credit adjustments for year-scoped balances and expiry

Revision ID: 032_leave_adj_dating
Revises: 031_leave_enforcement
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "032_leave_adj_dating"
down_revision = "031_leave_enforcement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # effective_date: which balance year the adjustment belongs to. Backfilled
    # from created_at so current-year balances are unchanged by this migration.
    op.add_column(
        "leave_credit_adjustments",
        sa.Column("effective_date", sa.Date(), nullable=True),
    )
    op.execute(
        "UPDATE leave_credit_adjustments SET effective_date = created_at::date"
    )
    op.alter_column(
        "leave_credit_adjustments",
        "effective_date",
        nullable=False,
        server_default=sa.text("CURRENT_DATE"),
    )
    op.add_column(
        "leave_credit_adjustments",
        sa.Column("expires_on", sa.Date(), nullable=True),
    )
    op.add_column(
        "leave_credit_adjustments",
        sa.Column("meta", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_leave_adjustments_tenant_employee_effective",
        "leave_credit_adjustments",
        ["tenant_id", "employee_id", "effective_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_leave_adjustments_tenant_employee_effective",
        table_name="leave_credit_adjustments",
    )
    op.drop_column("leave_credit_adjustments", "meta")
    op.drop_column("leave_credit_adjustments", "expires_on")
    op.drop_column("leave_credit_adjustments", "effective_date")
