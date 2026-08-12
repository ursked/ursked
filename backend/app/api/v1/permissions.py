from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.user import User
from app.schemas.permission import (
    BulkPermissionUpdate,
    MyPermissionsResponse,
    PermissionMatrixEntry,
    PermissionMatrixResponse,
    RolePermissionResponse,
)
from app.services.permission_service import PermissionService

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/me", response_model=MyPermissionsResponse)
async def get_my_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get merged permissions for the current user across all their roles."""
    # tenant_admin gets all permissions
    if current_user.has_role("tenant_admin"):
        from app.services.permission_service import VALID_MODULES

        perms = {
            m: {"view": True, "create": True, "edit": True, "delete": True}
            for m in VALID_MODULES
        }
        return MyPermissionsResponse(
            permissions=perms,
            extra={"view_salary": True},
        )

    role_ids = [ur.role_id for ur in current_user.user_roles]
    result = await PermissionService.get_user_permissions(
        db, current_user.tenant_id, role_ids
    )
    return MyPermissionsResponse(**result)


@router.get("/matrix", response_model=PermissionMatrixResponse)
async def get_permission_matrix(
    current_user: User = Depends(require_role(["tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Get the full permission matrix for all roles (tenant_admin only)."""
    entries = await PermissionService.get_permission_matrix(db, current_user.tenant_id)

    response_entries = []
    for entry in entries:
        modules = {}
        for module_name, perm in entry["modules"].items():
            modules[module_name] = RolePermissionResponse.model_validate(perm)
        response_entries.append(
            PermissionMatrixEntry(
                role_id=entry["role_id"],
                role_code=entry["role_code"],
                role_name=entry["role_name"],
                modules=modules,
            )
        )

    return PermissionMatrixResponse(entries=response_entries)


@router.put("/role/{role_id}")
async def update_role_permissions(
    role_id: int,
    body: BulkPermissionUpdate,
    current_user: User = Depends(require_role(["tenant_admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Update all permissions for a specific role (tenant_admin only)."""
    perms_data = [p.model_dump() for p in body.permissions]
    updated = await PermissionService.update_role_permissions(
        db, current_user.tenant_id, role_id, perms_data
    )
    await db.commit()
    return {"updated": len(updated)}
