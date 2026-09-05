from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class DataExportConfig(Base):
    __tablename__ = "data_export_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_export_config_tenant_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    data_source = Column(String(50), nullable=False)
    columns = Column(JSONB, nullable=False)
    custom_columns = Column(JSONB, nullable=False, server_default="[]")
    filters = Column(JSONB, nullable=True)
    # Kept for backward compatibility with configs saved before `sorts`; read as
    # a fallback when `sorts` is empty.
    sort_by = Column(String(100), nullable=True)
    sort_direction = Column(String(4), nullable=True)
    name_format = Column(String(50), nullable=True)

    # ── Transformation (migration 058) ───────────────────────────
    # group_by:        ["dept"]  -> collapses rows; REPLACES the output shape
    # aggregations:    [{"column":"ot","func":"sum","output_key":"ot_sum","label":"Total OT"}]
    # column_aliases:  {"employee_name": "Staff Member"}
    # column_formats:  {"date": {"kind":"date","pattern":"long"}}
    # sorts:           [{"column":"dept","direction":"asc"}, ...]
    group_by = Column(JSONB, nullable=False, server_default="[]")
    aggregations = Column(JSONB, nullable=False, server_default="[]")
    column_aliases = Column(JSONB, nullable=False, server_default="{}")
    column_formats = Column(JSONB, nullable=False, server_default="{}")
    sorts = Column(JSONB, nullable=False, server_default="[]")
    # A relative window ("last_month") re-resolves on every run, which is what
    # makes a schedule send last month's data rather than all history.
    date_preset = Column(String(30), nullable=True)
    date_from = Column(String(10), nullable=True)
    date_to = Column(String(10), nullable=True)
    output_format = Column(String(10), nullable=False, server_default="csv")
    row_limit = Column(Integer, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    scheduled_exports = relationship("ScheduledExport", back_populates="export_config", cascade="all, delete-orphan")


class ScheduledExport(Base):
    __tablename__ = "scheduled_exports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    export_config_id = Column(Integer, ForeignKey("data_export_configs.id", ondelete="CASCADE"), nullable=False)
    schedule_type = Column(String(20), nullable=False)  # daily, weekly, monthly
    schedule_day = Column(Integer, nullable=True)  # day of week (0=Mon..6=Sun) or day of month (1-31)
    schedule_time = Column(Time, nullable=False)
    recipient_emails = Column(JSONB, nullable=False, server_default="[]")
    is_active = Column(Boolean, nullable=False, server_default="true")
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_status = Column(String(20), nullable=True)  # success, failed
    last_run_error = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    export_config = relationship("DataExportConfig", back_populates="scheduled_exports")
    tenant = relationship("Tenant", backref="scheduled_exports")
