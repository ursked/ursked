from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.role import Role, UserRole

SYSTEM_ROLES = [
    ("employee", "Employee", "Base role assigned to every user"),
    ("tenant_admin", "Tenant Administrator", "Full tenant access, settings, and billing"),
    ("hr", "HR", "Payroll computations, onboarding, employee records access"),
    ("manager", "Manager", "Employee management for direct and indirect reports"),
    ("leave_approver", "Leave Approver", "Can approve leave applications for reports in their chain"),
    ("schedule_editor", "Schedule Editor", "Can create and edit schedules"),
    ("finance", "Finance", "Payroll management, salary grades, deductions, and payroll processing"),
]


class RoleService:
    @staticmethod
    async def seed_system_roles(db: AsyncSession, tenant_id: UUID) -> List[Role]:
        """Idempotently seed system roles for a tenant. Returns all system roles."""
        roles = []
        for code, name, desc in SYSTEM_ROLES:
            stmt = select(Role).where(Role.tenant_id == tenant_id, Role.code == code)
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                roles.append(existing)
            else:
                role = Role(
                    tenant_id=tenant_id,
                    code=code,
                    name=name,
                    description=desc,
                    is_system=True,
                )
                db.add(role)
                await db.flush()
                roles.append(role)

        # Seed default permissions for all system roles
        from app.services.permission_service import PermissionService
        await PermissionService.seed_default_permissions(db, tenant_id)

        return roles

    @staticmethod
    async def get_role_by_code(db: AsyncSession, tenant_id: UUID, code: str) -> Optional[Role]:
        stmt = select(Role).where(Role.tenant_id == tenant_id, Role.code == code)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def assign_role(
        db: AsyncSession,
        user_id: int,
        role_code: str,
        tenant_id: UUID,
        title: Optional[str] = None,
        assigned_by: Optional[int] = None,
    ) -> UserRole:
        """Assign a role to a user. Idempotent - returns existing assignment if already assigned."""
        role = await RoleService.get_role_by_code(db, tenant_id, role_code)
        if not role:
            raise ValueError(f"Role '{role_code}' not found for tenant")

        stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        user_role = UserRole(
            user_id=user_id,
            role_id=role.id,
            title=title,
            assigned_by=assigned_by,
        )
        db.add(user_role)
        await db.flush()
        return user_role

    @staticmethod
    async def assign_roles(
        db: AsyncSession,
        user_id: int,
        role_codes: List[str],
        tenant_id: UUID,
        assigned_by: Optional[int] = None,
    ) -> List[UserRole]:
        """Assign multiple roles to a user."""
        user_roles = []
        for code in role_codes:
            ur = await RoleService.assign_role(db, user_id, code, tenant_id, assigned_by=assigned_by)
            user_roles.append(ur)
        return user_roles

    @staticmethod
    async def remove_role(
        db: AsyncSession,
        user_id: int,
        role_code: str,
        tenant_id: UUID,
    ) -> bool:
        """Remove a role from a user. Cannot remove 'employee' role."""
        if role_code == "employee":
            raise ValueError("Cannot remove the base 'employee' role")

        role = await RoleService.get_role_by_code(db, tenant_id, role_code)
        if not role:
            return False

        stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
        result = await db.execute(stmt)
        user_role = result.scalar_one_or_none()
        if not user_role:
            return False

        await db.delete(user_role)
        await db.flush()
        return True

    @staticmethod
    async def get_user_roles(db: AsyncSession, user_id: int) -> List[UserRole]:
        stmt = (
            select(UserRole)
            .join(Role)
            .where(UserRole.user_id == user_id)
            .order_by(Role.code)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_tenant_roles(db: AsyncSession, tenant_id: UUID) -> List[Role]:
        stmt = select(Role).where(Role.tenant_id == tenant_id, Role.is_active == True).order_by(Role.code)
        result = await db.execute(stmt)
        return list(result.scalars().all())
