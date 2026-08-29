from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class TwoFactorSettings(Base):
    __tablename__ = "two_factor_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False)
    require_2fa_all = Column(Boolean, default=False)
    require_2fa_admins = Column(Boolean, default=False)
    require_2fa_managers = Column(Boolean, default=False)
    grace_period_days = Column(Integer, default=7)
    remember_device_enabled = Column(Boolean, default=True)
    remember_device_days = Column(Integer, default=30)
    allow_totp = Column(Boolean, default=True)
    allow_sms = Column(Boolean, default=False)
    allow_email = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailSettings(Base):
    __tablename__ = "email_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False)
    mail_server = Column(String(255), nullable=True)
    mail_port = Column(Integer, default=587)
    mail_use_tls = Column(Boolean, default=True)
    mail_use_ssl = Column(Boolean, default=False)
    mail_username = Column(String(255), nullable=True)
    mail_password = Column(String(255), nullable=True)
    mail_default_sender = Column(String(255), nullable=True)
    mail_sender_name = Column(String(255), nullable=True)
    templates = Column(JSONB, nullable=True)
    is_configured = Column(Boolean, default=False)
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    last_test_result = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False)
    timezone = Column(String(100), default="UTC")
    # Tenant master currency (ISO 4217, e.g. PHP, USD). All monetary values —
    # salary grades, payroll, compensation, exports — are denominated in this.
    currency_code = Column(String(3), nullable=False, default="PHP", server_default="PHP")
    date_format = Column(String(50), default="YYYY-MM-DD")
    time_format = Column(String(50), default="HH:mm")
    week_starts_on = Column(String(20), default="monday")
    default_leave_days = Column(Integer, default=15)
    allow_negative_leave = Column(Boolean, default=False)
    require_leave_approval = Column(Boolean, default=True)
    max_consecutive_leave_days = Column(Integer, default=30)
    default_shift_duration_hours = Column(Integer, default=8)
    allow_overtime = Column(Boolean, default=True)
    max_overtime_hours_per_week = Column(Integer, default=20)
    # ── Schedule enforcement (applied at shift creation) ──
    # 0 = disabled. When set, scheduling that violates these limits is blocked
    # unless the editor explicitly forces it.
    max_consecutive_work_days = Column(Integer, default=0)
    min_rest_days_per_week = Column(Integer, default=0)
    # When true, marking a date as a holiday generates 'holiday_off' shifts for
    # employees who have nothing scheduled that day. Default false: many
    # organisations operate on holidays, and writing a row onto every employee's
    # calendar is not something to do without being asked.
    auto_create_holiday_off = Column(Boolean, default=False)
    # ── Payroll computation settings (Stage 1 payroll engine) ──
    # Used to derive daily/hourly rate from a monthly salary grade.
    working_days_per_month = Column(Integer, default=22)
    # Premium multipliers. Applied to worked hours on the relevant dates/times.
    night_diff_multiplier = Column(Float, default=1.10)
    night_shift_start = Column(Time, nullable=True)   # e.g. 22:00
    night_shift_end = Column(Time, nullable=True)     # e.g. 06:00
    holiday_worked_multiplier = Column(Float, default=2.0)
    special_holiday_worked_multiplier = Column(Float, default=1.3)
    holiday_unworked_paid = Column(Boolean, default=False)
    notify_on_leave_request = Column(Boolean, default=True)
    notify_on_leave_approval = Column(Boolean, default=True)
    notify_on_schedule_change = Column(Boolean, default=True)
    schedule_employee_visibility = Column(String(30), default="own_node")  # all, own_node, own_and_children, own_and_parent
    data_retention_days = Column(Integer, nullable=True)  # null = keep forever, number = auto-delete after N days
    analytics_exclusion_days = Column(Integer, default=0)  # days after separation to still include in analytics
    custom_settings = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class ShiftStatusType(Base):
    __tablename__ = "shift_status_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_status_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    short_label = Column(String(10), nullable=False)
    color = Column(String(20), nullable=False)
    bg_class = Column(String(100), nullable=False)
    category = Column(String(20), nullable=False, default="leave")
    is_system = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    preferences = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
