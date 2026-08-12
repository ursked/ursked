from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Notification(Base):
    """A minimal in-app notification for a single recipient. Columns are generic so
    this can grow into a general feed, but for now it backs the salary-enrollment
    approval flow. An 'actionable' notification carries action_type + action_ref_id
    so the UI can render inline Approve/Decline against a referenced object."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(40), nullable=False)  # e.g. salary_enrollment_request
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    action_type = Column(String(40), nullable=True)  # e.g. approve_salary_request
    action_ref_id = Column(Integer, nullable=True)  # e.g. request id
    is_read = Column(Boolean, nullable=False, default=False)
    is_actioned = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])
