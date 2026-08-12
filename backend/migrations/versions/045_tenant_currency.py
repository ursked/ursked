"""Tenant master currency

Revision ID: 045_tenant_currency
Revises: 044_shift_publish

Adds a tenant-level master currency to app_settings so all monetary values
(salary grades, payroll, compensation, exports) are denominated in one place:
- currency_code VARCHAR(3) NOT NULL DEFAULT 'PHP' — ISO 4217 code.

Backfill: the server_default 'PHP' applies to every existing row, preserving
the previous hardcoded Philippine-peso behaviour with no visible change.
"""
from alembic import op
import sqlalchemy as sa

revision = "045_tenant_currency"
down_revision = "044_shift_publish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "currency_code",
            sa.String(length=3),
            nullable=False,
            server_default="PHP",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "currency_code")
