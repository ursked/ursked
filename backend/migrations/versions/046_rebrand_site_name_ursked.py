"""Rebrand default site_name SchedulePro -> ursked

Revision ID: 046_rebrand_site_name_ursked
Revises: 045_tenant_currency

The product is named ursked, but site_settings.site_name shipped with a
"SchedulePro" server default (migration 007) and any install created before this
still carries it. This migration:

- moves the column server_default to 'ursked' for new rows, and
- rebrands existing rows still holding the literal default 'SchedulePro'.

Rows an admin has already customised (any other value) are left untouched.
"""
from alembic import op
import sqlalchemy as sa

revision = "046_rebrand_site_name_ursked"
down_revision = "045_tenant_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New rows default to 'ursked'.
    op.alter_column(
        "site_settings",
        "site_name",
        existing_type=sa.String(length=200),
        existing_nullable=False,
        server_default="ursked",
    )
    # Rebrand only rows still on the old default; leave customised names alone.
    op.execute(
        "UPDATE site_settings SET site_name = 'ursked' "
        "WHERE site_name = 'SchedulePro'"
    )


def downgrade() -> None:
    op.alter_column(
        "site_settings",
        "site_name",
        existing_type=sa.String(length=200),
        existing_nullable=False,
        server_default="SchedulePro",
    )
    op.execute(
        "UPDATE site_settings SET site_name = 'SchedulePro' "
        "WHERE site_name = 'ursked'"
    )
