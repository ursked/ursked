from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.permission import RolePermission
from app.models.role import Role

VALID_MODULES = [
    "employees",
    "organization",
    "schedules",
    "leave",
    "finances",
    "settings",
    "reports",
]

# Default permission matrix: role_code -> {module: (can_view, can_create, can_edit, can_delete, extra)}
DEFAULT_PERMISSIONS = {
    "tenant_admin": {
        "employees": (True, True, True, True, {"view_salary": True}),
        "organization": (True, True, True, True, {}),
        "schedules": (True, True, True, True, {}),
        "leave": (True, True, True, True, {}),
        "finances": (True, True, True, True, {}),
        "settings": (True, True, True, True, {}),
        "reports": (True, True, True, True, {}),
    },
    "hr": {
        "employees": (True, True, True, False, {"view_salary": True}),
        "organization": (True, True, True, False, {}),
        "schedules": (True, False, False, False, {}),
        "leave": (True, True, True, False, {}),
        "finances": (True, False, False, False, {}),
        "settings": (True, False, False, False, {}),
        "reports": (True, True, True, False, {}),
    },
    "finance": {
        "employees": (True, False, False, False, {"view_salary": True}),
        "organization": (True, False, False, False, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (True, True, True, True, {}),
        "settings": (True, False, False, False, {}),
        "reports": (True, True, True, False, {}),
    },
    "manager": {
        "employees": (True, False, False, False, {}),
        "organization": (True, False, False, False, {}),
        "schedules": (True, False, False, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (True, False, False, False, {}),
    },
    "schedule_editor": {
        "employees": (True, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (True, True, True, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (False, False, False, False, {}),
    },
    "leave_approver": {
        "employees": (True, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (True, False, False, False, {}),
        "leave": (True, False, True, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (True, False, False, False, {}),
    },
    "employee": {
        "employees": (False, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (False, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (False, False, False, False, {}),
    },
}


class PermissionService:
    @staticmethod
    async def seed_default_permissions(db: AsyncSession, tenant_id: UUID) -> None:
        """Idempotently seed default permissions for all system roles in a tenant."""
        stmt = select(Role).where(Role.tenant_id == tenant_id, Role.is_system == True)
        result = await db.execute(stmt)
        roles = list(result.scalars().all())

        for role in roles:
            perms = DEFAULT_PERMISSIONS.get(role.code, {})
            for module, (v, c, e, d, extra) in perms.items():
                existing = await db.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.module == module,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                db.add(RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    module=module,
                    can_view=v,
                    can_create=c,
                    can_edit=e,
                    can_delete=d,
                    extra_permissions=extra or {},
                ))
        await db.flush()

    @staticmethod
    async def get_permission_matrix(db: AsyncSession, tenant_id: UUID) -> List[Dict[str, Any]]:
        """Get all roles with their module permissions for the tenant."""
        stmt = (
            select(Role)
            .where(Role.tenant_id == tenant_id, Role.is_active == True, Role.is_system == True)
            .order_by(Role.code)
        )
        result = await db.execute(stmt)
        roles = list(result.scalars().all())

        entries = []
        for role in roles:
            perm_stmt = select(RolePermission).where(RolePermission.role_id == role.id)
            perm_result = await db.execute(perm_stmt)
            perms = list(perm_result.scalars().all())

            modules = {}
            for p in perms:
                modules[p.module] = p

            entries.append({
                "role_id": role.id,
                "role_code": role.code,
                "role_name": role.name,
                "modules": modules,
            })

        return entries

    @staticmethod
    async def get_role_permissions(db: AsyncSession, role_id: int) -> List[RolePermission]:
        stmt = select(RolePermission).where(RolePermission.role_id == role_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_role_permissions(
        db: AsyncSession,
        tenant_id: UUID,
        role_id: int,
        permissions: List[Dict[str, Any]],
    ) -> List[RolePermission]:
        """Upsert permissions for a role. permissions is a list of dicts with module, can_view, etc."""
        updated = []
        for perm_data in permissions:
            module = perm_data["module"]
            if module not in VALID_MODULES:
                continue

            stmt = select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.module == module,
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.can_view = perm_data.get("can_view", existing.can_view)
                existing.can_create = perm_data.get("can_create", existing.can_create)
                existing.can_edit = perm_data.get("can_edit", existing.can_edit)
                existing.can_delete = perm_data.get("can_delete", existing.can_delete)
                if "extra_permissions" in perm_data and perm_data["extra_permissions"] is not None:
                    existing.extra_permissions = perm_data["extra_permissions"]
                updated.append(existing)
            else:
                rp = RolePermission(
                    tenant_id=tenant_id,
                    role_id=role_id,
                    module=module,
                    can_view=perm_data.get("can_view", False),
                    can_create=perm_data.get("can_create", False),
                    can_edit=perm_data.get("can_edit", False),
                    can_delete=perm_data.get("can_delete", False),
                    extra_permissions=perm_data.get("extra_permissions", {}),
                )
                db.add(rp)
                await db.flush()
                updated.append(rp)

        await db.flush()
        return updated

    @staticmethod
    async def get_user_permissions(db: AsyncSession, tenant_id: UUID, role_ids: List[int]) -> Dict[str, Any]:
        """
        Get merged permissions across all of a user's roles.
        Returns {permissions: {module: {view: bool, ...}}, extra: {view_salary: bool, ...}}
        """
        if not role_ids:
            return {"permissions": {}, "extra": {}}

        stmt = select(RolePermission).where(RolePermission.role_id.in_(role_ids))
        result = await db.execute(stmt)
        all_perms = list(result.scalars().all())

        # OR-merge across roles per module
        merged: Dict[str, Dict[str, bool]] = {}
        extra_merged: Dict[str, bool] = {}

        for p in all_perms:
            if p.module not in merged:
                merged[p.module] = {"view": False, "create": False, "edit": False, "delete": False}
            merged[p.module]["view"] = merged[p.module]["view"] or p.can_view
            merged[p.module]["create"] = merged[p.module]["create"] or p.can_create
            merged[p.module]["edit"] = merged[p.module]["edit"] or p.can_edit
            merged[p.module]["delete"] = merged[p.module]["delete"] or p.can_delete

            # Merge extra permissions
            if p.extra_permissions:
                for key, val in p.extra_permissions.items():
                    if isinstance(val, bool):
                        extra_merged[key] = extra_merged.get(key, False) or val

        return {"permissions": merged, "extra": extra_merged}

    @staticmethod
    async def check_permission(
        db: AsyncSession,
        tenant_id: UUID,
        role_ids: List[int],
        module: str,
        action: str,
    ) -> bool:
        """Check if any of the given roles has the specified module+action permission."""
        if not role_ids:
            return False

        action_col = {
            "view": RolePermission.can_view,
            "create": RolePermission.can_create,
            "edit": RolePermission.can_edit,
            "delete": RolePermission.can_delete,
        }.get(action)

        if action_col is None:
            return False

        stmt = select(RolePermission).where(
            RolePermission.role_id.in_(role_ids),
            RolePermission.module == module,
            action_col == True,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def check_extra_permission(
        db: AsyncSession,
        tenant_id: UUID,
        role_ids: List[int],
        permission_key: str,
    ) -> bool:
        """Check if any of the given roles has a specific extra permission."""
        if not role_ids:
            return False

        stmt = select(RolePermission).where(RolePermission.role_id.in_(role_ids))
        result = await db.execute(stmt)
        all_perms = list(result.scalars().all())

        for p in all_perms:
            if p.extra_permissions and p.extra_permissions.get(permission_key) is True:
                return True
        return False
