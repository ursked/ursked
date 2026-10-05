"""Plugins and licensing: plugin settings, the plugin event outbox, and the
install's licence

Revision ID: 069_plugins_and_licence
Revises: 068_operational_portals
Create Date: 2026-10-05

The owner's decisions (2026-10-05, ops/PLUGINS_AND_LICENSING.md): official
plugins ship inside the image and stay locked until a licence key unlocks them;
the key is checked offline; every plugin is paid.

  * plugin_settings: one row per (company, plugin): on/off, plain settings,
    encrypted secrets, and the last Test result.
  * plugin_event_outbox: events written in the same transaction as the change
    they report and delivered afterwards by the scheduler, so a plugin never
    runs inside a change.
  * site_settings.install_id / licence_key / licence_state. Every existing
    install gets its install ID here, so the Licence tab can show it at once.

Downgrade drops the two tables and the three columns. An applied licence key
is lost with them; it can be pasted again after upgrading.
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "069_plugins_and_licence"
down_revision = "068_operational_portals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("site_settings", sa.Column("install_id", sa.String(36), nullable=True))
    op.add_column("site_settings", sa.Column("licence_key", sa.Text(), nullable=True))
    op.add_column("site_settings", sa.Column("licence_state", postgresql.JSONB(), nullable=True))
    op.create_unique_constraint("uq_site_settings_install_id", "site_settings", ["install_id"])

    conn = op.get_bind()
    for (row_id,) in conn.execute(sa.text("SELECT id FROM site_settings WHERE install_id IS NULL")).fetchall():
        conn.execute(
            sa.text("UPDATE site_settings SET install_id = :iid WHERE id = :id"),
            {"iid": str(uuid.uuid4()), "id": row_id},
        )

    op.create_table(
        "plugin_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plugin_id", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("secrets", sa.Text(), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "plugin_id", name="uq_plugin_settings_tenant_plugin"),
    )
    op.create_index("ix_plugin_settings_tenant_id", "plugin_settings", ["tenant_id"])

    op.create_table(
        "plugin_event_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plugin_id", sa.String(64), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_plugin_event_outbox_tenant_id", "plugin_event_outbox", ["tenant_id"])
    op.create_index("ix_plugin_event_outbox_status_next", "plugin_event_outbox", ["status", "next_attempt_at"])
    op.create_index("ix_plugin_event_outbox_plugin_created", "plugin_event_outbox", ["plugin_id", "created_at"])


def downgrade() -> None:
    op.drop_table("plugin_event_outbox")
    op.drop_table("plugin_settings")
    op.drop_constraint("uq_site_settings_install_id", "site_settings", type_="unique")
    op.drop_column("site_settings", "licence_state")
    op.drop_column("site_settings", "licence_key")
    op.drop_column("site_settings", "install_id")
