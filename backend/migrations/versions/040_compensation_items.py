"""Compensation items: append-only ledger of variable pay lines

Revision ID: 040_compensation_items
Revises: 039_payout_schedules

Bonuses, incentives, allowances, salary adjustments, leave-cash and corrections.
Each row carries earned_on (when) and payout_date (which run pays it).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "040_compensation_items"
down_revision = "039_payout_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compensation_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("earned_on", sa.Date(), nullable=False),
        sa.Column("payout_date", sa.Date(), nullable=False),
        sa.Column("recurrence", sa.String(length=20), nullable=False, server_default="once"),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("compensation_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("meta", JSONB(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("payroll_item_id", sa.Integer(), sa.ForeignKey("payroll_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_compensation_items_tenant_id", "compensation_items", ["tenant_id"])
    op.create_index("ix_compensation_items_employee_id", "compensation_items", ["employee_id"])
    op.create_index("ix_compensation_items_kind", "compensation_items", ["kind"])
    op.create_index("ix_compensation_items_earned_on", "compensation_items", ["earned_on"])
    op.create_index("ix_compensation_items_payout_date", "compensation_items", ["payout_date"])
    op.create_index("ix_compensation_items_status", "compensation_items", ["status"])


def downgrade() -> None:
    for ix in (
        "ix_compensation_items_status",
        "ix_compensation_items_payout_date",
        "ix_compensation_items_earned_on",
        "ix_compensation_items_kind",
        "ix_compensation_items_employee_id",
        "ix_compensation_items_tenant_id",
    ):
        op.drop_index(ix, table_name="compensation_items")
    op.drop_table("compensation_items")
