from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.timeutil import utcnow


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "date", "sequence_number", name="uq_tenant_employee_date_seq"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    sequence_number = Column(Integer, default=1)
    status = Column(String(50), nullable=False, default="scheduled")
    work_arrangement = Column(String(50), nullable=True)
    role_id = Column(Integer, nullable=True)
    role_name = Column(String(100), nullable=True)
    color = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)
    remarks = Column(Text, nullable=True)
    original_status = Column(String(50), nullable=True)
    original_start_time = Column(Time, nullable=True)
    original_end_time = Column(Time, nullable=True)
    leave_application_id = Column(Integer, ForeignKey("leave_applications.id", ondelete="SET NULL"), nullable=True)
    # Draft/publish: new shifts start unpublished (draft) and are hidden from
    # employees until an editor publishes the range. Existing shifts were
    # backfilled to published=True by migration 044.
    is_published = Column(Boolean, nullable=False, default=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Where the employee is expected to be. The column has existed since
    # migration 057 (the time clock geofence reads it) but was never mapped, so
    # nothing could set it.
    work_site_id = Column(Integer, ForeignKey("work_sites.id", ondelete="SET NULL"), nullable=True)
    # Publish state before a leave overlay published this shift, so reverting
    # the leave puts back a draft as a draft. NULL = not overlaid / unknown.
    original_is_published = Column(Boolean, nullable=True)
    # Provenance of an automatic 'holiday_off' shift: the holiday that
    # generated it. Cleared the moment anyone edits the shift, so "generated
    # and still untouched" is exactly `holiday_remark_id IS NOT NULL`, and
    # editing or deleting the holiday removes only those.
    holiday_remark_id = Column(Integer, ForeignKey("date_remarks.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="shifts")
    employee = relationship("User", foreign_keys=[employee_id])
    leave_application = relationship("LeaveApplication", foreign_keys=[leave_application_id])
    creator = relationship("User", foreign_keys=[created_by])


class DateRemark(Base):
    __tablename__ = "date_remarks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_holiday = Column(Boolean, default=False)
    is_special = Column(Boolean, default=False)
    is_recurring = Column(Boolean, default=False)
    # ── Live holiday feed (holiday_sync_service) ──
    # 'manual' rows are the admin's; 'feed' rows came from the tenant's
    # holiday source and are kept up to date by sync unless edited locally.
    source = Column(String(20), nullable=False, default="manual", server_default="manual")
    # The feed's event UID(s), space-separated when two feed holidays share a
    # date (one row per date is enforced by uq_date_remark_tenant_date).
    external_uid = Column(Text, nullable=True)
    # The feed said "Date to be confirmed" (e.g. Eid, which follows the moon).
    is_tentative = Column(Boolean, nullable=False, default=False, server_default="false")
    # ISO 3166-2 subdivision code for a regional holiday (e.g. PH-CEB), else NULL.
    region = Column(String(100), nullable=True)
    # The feed did not say whether this is a regular or special holiday; it was
    # saved as regular and someone should confirm.
    needs_review = Column(Boolean, nullable=False, default=False, server_default="false")
    # An admin edited a feed holiday; sync never overwrites it again.
    locally_modified = Column(Boolean, nullable=False, default=False, server_default="false")
    # Tombstone: an admin deleted a feed holiday. The row stays (with
    # is_holiday false, so nothing treats it as a holiday) so the next sync
    # does not add it back.
    is_suppressed = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class HolidaySource(Base):
    """Where a tenant's public holidays come from, and how the last sync went.

    One row per tenant. provider 'officeholidays' reads the free per-country
    iCal feed at https://www.officeholidays.com/ics/<country_slug>;
    'ics_url' reads any https iCal URL the admin supplies.
    """
    __tablename__ = "holiday_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True)
    provider = Column(String(30), nullable=False, default="officeholidays")
    country_slug = Column(String(100), nullable=True)
    feed_url = Column(Text, nullable=True)
    # Regional holidays are only imported for these subdivision codes.
    include_regions = Column(JSON, nullable=False, default=list)
    auto_sync = Column(Boolean, nullable=False, default=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    # Last try, successful or not: a failing feed is retried hourly, not on
    # every scheduler tick.
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(20), nullable=True)  # ok | error
    last_error = Column(Text, nullable=True)
    last_counts = Column(JSON, nullable=True)  # {added, changed, removed, needs_review, skipped}
    # Regions seen in the feed at the last fetch: [{code, label, count, samples}].
    discovered_regions = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ScheduleChangeRequest(Base):
    __tablename__ = "schedule_change_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    request_type = Column(String(20), nullable=False)  # 'swap' or 'change'
    requester_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    target_employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    # Snapshot of requester's current shift
    original_start_time = Column(Time, nullable=True)
    original_end_time = Column(Time, nullable=True)
    original_status = Column(String(50), nullable=True)

    # Snapshot of target's current shift (swap only)
    target_original_start_time = Column(Time, nullable=True)
    target_original_end_time = Column(Time, nullable=True)
    target_original_status = Column(String(50), nullable=True)

    # Requested new values (change only)
    requested_start_time = Column(Time, nullable=True)
    requested_end_time = Column(Time, nullable=True)
    requested_status = Column(String(50), nullable=True)
    requested_work_arrangement = Column(String(50), nullable=True)

    reason = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tenant = relationship("Tenant", back_populates="schedule_change_requests")
    requester = relationship("User", foreign_keys=[requester_id])
    target_employee = relationship("User", foreign_keys=[target_employee_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    approval_steps = relationship(
        "ScheduleChangeApprovalStep",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="ScheduleChangeApprovalStep.step_order",
    )


class ScheduleChangeApprovalStep(Base):
    __tablename__ = "schedule_change_approval_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("schedule_change_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    step_order = Column(Integer, nullable=False)
    step_type = Column(String(30), nullable=False, default="manager_approval")  # 'peer_approval' or 'manager_approval'
    status = Column(String(20), nullable=False, default="pending")
    decided_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    request = relationship("ScheduleChangeRequest", back_populates="approval_steps")
    approver = relationship("User", foreign_keys=[approver_id])


class ScheduleTemplate(Base):
    __tablename__ = "schedule_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    template_data = Column(JSONB, nullable=False)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ScheduleSnapshot(Base):
    __tablename__ = "schedule_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    source_start_date = Column(Date, nullable=False)
    source_end_date = Column(Date, nullable=False)
    range_type = Column(String(20), nullable=False, default="week")  # week, biweekly, month, custom
    snapshot_data = Column(JSONB, nullable=False)  # [{employee_id, employee_name, shifts: [{day_offset, status, start_time, ...}]}]
    employee_count = Column(Integer, default=0)
    shift_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    creator = relationship("User", foreign_keys=[created_by])
