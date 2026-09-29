from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.role import Role
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
    """What this session may do, module by module: the answers
    require_permission will give. In an admin session that is the
    administration modules plus leave configuration and no operations; in an
    employee session no finances; see permission_service. Salary figures are
    not the matrix's (salary-viewer enrollment), so none is claimed here."""
    result = await PermissionService.user_permissions(db, current_user)
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
    # role_id comes from the URL, so it must be proven to belong to the
    # caller's tenant before anything is written: without this an admin of one
    # tenant could rewrite another tenant's permission matrix by guessing ids
    # (audit Tier 1 #15). 404, not 403, so ids of other tenants are not probed.
    role = (
        await db.execute(
            select(Role).where(Role.id == role_id, Role.tenant_id == current_user.tenant_id)
        )
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    perms_data = [p.model_dump() for p in body.permissions]
    before = {p.module: [p.can_view, p.can_create, p.can_edit, p.can_delete]
              for p in await PermissionService.get_role_permissions(db, role_id)}
    updated = await PermissionService.update_role_permissions(
        db, current_user.tenant_id, role_id, perms_data
    )
    after = {p.module: [p.can_view, p.can_create, p.can_edit, p.can_delete] for p in updated}
    from app.services import audit_service

    changes = audit_service.diff(before, {**before, **after})
    if changes:
        audit_service.record(
            db, actor=current_user, action="permissions_update", resource_type="role", resource_id=role.id,
            details={"role": role.code, "changes": changes},
        )
    await db.commit()
    return {"updated": len(updated)}
