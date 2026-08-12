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


class PayoutSchedule(Base):
    """A tenant's payroll calendar: how cutoff windows map to payout dates.

    ``cutoffs`` is a JSON list describing each pay run within the frequency, e.g.
    semi-monthly::

        [
          {"cutoff_start_day": 1,  "cutoff_end_day": 15, "payout_day": 20, "payout_month_offset": 0},
          {"cutoff_start_day": 16, "cutoff_end_day": 31, "payout_day": 5,  "payout_month_offset": 1}
        ]

    Work in the 1-15 window is paid on the 20th of the same month; work in the
    16-31 window is paid on the 5th of the *next* month. ``payout_month_offset``
    lets a tenant defer a run arbitrarily far (e.g. a December year-end run).
    """

    __tablename__ = "payout_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    # semi_monthly | monthly | weekly | bi_weekly
    frequency = Column(String(20), nullable=False, default="semi_monthly")
    cutoffs = Column(JSONB, nullable=False, default=list)
    # none | prev_business_day | next_business_day — how to shift a payout date
    # that lands on a weekend/holiday.
    payout_day_adjust = Column(String(20), nullable=False, default="none")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="payout_schedules")


class CompensationItem(Base):
    """Append-only ledger of variable pay lines (bonus / incentive / allowance /
    salary adjustment / leave-cash / correction).

    Never updated in place except for the pay-lifecycle status transition
    (scheduled -> paid) and void. The paid amount for any run is a SUM over rows
    whose ``payout_date`` matches the run, mirroring the credits-ledger pattern
    so figures are always reconstructible.
    """

    __tablename__ = "compensation_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # bonus | incentive | allowance | salary_adjustment | leave_cash | correction
    kind = Column(String(30), nullable=False, index=True)
    # Positive = earning, negative = clawback/correction.
    amount = Column(Float, nullable=False, default=0)
    # When the work/entitlement happened.
    earned_on = Column(Date, nullable=False, index=True)
    # Resolved from the active PayoutSchedule at creation time; the run that pays it.
    payout_date = Column(Date, nullable=False, index=True)
    # once | monthly | per_cutoff — for recurring allowances. A recurring row is a
    # *template*; materialized rows carry recurrence="once" and template_id.
    recurrence = Column(String(20), nullable=False, default="once")
    template_id = Column(Integer, ForeignKey("compensation_items.id", ondelete="SET NULL"), nullable=True)
    # pending | scheduled | paid | void
    status = Column(String(20), nullable=False, default="scheduled", index=True)
    reason = Column(Text, nullable=False)
    meta = Column(JSONB, nullable=True)
    # Traceability to the thing that generated this line (e.g. leave adjustment, OT log).
    source_type = Column(String(40), nullable=True)
    source_id = Column(Integer, nullable=True)
    # Set when swept into a finalized payroll run.
    payroll_item_id = Column(Integer, ForeignKey("payroll_items.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="compensation_items")
    employee = relationship("User", foreign_keys=[employee_id])
    creator = relationship("User", foreign_keys=[created_by])
