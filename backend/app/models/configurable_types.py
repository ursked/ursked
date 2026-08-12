from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class EmployeeType(Base):
    __tablename__ = "employee_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_employee_type_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="employee_types")


class ScheduleFormat(Base):
    __tablename__ = "schedule_formats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_schedule_format_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    hours_per_day = Column(Float, nullable=True)
    hours_per_week = Column(Float, nullable=True)
    is_flexible = Column(Boolean, default=False, nullable=False)
    paid_break_minutes = Column(Integer, default=0, nullable=False)
    unpaid_break_minutes = Column(Integer, default=0, nullable=False)
    paid_break_after_hours = Column(Float, default=4.0, nullable=False)
    unpaid_break_after_hours = Column(Float, default=4.0, nullable=False)
    description = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="schedule_formats")


class UserOrgNode(Base):
    __tablename__ = "user_org_nodes"
    __table_args__ = (
        UniqueConstraint("user_id", "org_node_id", name="uq_user_org_node"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_node_id = Column(
        Integer,
        ForeignKey("org_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_primary = Column(Boolean, default=False, nullable=False)
    assigned_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    assigned_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    user = relationship("User", foreign_keys=[user_id], backref="org_node_assignments")
    org_node = relationship("OrgNode", backref="user_assignments")
    assigner = relationship("User", foreign_keys=[assigned_by])
