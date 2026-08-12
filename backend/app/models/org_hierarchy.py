from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class OrgLevel(Base):
    __tablename__ = "org_levels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "level_number", name="uq_tenant_level_number"),
        # No upper bound: some organizations are very deep. Tree traversal is
        # guarded by visited-set cycle detection, not a magic depth number.
        CheckConstraint("level_number >= 1", name="ck_level_number_range"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    level_number = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tenant = relationship("Tenant", back_populates="org_levels")
    nodes = relationship("OrgNode", back_populates="level")


class OrgNode(Base):
    __tablename__ = "org_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id = Column(
        Integer,
        ForeignKey("org_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    level_id = Column(
        Integer,
        ForeignKey("org_levels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    head_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deputy_head_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tenant = relationship("Tenant", back_populates="org_nodes")
    parent = relationship("OrgNode", remote_side=[id], back_populates="children")
    children = relationship(
        "OrgNode",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="OrgNode.sort_order",
    )
    level = relationship("OrgLevel", back_populates="nodes")
    head_user = relationship(
        "User", foreign_keys=[head_user_id], back_populates="headed_org_nodes"
    )
    deputy_head_user = relationship("User", foreign_keys=[deputy_head_user_id])
    members = relationship(
        "User", back_populates="org_node", foreign_keys="[User.org_node_id]"
    )
