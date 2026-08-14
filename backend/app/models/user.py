from datetime import datetime
from typing import List

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.services.crypto import EncryptedString


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_tenant_username"),
        UniqueConstraint("tenant_id", "email", name="uq_tenant_email"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(80), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    middle_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=False)
    avatar = Column(String(255), nullable=True)
    contact_number = Column(String(50), nullable=True)
    personnel_number = Column(String(50), nullable=True)
    typecode = Column(String(50), nullable=True)
    id_number = Column(String(100), nullable=True)
    hiring_date = Column(Date, nullable=True)
    job_title = Column(String(200), nullable=True)
    rank = Column(String(100), nullable=True)
    div_department = Column(String(200), nullable=True)
    signature = Column(String(255), nullable=True)
    employee_type = Column(String(50), nullable=True)
    schedule_format = Column(String(50), nullable=True, default="8_hour")
    section_id = Column(Integer, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    division_id = Column(Integer, ForeignKey("divisions.id", ondelete="SET NULL"), nullable=True)
    reports_to_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    org_node_id = Column(Integer, ForeignKey("org_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    is_superadmin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    separation_type = Column(String(20), nullable=True)  # resigned, terminated
    separation_date = Column(Date, nullable=True)
    separation_reason = Column(Text, nullable=True)
    separated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    must_change_password = Column(Boolean, default=False)
    # Global session revocation: any token issued before this instant is
    # rejected. Bumped on password change, role change and deactivation.
    # Stored on the row (not Redis) so revocation survives a cache outage.
    tokens_valid_from = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users")
    section = relationship("Section", back_populates="users")
    unit = relationship("Unit", back_populates="users")
    department = relationship("Department", back_populates="users")
    division = relationship("Division", back_populates="users")
    reports_to = relationship("User", remote_side=[id], foreign_keys=[reports_to_id], backref="direct_reports")
    org_node = relationship("OrgNode", back_populates="members", foreign_keys=[org_node_id])
    headed_org_nodes = relationship("OrgNode", back_populates="head_user", foreign_keys="[OrgNode.head_user_id]")
    two_factor = relationship("UserTwoFactor", back_populates="user", uselist=False, cascade="all, delete-orphan")
    trusted_devices = relationship("TrustedDevice", back_populates="user", cascade="all, delete-orphan")
    user_roles = relationship("UserRole", back_populates="user", foreign_keys="[UserRole.user_id]", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)

    @property
    def formal_name(self) -> str:
        """LASTNAME, FIRST MIDDLE — the all-caps surname-first format used on
        formal schedule/payroll exports (e.g. 'LLOREN, FRANCIS MICHAEL M.')."""
        given = " ".join(p for p in [self.first_name, self.middle_name] if p).upper()
        last = (self.last_name or "").upper()
        return f"{last}, {given}".strip().rstrip(",").strip()

    @property
    def role_codes(self) -> List[str]:
        """Return list of role codes for this user (requires user_roles to be loaded)."""
        return [ur.role.code for ur in self.user_roles if ur.role.is_active]

    def has_role(self, role_code: str) -> bool:
        """Check if user has a specific role."""
        return role_code in self.role_codes

    @property
    def primary_role(self) -> str:
        """Return the highest-priority role for display purposes."""
        priority = ["tenant_admin", "hr", "finance", "manager", "leave_approver", "schedule_editor", "employee"]
        codes = self.role_codes
        for p in priority:
            if p in codes:
                return p
        return "employee"


class UserTwoFactor(Base):
    __tablename__ = "user_two_factor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    status = Column(String(50), nullable=False, default="disabled")
    method = Column(String(50), nullable=False, default="totp")
    # Encrypted at rest (recoverable — pyotp needs the secret verbatim). Legacy
    # plaintext rows are read through unchanged and re-encrypted on next write.
    totp_secret = Column(EncryptedString(255), nullable=True)
    totp_verified = Column(Boolean, default=False)
    backup_codes = Column(JSON, nullable=True)
    grace_period_ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="two_factor")


class TrustedDevice(Base):
    __tablename__ = "trusted_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_token = Column(String(255), unique=True, nullable=False)
    device_name = Column(String(255), nullable=True)
    device_type = Column(String(100), nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="trusted_devices")


class UserSession(Base):
    """Persistent login record.

    Tracks active sessions so users can see where they are signed in and revoke
    individual sessions. Linked to the JWT's JTI: revoking a session adds its
    JTI to the Redis denylist AND marks `revoked_at` so it drops from the list.

    CE scope: users see their OWN sessions only.
    EE scope (not built): cross-tenant session analytics, admin-forced logout.
    """
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    login_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="sessions")


class UserInviteToken(Base):
    __tablename__ = "user_invite_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # Only the SHA-256 hash of the raw token is stored, mirroring PasswordResetToken:
    # a leaked table must not be a set of working activation links. The raw token
    # lives only in the emailed activation URL.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id], backref="invite_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Only the SHA-256 hash of the raw token is stored; a leaked table must not
    # be a set of working reset links. The raw token lives only in the email URL.
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
