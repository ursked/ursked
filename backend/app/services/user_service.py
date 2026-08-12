from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.middleware.auth import get_password_hash
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.role_service import RoleService


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
        send_invite = data.pop("send_invite", True)
        data.pop("role_codes", None)

        # If no password provided (invite flow), generate a placeholder
        if not password:
            password = InviteService.generate_placeholder_password()

        user = User(
            tenant_id=tenant_id,
            password_hash=get_password_hash(password),
            must_change_password=send_invite,
            **data,
        )
        db.add(user)
        await db.flush()

        # Assign roles
        codes = role_codes or ["employee"]
        if "employee" not in codes:
            codes.insert(0, "employee")
        await RoleService.assign_roles(db, user.id, codes, tenant_id, assigned_by=assigned_by)

        # Reload with roles
        stmt = (
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.id == user.id)
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
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str, tenant_id: UUID) -> Optional[User]:
        stmt = select(User).where(User.email == email, User.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_username(db: AsyncSession, username: str, tenant_id: UUID) -> Optional[User]:
        stmt = select(User).where(User.username == username, User.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

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
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        separation_type: Optional[str] = None,
        department_id: Optional[int] = None,
        section_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        sort_by: Optional[str] = None,
        order: str = "asc",
    ) -> dict:
        stmt = select(User).options(
            selectinload(User.user_roles).selectinload(UserRole.role)
        ).where(User.tenant_id == tenant_id)
        count_stmt = select(func.count(User.id)).where(User.tenant_id == tenant_id)

        if search:
            search_filter = (
                User.first_name.ilike(f"%{search}%")
                | User.last_name.ilike(f"%{search}%")
                | User.email.ilike(f"%{search}%")
                | User.username.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        if role:
            # Filter by role code via junction table
            stmt = stmt.where(
                User.id.in_(
                    select(UserRole.user_id)
                    .join(Role)
                    .where(Role.code == role, Role.tenant_id == tenant_id)
                )
            )
            count_stmt = count_stmt.where(
                User.id.in_(
                    select(UserRole.user_id)
                    .join(Role)
                    .where(Role.code == role, Role.tenant_id == tenant_id)
                )
            )

        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)
            count_stmt = count_stmt.where(User.is_active == is_active)

        if separation_type:
            stmt = stmt.where(User.separation_type == separation_type)
            count_stmt = count_stmt.where(User.separation_type == separation_type)

        if department_id:
            stmt = stmt.where(User.department_id == department_id)
            count_stmt = count_stmt.where(User.department_id == department_id)

        if section_id:
            stmt = stmt.where(User.section_id == section_id)
            count_stmt = count_stmt.where(User.section_id == section_id)

        if unit_id:
            stmt = stmt.where(User.unit_id == unit_id)
            count_stmt = count_stmt.where(User.unit_id == unit_id)

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
    async def update_user(db: AsyncSession, user: User, data: dict) -> User:
        for key, value in data.items():
            if value is not None and hasattr(user, key):
                setattr(user, key, value)
        await db.flush()
        await db.refresh(user)
        return user

    @staticmethod
    async def bulk_create_users(db: AsyncSession, tenant_id: UUID, users_data: List[dict]) -> dict:
        created = []
        errors = []

        for i, data in enumerate(users_data):
            try:
                role_codes = data.pop("role_codes", ["employee"])
                user = await UserService.create_user(db, tenant_id, data, role_codes=role_codes)
                created.append(user)
            except Exception as e:
                errors.append(f"Row {i + 1}: {str(e)}")

        return {
            "success_count": len(created),
            "error_count": len(errors),
            "errors": errors,
            "created_users": created,
        }
