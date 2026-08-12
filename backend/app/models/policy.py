from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class PolicyRule(Base):
    __tablename__ = "policy_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_policy_rule_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    rule_type = Column(String(50), nullable=False)  # overtime, tardiness, leave_conversion, attendance
    priority = Column(Integer, nullable=False, default=0)  # lower = evaluated first
    is_active = Column(Boolean, nullable=False, default=True)
    # Condition TREE. A leaf is {"field","operator","value"}; a group is
    # {"all":[...]} or {"any":[...]} and may nest. A bare list is treated as an
    # implicit "all" group (backward compatible with the old flat format).
    conditions = Column(JSONB, nullable=False, default=list)
    # Actions. Besides direct-effect actions, an action may be
    # {"type":"banded","field":...,"bands":[{"min","max","action":{...}}]} which
    # maps value ranges to different sub-actions (e.g. graduated tardiness).
    actions = Column(JSONB, nullable=False, default=list)
    employment_types = Column(JSONB, nullable=True)  # array of employee_type codes, null = all
    # Optional org-node scope: applies only to employees in these nodes (or their
    # descendants). NULL = all employees.
    scope_org_node_ids = Column(JSONB, nullable=True)
    # Optional inclusive effective-date window. NULL = open-ended.
    effective_from = Column(Date, nullable=True)
    effective_until = Column(Date, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", backref="policy_rules")
    creator = relationship("User", foreign_keys=[created_by])
