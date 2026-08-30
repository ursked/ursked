"""Work sites and the geofence expectation attached to a work arrangement.

A punch's location only means something in context. Being 40km from the office is
unremarkable for someone rostered to work from home and a problem for someone
rostered on site, so the expectation is derived from the shift's work_arrangement
rather than applied globally.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class WorkSite(Base):
    """A place an employee can be expected to be, plus how close counts as there.

    Coordinates are plain floats and distance is computed with a haversine in
    Python. PostGIS would be more precise over long distances, but a required
    Postgres extension is a real support burden for a self-hosted install, and the
    error at geofence range (hundreds of metres) is far below GPS noise.
    """

    __tablename__ = "work_sites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tenant_work_site_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = Column(String(200), nullable=False)
    code = Column(String(50), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # How far from the point still counts as "at" the site. Deliberately generous
    # by default: a phone indoors routinely reports a position 100-200m out.
    radius_m = Column(Integer, nullable=False, default=200)
    address = Column(Text, nullable=True)
    org_node_id = Column(
        Integer, ForeignKey("org_nodes.id", ondelete="SET NULL"), nullable=True,
    )
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkArrangementRule(Base):
    """What a given work_arrangement code expects of a punch's location.

    `shifts.work_arrangement` is an unvalidated String(50) and always has been, so
    real data contains whatever anyone wrote. Rather than retrofit an enum onto
    live rows that payroll depends on, arrangements are matched here by normalised
    code and anything unrecognised FAILS OPEN to `any_location`. A typo must never
    turn into a false "outside the geofence" on someone's timesheet.
    """

    __tablename__ = "work_arrangement_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tenant_arrangement_code"),
    )

    # require_site : must be within radius of a site, else flagged (never blocked)
    # any_location : capture coordinates, never evaluate them (WFH, official business)
    # record_only  : capture if offered, no expectation either way
    GEOFENCE_MODES = ("require_site", "any_location", "record_only")

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code = Column(String(50), nullable=False)
    label = Column(String(100), nullable=False)
    geofence_mode = Column(String(20), nullable=False, default="any_location")
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
