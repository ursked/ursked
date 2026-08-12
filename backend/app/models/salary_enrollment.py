from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class SalaryEnrollment(Base):
    """A per-user grant to view salary data (kind='viewer') or to approve viewer
    requests (kind='approver'). Orthogonal to role: being finance/hr/admin is not
    enough — you must have an active row here. NULL granted_by = bootstrap seed.
    Access is permanent until revoked (status flips to 'revoked')."""

    __tablename__ = "salary_enrollments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "kind", name="uq_salary_enrollment_user_kind"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # viewer | approver
    status = Column(String(20), nullable=False, default="active")  # active | revoked
    granted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    revoked_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    granter = relationship("User", foreign_keys=[granted_by])
    revoker = relationship("User", foreign_keys=[revoked_by])


class SalaryEnrollmentRequest(Base):
    """A pending workflow item: a user asking to become a salary viewer/approver.
    Must be approved by a DIFFERENT active approver (no self-approval). The token
    is a deep-link handle emailed to approvers; the actual decision is made through
    authenticated endpoints, so the token never authorizes a state change."""

    __tablename__ = "salary_enrollment_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # viewer | approver
    status = Column(String(20), nullable=False, default="pending")  # pending | approved | declined | cancelled
    reason = Column(Text, nullable=True)
    requested_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    decided_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_note = Column(Text, nullable=True)
    token = Column(String(255), unique=True, nullable=True, index=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    requester = relationship("User", foreign_keys=[requested_by])
    decider = relationship("User", foreign_keys=[decided_by])
