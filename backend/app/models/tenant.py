import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    domain = Column(String(255), unique=True, nullable=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    industry = Column(String(100), nullable=True)
    company_size = Column(String(50), nullable=True)
    country = Column(String(100), nullable=True)
    timezone = Column(String(100), nullable=True)
    plan = Column(String(50), nullable=False, default="free")
    subscription_status = Column(String(50), nullable=False, default="trial")
    subscription_ends_at = Column(DateTime(timezone=True), nullable=True)
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    max_users = Column(Integer, default=10)
    max_storage_gb = Column(Integer, default=5)
    settings = Column(JSONB, nullable=True)
    branding = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    roles = relationship("Role", back_populates="tenant", cascade="all, delete-orphan")
    departments = relationship("Department", back_populates="tenant", cascade="all, delete-orphan")
    divisions = relationship("Division", back_populates="tenant", cascade="all, delete-orphan")
    sections = relationship("Section", back_populates="tenant", cascade="all, delete-orphan")
    units = relationship("Unit", back_populates="tenant", cascade="all, delete-orphan")
    shifts = relationship("Shift", back_populates="tenant", cascade="all, delete-orphan")
    leave_applications = relationship("LeaveApplication", back_populates="tenant", cascade="all, delete-orphan")
    org_levels = relationship("OrgLevel", back_populates="tenant", cascade="all, delete-orphan")
    org_nodes = relationship("OrgNode", back_populates="tenant", cascade="all, delete-orphan")
    schedule_change_requests = relationship("ScheduleChangeRequest", back_populates="tenant", cascade="all, delete-orphan")
