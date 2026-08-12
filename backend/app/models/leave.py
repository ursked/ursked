from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class LeaveApplication(Base):
    __tablename__ = "leave_applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type = Column(String(50), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    days_requested = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    supporting_documents = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    # Snapshot of non-blocking rule violations at filing time, shown to approvers.
    # [{"rule": str, "mode": "warn", "message": str, "details": {...}}, ...]
    rule_warnings = Column(JSON, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="leave_applications")
    employee = relationship("User", foreign_keys=[employee_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    approval_steps = relationship("LeaveApprovalStep", back_populates="leave_application", cascade="all, delete-orphan", order_by="LeaveApprovalStep.step_order")


class LeaveType(Base):
    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_leave_type_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    # Short code shown in the REMARKS column of formal schedule exports
    # (e.g. SL, PL, EL, AVL). Tenant-configurable so each client uses its own.
    export_code = Column(String(20), nullable=True)
    is_system = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="leave_types")
    entitlements = relationship("LeavePolicyEntitlement", back_populates="leave_type", cascade="all, delete-orphan")


class LeavePolicy(Base):
    __tablename__ = "leave_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_leave_policy_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    accrual_method = Column(String(20), nullable=False, default="annual")
    pool_type = Column(String(20), nullable=False, default="per_type")
    employment_types = Column(JSON, nullable=False, default=list)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    # Approval chain configuration
    approval_mode = Column(String(20), nullable=False, default="auto")  # auto / manual / hybrid
    required_approval_levels = Column(Integer, nullable=False, default=1)

    # Per-rule enforcement mode at filing time. Keys: insufficient_balance,
    # min_notice_days, max_consecutive_days, overlapping_application,
    # requires_documentation. Values: "block" | "warn" | "off".
    # A missing key means "off" (preserves pre-enforcement behavior).
    enforcement = Column(JSON, nullable=False, default=dict)

    # Shared pool fields (used when pool_type == "shared")
    shared_annual_credits = Column(Float, nullable=True)
    shared_carry_over_enabled = Column(Boolean, default=False)
    shared_max_carry_over_days = Column(Float, default=0)
    shared_carry_over_expiry_months = Column(Integer, default=0)
    shared_cash_convertible = Column(Boolean, default=False)
    shared_cash_conversion_rate = Column(Float, default=1.0)
    # Max consecutive days per application for shared-pool policies.
    # None = unlimited. Per-type policies use the entitlement's field.
    shared_max_consecutive_days = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="leave_policies")
    entitlements = relationship("LeavePolicyEntitlement", back_populates="policy", cascade="all, delete-orphan")


class LeavePolicyEntitlement(Base):
    __tablename__ = "leave_policy_entitlements"
    __table_args__ = (
        UniqueConstraint("policy_id", "leave_type_id", name="uq_policy_leave_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("leave_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type_id = Column(Integer, ForeignKey("leave_types.id", ondelete="CASCADE"), nullable=False, index=True)
    annual_credits = Column(Float, nullable=False, default=0)
    carry_over_enabled = Column(Boolean, default=False)
    max_carry_over_days = Column(Float, default=0)
    carry_over_expiry_months = Column(Integer, default=0)
    cash_convertible = Column(Boolean, default=False)
    cash_conversion_rate = Column(Float, default=1.0)
    requires_documentation = Column(Boolean, default=False)
    min_notice_days = Column(Integer, default=0)
    # Max consecutive days per application for this leave type. None = unlimited.
    max_consecutive_days = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    policy = relationship("LeavePolicy", back_populates="entitlements")
    leave_type = relationship("LeaveType", back_populates="entitlements")


class OvertimeCategory(Base):
    __tablename__ = "overtime_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_overtime_category_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    multiplier_rate = Column(Float, nullable=False, default=1.0)
    compensation_type = Column(String(20), nullable=False, default="paid")
    leave_credit_rate = Column(Float, nullable=True)
    leave_credit_type_id = Column(
        Integer, ForeignKey("leave_types.id", ondelete="SET NULL"), nullable=True
    )
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="overtime_categories")
    leave_credit_type = relationship("LeaveType", foreign_keys=[leave_credit_type_id])


class LeaveApproverAssignment(Base):
    __tablename__ = "leave_approver_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    org_node_id = Column(Integer, ForeignKey("org_nodes.id", ondelete="CASCADE"), nullable=True)
    approver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    approver_role = Column(String(30), nullable=True)  # node_head, node_deputy, parent_head, parent_deputy
    step_order = Column(Integer, nullable=False, default=1)
    priority = Column(Integer, nullable=False, default=100)
    cascade = Column(Boolean, default=False)
    exclude = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="leave_approver_assignments")
    employee = relationship("User", foreign_keys=[employee_id])
    org_node = relationship("OrgNode", foreign_keys=[org_node_id])
    approver = relationship("User", foreign_keys=[approver_id])
