from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class SalaryGrade(Base):
    __tablename__ = "salary_grades"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_salary_grades_tenant_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    monthly_rate = Column(Float, nullable=False)
    daily_rate = Column(Float, nullable=True)
    hourly_rate = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="salary_grades")


class EmployeeSalary(Base):
    __tablename__ = "employee_salaries"
    __table_args__ = (
        UniqueConstraint("employee_id", "effective_date", name="uq_employee_salary_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    salary_grade_id = Column(Integer, ForeignKey("salary_grades.id", ondelete="RESTRICT"), nullable=False)
    effective_date = Column(Date, nullable=False)
    monthly_rate_override = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="employee_salaries")
    employee = relationship("User", foreign_keys=[employee_id], backref="salary_assignments")
    salary_grade = relationship("SalaryGrade", backref="employee_salaries")


class DeductionType(Base):
    __tablename__ = "deduction_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_deduction_types_tenant_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    calculation_type = Column(String(20), nullable=False, default="fixed")  # fixed / percentage / tiered
    # What the percentage/tiered calculation applies to: gross pay or base pay.
    calculation_basis = Column(String(10), nullable=False, default="gross")  # gross / base
    default_amount = Column(Float, nullable=True)
    default_rate = Column(Float, nullable=True)
    is_mandatory = Column(Boolean, default=False, nullable=False)
    is_employer_contribution = Column(Boolean, default=False, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="deduction_types")
    brackets = relationship(
        "DeductionBracket",
        back_populates="deduction_type",
        cascade="all, delete-orphan",
        order_by="DeductionBracket.over_amount",
    )


class DeductionBracket(Base):
    """A band in a tiered deduction table (used when calculation_type='tiered').

    For a basis value B falling in [over_amount, up_to_amount):
        amount = base_amount + rate * (B if rate_basis == 'full'
                                       else max(0, B - over_amount))
    This expresses flat-per-band tables (rate=0), percent-of-excess brackets,
    and full-percent-with-caps — enough for arbitrary government contribution
    and progressive-tax tables without any country hardcoding.
    """
    __tablename__ = "deduction_brackets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    deduction_type_id = Column(Integer, ForeignKey("deduction_types.id", ondelete="CASCADE"), nullable=False, index=True)
    over_amount = Column(Float, nullable=False, default=0)  # lower bound (inclusive)
    up_to_amount = Column(Float, nullable=True)  # upper bound (exclusive); null = infinity
    base_amount = Column(Float, nullable=False, default=0)
    rate = Column(Float, nullable=False, default=0)
    rate_basis = Column(String(10), nullable=False, default="excess")  # excess / full
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    deduction_type = relationship("DeductionType", back_populates="brackets")


class PayrollPeriod(Base):
    __tablename__ = "payroll_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "start_date", "end_date", name="uq_payroll_period_range"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    period_type = Column(String(20), nullable=False, default="monthly")
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    # Optional payout scheduling. When set, the run also pays every
    # CompensationItem whose payout_date == this date. Null preserves the
    # legacy range-only behavior.
    payout_date = Column(Date, nullable=True, index=True)
    schedule_id = Column(Integer, ForeignKey("payout_schedules.id", ondelete="SET NULL"), nullable=True)
    # draft / computing / computed / compute_failed / approved / finalized
    status = Column(String(20), nullable=False, default="draft")
    # Progress for backgrounded compute: {"done": n, "total": m}.
    compute_progress = Column(JSONB, nullable=True)
    computed_at = Column(DateTime(timezone=True), nullable=True)
    computed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    finalized_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="payroll_periods")
    computed_by_user = relationship("User", foreign_keys=[computed_by])
    approved_by_user = relationship("User", foreign_keys=[approved_by])
    finalized_by_user = relationship("User", foreign_keys=[finalized_by])
    items = relationship("PayrollItem", back_populates="payroll_period", cascade="all, delete-orphan")


class PayrollItem(Base):
    __tablename__ = "payroll_items"
    __table_args__ = (
        UniqueConstraint("payroll_period_id", "employee_id", name="uq_payroll_item_period_emp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    payroll_period_id = Column(Integer, ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    salary_grade_id = Column(Integer, ForeignKey("salary_grades.id", ondelete="SET NULL"), nullable=True)
    base_pay = Column(Float, nullable=False, default=0)
    overtime_pay = Column(Float, nullable=False, default=0)
    gross_pay = Column(Float, nullable=False, default=0)
    total_deductions = Column(Float, nullable=False, default=0)
    total_contributions = Column(Float, nullable=False, default=0)
    net_pay = Column(Float, nullable=False, default=0)
    breakdown = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="payroll_items")
    payroll_period = relationship("PayrollPeriod", back_populates="items")
    employee = relationship("User", foreign_keys=[employee_id])
    salary_grade = relationship("SalaryGrade")
