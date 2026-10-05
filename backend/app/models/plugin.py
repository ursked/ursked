from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base
from app.utils.timeutil import utcnow


class PluginSetting(Base):
    """One company's configuration of one plugin (ops/PLUGINS_AND_LICENSING.md 2.3).

    `config` holds the plain settings the manifest declares. `secrets` holds the
    secret ones as a JSON object encrypted with services/crypto, and is only
    decrypted where the plugin actually runs (delivery and the Test button), and
    only while the plugin is licensed: that is one of the places the licence is
    checked (3.5). The API never returns a secret, only whether it is set.
    """

    __tablename__ = "plugin_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "plugin_id", name="uq_plugin_settings_tenant_plugin"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    plugin_id = Column(String(64), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    config = Column(JSONB, nullable=False, default=dict)
    secrets = Column(Text, nullable=True)
    last_test_at = Column(DateTime(timezone=True), nullable=True)
    last_test_ok = Column(Boolean, nullable=True)
    last_test_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PluginEventOutbox(Base):
    """An event waiting to be delivered to one plugin, written in the same
    transaction as the change it reports (ops/PLUGINS_AND_LICENSING.md 2.2).

    If the change rolls back, so does the row; if it commits, the scheduler
    delivers it, retrying with backoff. A plugin therefore never runs inside a
    change and can never slow it down, veto it or half-apply it. Finished rows
    are removed by the daily cleanup after PLUGIN_EVENT_RETENTION.
    """

    __tablename__ = "plugin_event_outbox"
    __table_args__ = (
        Index("ix_plugin_event_outbox_status_next", "status", "next_attempt_at"),
        Index("ix_plugin_event_outbox_plugin_created", "plugin_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    plugin_id = Column(String(64), nullable=False)
    event = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    # queued -> sent | failed (gave up after MAX_ATTEMPTS) | skipped (plugin
    # disabled or no longer licensed by the time it was due)
    status = Column(String(20), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
