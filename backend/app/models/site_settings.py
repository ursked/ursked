from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class SiteSettings(Base):
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # General
    site_name = Column(String(200), nullable=False, default="SchedulePro")
    site_description = Column(Text, nullable=True)
    site_timezone = Column(String(100), nullable=False, default="UTC")
    primary_domain = Column(String(255), nullable=True)
    base_url = Column(String(255), nullable=True)
    allowed_domains = Column(Text, nullable=True)
    support_email = Column(String(255), nullable=True)
    registration_enabled = Column(Boolean, nullable=False, default=True)
    maintenance_mode = Column(Boolean, nullable=False, default=False)
    # SMTP
    smtp_active = Column(Boolean, nullable=False, default=False)
    smtp_host = Column(String(255), nullable=True)
    smtp_port = Column(Integer, nullable=False, default=587)
    smtp_use_ssl = Column(Boolean, nullable=False, default=False)
    smtp_use_tls = Column(Boolean, nullable=False, default=True)
    smtp_username = Column(String(255), nullable=True)
    smtp_password = Column(String(255), nullable=True)
    smtp_from_email = Column(String(255), nullable=True)
    smtp_from_name = Column(String(200), nullable=True)
    smtp_admin_notification_email = Column(String(255), nullable=True)
    # Database backup
    db_backup_enabled = Column(Boolean, nullable=False, default=False)
    db_backup_frequency = Column(String(50), nullable=False, default="daily")
    db_backup_time = Column(String(10), nullable=False, default="02:00")
    db_backup_retention_days = Column(Integer, nullable=False, default=30)
    db_backup_path = Column(String(500), nullable=True)
    # Application backup
    app_backup_enabled = Column(Boolean, nullable=False, default=False)
    app_backup_frequency = Column(String(50), nullable=False, default="weekly")
    app_backup_retention_days = Column(Integer, nullable=False, default=30)
    app_backup_path = Column(String(500), nullable=True)
    # Notifications
    notify_on_backup_failure = Column(Boolean, nullable=False, default=True)
    notification_email = Column(String(255), nullable=True)
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_email = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(100), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
