"""Country-neutral defaults: the organisation's country, USD as the fallback
currency

Revision ID: 070_country_neutral_defaults
Revises: 069_plugins_and_licence
Create Date: 2026-10-06

ursked is used worldwide. A new install used to start in pesos with Philippine
holiday and night premiums; it now starts in USD with no premiums and no
country, and the admin picks the country (which suggests the currency and the
holiday calendar).

  * app_settings.country_code (ISO 3166-1 alpha-2), empty until chosen.
  * app_settings.currency_code server default PHP -> USD. Existing rows keep
    the currency they already have.

The premium multipliers have only Python-side defaults, so nothing changes in
the database for them, and existing installs keep the rates they saved.
"""

import sqlalchemy as sa
from alembic import op

revision = "070_country_neutral_defaults"
down_revision = "069_plugins_and_licence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.alter_column("app_settings", "currency_code", server_default="USD")


def downgrade() -> None:
    op.alter_column("app_settings", "currency_code", server_default="PHP")
    op.drop_column("app_settings", "country_code")
