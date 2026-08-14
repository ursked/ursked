from datetime import date, datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_employee_attendance_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    shift_id = Column(Integer, ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True)
    date = Column(Date, nullable=False)
    actual_start_time = Column(Time, nullable=True)
    actual_end_time = Column(Time, nullable=True)
    scheduled_start_time = Column(Time, nullable=True)
    scheduled_end_time = Column(Time, nullable=True)
    hours_worked = Column(Float, nullable=True)
    tardiness_minutes = Column(Integer, nullable=False, default=0)
    overtime_minutes = Column(Integer, nullable=False, default=0)
    undertime_minutes = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="present")  # present, late, absent, half_day, excused
    notes = Column(Text, nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # True when the employee submitted their own hours (POST /attendance/my).
    # Lets admins filter self-reported entries for review before payroll.
    self_reported = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="attendance_records")
    employee = relationship("User", foreign_keys=[employee_id])
    shift = relationship("Shift", foreign_keys=[shift_id])
    recorder = relationship("User", foreign_keys=[recorded_by])
    overtime_log = relationship("OvertimeLog", back_populates="attendance_record", uselist=False)
    tardiness_record = relationship("TardinessRecord", back_populates="attendance_record", uselist=False)


class OvertimeLog(Base):
    __tablename__ = "overtime_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    attendance_record_id = Column(Integer, ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False, unique=True)
    date = Column(Date, nullable=False)
    overtime_minutes = Column(Integer, nullable=False)
    overtime_category_id = Column(Integer, ForeignKey("overtime_categories.id", ondelete="SET NULL"), nullable=True)
    log_type = Column(String(30), nullable=False, default="overtime")  # overtime, night_differential, holiday_shift
    pay_multiplier = Column(Float, nullable=True)
    pay_amount = Column(Float, nullable=True)
    leave_credits_earned = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, approved, converted, rejected
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="overtime_logs")
    employee = relationship("User", foreign_keys=[employee_id])
    attendance_record = relationship("AttendanceRecord", back_populates="overtime_log")
    overtime_category = relationship("OvertimeCategory")
    approver = relationship("User", foreign_keys=[approved_by])


class TardinessRecord(Base):
    __tablename__ = "tardiness_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    attendance_record_id = Column(Integer, ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False, unique=True)
    date = Column(Date, nullable=False)
    tardiness_minutes = Column(Integer, nullable=False)
    resolution_type = Column(String(30), nullable=True)  # salary_deduction, leave_deduction, excused, warning
    deduction_amount = Column(Float, nullable=True)
    leave_credits_deducted = Column(Float, nullable=True)
    policy_rule_id = Column(Integer, ForeignKey("policy_rules.id", ondelete="SET NULL"), nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="tardiness_records")
    employee = relationship("User", foreign_keys=[employee_id])
    attendance_record = relationship("AttendanceRecord", back_populates="tardiness_record")
    policy_rule = relationship("PolicyRule")
    recorder = relationship("User", foreign_keys=[recorded_by])


class LeaveCreditAdjustment(Base):
    __tablename__ = "leave_credit_adjustments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # ot_conversion, tardiness_deduction, manual, carry_over,
    # carry_over_expiry, cash_conversion
    adjustment_type = Column(String(30), nullable=False)
    leave_type = Column(String(50), nullable=True)
    credits = Column(Float, nullable=False)  # positive = earned, negative = deducted
    # The balance year this adjustment belongs to. Balance queries are scoped to
    # the requested year via this column, so carry-over credits written for
    # Jan 1 of year N only affect year N.
    effective_date = Column(Date, nullable=False, default=date.today, index=True)
    # For carry_over rows: date the carried credits lapse (enforced by the
    # daily expiry job). None = never expires.
    expires_on = Column(Date, nullable=True)
    # Job/context payload, e.g. {"days": 2.5, "rate": 1.0} for cash_conversion.
    meta = Column(JSONB, nullable=True)
    source_id = Column(Integer, nullable=True)
    source_type = Column(String(30), nullable=True)  # overtime_log, tardiness_record, job_run
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    tenant = relationship("Tenant", backref="leave_credit_adjustments")
    employee = relationship("User", foreign_keys=[employee_id])
    creator = relationship("User", foreign_keys=[created_by])
