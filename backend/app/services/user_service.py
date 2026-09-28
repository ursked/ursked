from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.middleware.auth import get_password_hash
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.role_service import RoleService
from app.utils.timeutil import as_utc, utcnow

# Columns an employee-edit payload may set. Anything else in the dict is a
# programming error, not a user choice, so it is ignored here and rejected by
# the schema (extra="forbid") before it gets this far.
EDITABLE_COLUMNS = {
    "username", "email", "first_name", "middle_name", "last_name", "contact_number",
    "personnel_number", "typecode", "id_number", "rank", "employee_type",
    "schedule_format", "job_title", "hiring_date", "reports_to_id", "org_node_id",
}
# Required columns: an explicit null is refused by the schemas, and never
# written here even if one slips through.
NOT_NULL_COLUMNS = {"username", "email", "first_name", "last_name"}

DEFAULT_EMPLOYEE_NUMBER_LABEL = "Personnel #"


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Emails are stored lowercased on every write path. Mail servers treat
    the local part case-insensitively in practice, and two accounts differing
    only by case made login pick whichever the database returned first."""
    return email.strip().lower() if email else email


def normalize_personnel_number(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


class UserService:
    @staticmethod
    async def create_user(
        db: AsyncSession,
        tenant_id: UUID,
        data: dict,
        role_codes: Optional[List[str]] = None,
        assigned_by: Optional[int] = None,
    ) -> User:
        from app.services.invite_service import InviteService

        password = data.pop("password", None)
        data.pop("send_invite", None)
        data.pop("role_codes", None)
        data.pop("custom_fields", None)
        org_node_id = data.pop("org_node_id", None)

        # If no password provided (invite flow), generate a placeholder
        if not password:
            password = InviteService.generate_placeholder_password()

        data["email"] = normalize_email(data.get("email"))
        if "personnel_number" in data:
            data["personnel_number"] = normalize_personnel_number(data["personnel_number"])
        # New employees get the company's first active schedule format, not a
        # hard-coded "8_hour" that many companies do not have (audit E-13).
        if not data.get("schedule_format"):
            data["schedule_format"] = await UserService.default_schedule_format(db, tenant_id)

        user = User(
            tenant_id=tenant_id,
            password_hash=get_password_hash(password),
            # Always: an invitee sets their own password on activation, and an
            # administrator-chosen password is known to someone else, so the
            # employee must replace it at first sign-in.
            must_change_password=True,
            **{k: v for k, v in data.items() if k in EDITABLE_COLUMNS},
        )
        db.add(user)
        await db.flush()

        if org_node_id:
            await UserService.set_org_unit(db, user, org_node_id, assigned_by=assigned_by)

        # Assign roles
        codes = list(role_codes or ["employee"])
        if "employee" not in codes:
            codes.insert(0, "employee")
        await RoleService.assign_roles(db, user.id, codes, tenant_id, assigned_by=assigned_by)

        # Reload with roles
        stmt = (
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.id == user.id)
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        user = result.scalar_one()
        return user

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: int, tenant_id: UUID) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.id == user_id, User.tenant_id == tenant_id)
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str, tenant_id: UUID) -> Optional[User]:
        stmt = select(User).where(
            func.lower(User.email) == normalize_email(email), User.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_user_by_username(db: AsyncSession, username: str, tenant_id: UUID) -> Optional[User]:
        stmt = select(User).where(
            func.lower(User.username) == (username or "").strip().lower(), User.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_user_by_personnel_number(db: AsyncSession, number: str, tenant_id: UUID) -> Optional[User]:
        norm = (normalize_personnel_number(number) or "").lower()
        if not norm:
            return None
        stmt = select(User).where(
            User.tenant_id == tenant_id,
            func.lower(func.trim(User.personnel_number)) == norm,
        )
        return (await db.execute(stmt)).scalars().first()

    @staticmethod
    async def employee_number_label(db: AsyncSession, tenant_id: UUID) -> str:
        from app.models.settings import AppSettings

        label = (
            await db.execute(select(AppSettings.employee_number_label).where(AppSettings.tenant_id == tenant_id))
        ).scalar()
        return label or DEFAULT_EMPLOYEE_NUMBER_LABEL

    @staticmethod
    async def find_conflict(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        email: Optional[str] = None,
        username: Optional[str] = None,
        personnel_number: Optional[str] = None,
        exclude_id: Optional[int] = None,
    ) -> Optional[str]:
        """A readable sentence if any value is already used by another user in
        the tenant, else None. Case-insensitive, like the unique indexes the
        061 migration adds, so the 500 an IntegrityError used to produce
        (audit E-9) becomes a 400 that says what to fix."""
        checks = []
        if email:
            checks.append((
                func.lower(User.email) == normalize_email(email),
                f"The email address {normalize_email(email)} is already used by another employee.",
            ))
        if username:
            checks.append((
                func.lower(User.username) == username.strip().lower(),
                f"The username {username.strip()} is already taken.",
            ))
        pn = normalize_personnel_number(personnel_number)
        if pn:
            label = await UserService.employee_number_label(db, tenant_id)
            checks.append((
                func.lower(func.trim(User.personnel_number)) == pn.lower(),
                f"{label} {pn} is already assigned to another employee.",
            ))
        for clause, message in checks:
            stmt = select(User.id).where(User.tenant_id == tenant_id, clause)
            if exclude_id is not None:
                stmt = stmt.where(User.id != exclude_id)
            if (await db.execute(stmt.limit(1))).scalar() is not None:
                return message
        return None

    @staticmethod
    async def assert_no_conflict(db: AsyncSession, tenant_id: UUID, **kwargs) -> None:
        message = await UserService.find_conflict(db, tenant_id, **kwargs)
        if message:
            raise HTTPException(status_code=400, detail=message)

    # ── Schedule formats ─────────────────────────────────────────────

    @staticmethod
    async def active_schedule_formats(db: AsyncSession, tenant_id: UUID) -> List[str]:
        from app.models.configurable_types import ScheduleFormat

        rows = await db.execute(
            select(ScheduleFormat.code)
            .where(ScheduleFormat.tenant_id == tenant_id, ScheduleFormat.is_active == True)  # noqa: E712
            .order_by(ScheduleFormat.sort_order, ScheduleFormat.name)
        )
        return [r[0] for r in rows.all()]

    @staticmethod
    async def default_schedule_format(db: AsyncSession, tenant_id: UUID) -> Optional[str]:
        formats = await UserService.active_schedule_formats(db, tenant_id)
        return formats[0] if formats else None

    @staticmethod
    async def assert_valid_schedule_format(db: AsyncSession, tenant_id: UUID, code: Optional[str]) -> None:
        """Same rule as employee types: a format that matches nothing configured
        made hours silently fall back to defaults (audit E-13)."""
        if not code:
            return
        if code not in await UserService.active_schedule_formats(db, tenant_id):
            raise HTTPException(
                status_code=400,
                detail=f"Unknown schedule format '{code}'. Configure it under Schedule Formats first.",
            )

    # ── Organization ─────────────────────────────────────────────────

    @staticmethod
    async def assert_valid_org_unit(db: AsyncSession, tenant_id: UUID, node_id: Optional[int]) -> None:
        if node_id is None:
            return
        from app.models.org_hierarchy import OrgNode

        ok = (
            await db.execute(
                select(OrgNode.id).where(
                    OrgNode.id == node_id, OrgNode.tenant_id == tenant_id, OrgNode.is_active == True  # noqa: E712
                )
            )
        ).scalar()
        if ok is None:
            raise HTTPException(status_code=400, detail="That organization unit does not exist or is inactive.")

    @staticmethod
    async def set_org_unit(db: AsyncSession, user: User, node_id: Optional[int], assigned_by: Optional[int] = None) -> None:
        """Move `user` to a unit (None = no unit) the same way the Organization
        page does, so users.org_node_id and the primary membership row in
        user_org_nodes never disagree."""
        from app.services.org_service import OrgService

        if node_id == user.org_node_id:
            return
        if node_id is None:
            await OrgService.unassign_members(db, [user.id], user.tenant_id)
        else:
            await OrgService.assign_members(db, node_id, [user.id], user.tenant_id, assigned_by=assigned_by)

    @staticmethod
    async def assert_valid_reports_to(db: AsyncSession, user: Optional[User], tenant_id: UUID, manager_id: Optional[int]) -> None:
        """Line manager: must exist in the tenant, not be the employee, and not
        create a loop (A reports to B reports to A), which would make approval
        chains and org charts walk forever."""
        if manager_id is None:
            return
        manager = (
            await db.execute(select(User.id).where(User.id == manager_id, User.tenant_id == tenant_id))
        ).scalar()
        if manager is None:
            raise HTTPException(status_code=400, detail="The selected line manager does not exist.")
        if user is None:
            return
        if manager_id == user.id:
            raise HTTPException(status_code=400, detail="An employee cannot be their own line manager.")
        from app.services.hierarchy_service import HierarchyService

        if not await HierarchyService.validate_reports_to(db, user.id, manager_id, tenant_id):
            raise HTTPException(
                status_code=400,
                detail="That line manager already reports (directly or indirectly) to this employee, which would make a loop.",
            )

    SORTABLE_COLUMNS = {
        "first_name": User.first_name,
        "last_name": User.last_name,
        "email": User.email,
        "job_title": User.job_title,
        "personnel_number": User.personnel_number,
        "hiring_date": User.hiring_date,
        "created_at": User.created_at,
    }

    @staticmethod
    async def list_users(
        db: AsyncSession,
        tenant_id: UUID,
        page: int = 1,
        per_page: int = 20,
        restrict_to_ids: Optional[set] = None,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        separation_type: Optional[str] = None,
        department_id: Optional[int] = None,
        section_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        org_node_ids: Optional[List[int]] = None,
        search_field_ids: Optional[List[int]] = None,
        extra_clauses: Optional[List[Any]] = None,
        sort_by: Optional[str] = None,
        order: str = "asc",
        ids_only: bool = False,
    ) -> dict:
        from app.services import employee_field_service

        filters = [User.tenant_id == tenant_id]

        if restrict_to_ids is not None:
            # The caller's readable scope (employee_access.readable_employee_ids).
            # None means everyone; an explicit set, even of one, is a hard limit.
            filters.append(User.id.in_(sorted(restrict_to_ids)))

        if search and search.strip():
            like = f"%{search.strip().lower()}%"
            terms = [
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
                func.lower(User.first_name + " " + User.last_name).like(like),
                func.lower(User.email).like(like),
                func.lower(User.username).like(like),
                # The employee number is how HR looks people up (audit E-12).
                func.lower(func.coalesce(User.personnel_number, "")).like(like),
            ]
            if search_field_ids:
                terms.append(employee_field_service.search_clause(search_field_ids, like))
            filters.append(or_(*terms))

        if role:
            filters.append(
                User.id.in_(
                    select(UserRole.user_id)
                    .join(Role)
                    .where(Role.code == role, Role.tenant_id == tenant_id)
                )
            )
        if is_active is not None:
            filters.append(User.is_active == is_active)
        if separation_type:
            filters.append(User.separation_type == separation_type)
        if department_id:
            filters.append(User.department_id == department_id)
        if section_id:
            filters.append(User.section_id == section_id)
        if unit_id:
            filters.append(User.unit_id == unit_id)
        if org_node_ids is not None:
            filters.append(User.org_node_id.in_(org_node_ids))
        filters.extend(extra_clauses or [])

        if ids_only:
            rows = await db.execute(select(User.id).where(*filters).order_by(User.id))
            return {"ids": [r[0] for r in rows.all()]}

        stmt = select(User).options(
            selectinload(User.user_roles).selectinload(UserRole.role)
        ).where(*filters)
        count_stmt = select(func.count(User.id)).where(*filters)

        total_result = await db.execute(count_stmt)
        total = total_result.scalar()

        col = UserService.SORTABLE_COLUMNS.get(sort_by)
        if col is not None:
            stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), User.id)
        else:
            stmt = stmt.order_by(User.id)
        stmt = stmt.offset((page - 1) * per_page).limit(per_page)
        result = await db.execute(stmt)
        users = result.scalars().unique().all()

        total_pages = (total + per_page - 1) // per_page

        return {
            "items": users,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    @staticmethod
    async def update_user(db: AsyncSession, user: User, data: dict, assigned_by: Optional[int] = None) -> User:
        """Apply exactly the keys the caller sent, explicit nulls included.

        The old version skipped None, so once a contact number, job title or
        hiring date was set it could never be cleared (audit E-5). Callers pass
        model_dump(exclude_unset=True), so a key's presence means the user
        chose that value.
        """
        data = dict(data)
        if "email" in data:
            data["email"] = normalize_email(data["email"])
        if "personnel_number" in data:
            data["personnel_number"] = normalize_personnel_number(data["personnel_number"])
        if "org_node_id" in data:
            await UserService.set_org_unit(db, user, data.pop("org_node_id"), assigned_by=assigned_by)
        for key, value in data.items():
            if key not in EDITABLE_COLUMNS:
                continue
            if value is None and key in NOT_NULL_COLUMNS:
                continue
            setattr(user, key, value)
        await db.flush()
        await db.refresh(user)
        return user

    @staticmethod
    async def revoke_all_sessions(db: AsyncSession, user: User) -> int:
        """Sign the user out everywhere, now.

        tokens_valid_from is the cutoff get_current_user and /auth/refresh
        already honour, so every access and refresh token minted before this
        instant stops working, including ones on devices we never saw. The
        session rows are marked revoked and their JTIs deny-listed as well so
        the "Active sessions" list is truthful and the rejection does not wait
        for the next user lookup.
        """
        from datetime import datetime, timezone

        from app.models.user import UserSession
        from app.services.token_store import TokenDenylist

        now = datetime.now(timezone.utc)
        user.tokens_valid_from = now
        rows = (
            await db.execute(
                select(UserSession).where(
                    UserSession.user_id == user.id,
                    UserSession.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        for s in rows:
            s.revoked_at = now
            exp = int(s.expires_at.timestamp()) if s.expires_at else None
            await TokenDenylist.revoke(s.jti, exp)
        await db.flush()
        return len(rows)

    @staticmethod
    async def pending_invites(db: AsyncSession, user_ids: List[int]) -> Dict[int, bool]:
        """{user_id: expired?} for users holding an unused invite link.

        An invite is pending while the account has never been activated
        (must_change_password) and an unused activation token exists; the
        token's expiry decides whether the badge says "pending" or "expired".
        """
        from datetime import datetime

        from app.models.user import UserInviteToken

        if not user_ids:
            return {}
        rows = await db.execute(
            select(UserInviteToken.user_id, func.max(UserInviteToken.expires_at))
            .join(User, User.id == UserInviteToken.user_id)
            .where(
                UserInviteToken.user_id.in_(user_ids),
                UserInviteToken.used_at.is_(None),
                User.must_change_password == True,  # noqa: E712
            )
            .group_by(UserInviteToken.user_id)
        )
        now = utcnow()
        out = {}
        for uid, expires in rows.all():
            out[uid] = bool(expires is not None and as_utc(expires) < now)
        return out
