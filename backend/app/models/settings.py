from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base
from app.utils.timeutil import utcnow


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
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False)
    timezone = Column(String(100), default="UTC")
    # The organisation's country (ISO 3166-1 alpha-2), chosen by the admin.
    # Nothing is assumed until it is set: it only suggests the currency and the
    # public-holiday calendar, and the admin confirms each.
    country_code = Column(String(2), nullable=True)
    # Tenant master currency (ISO 4217, e.g. USD, EUR). All monetary values —
    # salary grades, payroll, compensation, exports — are denominated in this.
    currency_code = Column(String(3), nullable=False, default="USD", server_default="USD")
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
    # 1.0 means no premium: premiums depend on the country and the company, so
    # a new install pays none until finance sets them (Finances -> Pay rules).
    night_diff_multiplier = Column(Float, default=1.0)
    night_shift_start = Column(Time, nullable=True)   # e.g. 22:00
    night_shift_end = Column(Time, nullable=True)     # e.g. 06:00
    holiday_worked_multiplier = Column(Float, default=1.0)
    special_holiday_worked_multiplier = Column(Float, default=1.0)
    holiday_unworked_paid = Column(Boolean, default=False)
    notify_on_leave_request = Column(Boolean, default=True)
    notify_on_leave_approval = Column(Boolean, default=True)
    notify_on_schedule_change = Column(Boolean, default=True)
    schedule_employee_visibility = Column(String(30), default="own_node")  # all, own_node, own_and_children, own_and_parent
    data_retention_days = Column(Integer, nullable=True)  # null = keep forever, number = auto-delete after N days
    analytics_exclusion_days = Column(Integer, default=0)  # days after separation to still include in analytics

    # ── Time clock ────────────────────────────────────────────────────────────
    # Off by default: an existing install must not sprout a clock-in button on
    # upgrade, and location capture is something an operator opts into knowingly.
    timeclock_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    # Ask the browser for coordinates on each punch. A punch is NEVER blocked by
    # the answer; this only controls whether we ask and how we flag the result.
    timeclock_require_location = Column(Boolean, nullable=False, default=True, server_default="true")
    # How long after a punch an employee may still attach a location they could
    # not provide at the time. 0 disables recapture entirely.
    timeclock_location_grace_minutes = Column(Integer, nullable=False, default=60, server_default="60")
    # Fallback radius for a site that does not set its own.
    timeclock_default_radius_m = Column(Integer, nullable=False, default=200, server_default="200")

    # ── Area S: working-hour rules (migration 062) ────────────────────────────
    # Checked by the one shift validator on every write path (create, edit,
    # drag, bulk, copy, templates, snapshots, change requests), as warnings an
    # editor may override like the consecutive-days rule. 0 / false = off, so
    # nothing changes until an admin sets them.
    max_work_hours_per_day = Column(Float, nullable=False, default=0, server_default="0")
    max_work_hours_per_week = Column(Float, nullable=False, default=0, server_default="0")
    # Between the end of one working day's last shift and the start of the
    # next day's first, overnight shifts included. Segments of the same day
    # (a split shift) are not "rest".
    min_rest_hours_between_shifts = Column(Float, nullable=False, default=0, server_default="0")
    check_overlapping_shifts = Column(Boolean, nullable=False, default=False, server_default="false")

    custom_settings = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # ── Area E (employees): what this company calls Personnel # (e.g. "Badge
    # no."). NULL = the default wording. Set from Employees > Custom fields.
    employee_number_label = Column(String(50), nullable=True)

    # ── Area L: leave day counting and approval reminders (migration 063) ──
    # The company's normal working days, 0 = Monday ... 6 = Sunday. Leave only
    # falls back to this for days with nothing on the roster; a rostered work
    # shift always counts and a rostered rest day never does.
    work_week_days = Column(JSONB, nullable=False, default=lambda: [0, 1, 2, 3, 4], server_default="[0, 1, 2, 3, 4]")
    # Remind the current approver once a day after a step has waited this long.
    leave_reminder_after_days = Column(Integer, nullable=False, default=2, server_default="2")
    # Hand a step to the approver's fallback after this many days. 0 = never.
    leave_escalate_after_days = Column(Integer, nullable=False, default=5, server_default="5")

    # ── Area F: attendance automation (migration 064) ──
    # An open clock-in is closed, at the scheduled end of its shift, once this
    # many hours have passed since that end. A forgotten clock-out used to block
    # the next day's clock-in and then close yesterday with a 24-hour day.
    auto_clockout_after_hours = Column(Float, nullable=False, default=4, server_default="4")
    # Same, for a clock-in with no published shift to end it: closed this many
    # hours after the clock-in.
    auto_clockout_unscheduled_hours = Column(Float, nullable=False, default=16, server_default="16")
    # Mark a published work shift that passed with no clock-in and no approved
    # leave or holiday as absent, this many minutes after it was due to start.
    auto_mark_absent = Column(Boolean, nullable=False, default=True, server_default="true")
    auto_absent_after_minutes = Column(Integer, nullable=False, default=120, server_default="120")

    # ── Area A: housekeeping windows (migration 065) ──
    # The daily housekeeping job (services/housekeeping_service.py) deletes
    # these once they are older than the window. Nothing was ever pruned
    # before. Business records (shifts, leave, payroll) are never deleted.
    audit_log_retention_days = Column(Integer, nullable=False, default=730, server_default="730")
    login_history_retention_days = Column(Integer, nullable=False, default=180, server_default="180")
    read_notification_retention_days = Column(Integer, nullable=False, default=90, server_default="90")


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
    created_at = Column(DateTime(timezone=True), default=utcnow)


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    preferences = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
