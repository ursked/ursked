"""Company-defined employee fields (Employees > Custom fields).

Managing the definitions is company configuration, so it follows settings:edit
like employee types. Reading them is open to every signed-in user, filtered to
the fields that user could ever see, because the employee form, the directory
and My Profile are all built from this list. Values themselves travel with the
employee record (`custom_fields` on GET/PATCH /users/...).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.employee_field import EmployeeFieldDefinition
from app.models.user import User
from app.services import audit_service, employee_access, employee_field_service as efs
from app.services.user_service import DEFAULT_EMPLOYEE_NUMBER_LABEL

router = APIRouter(prefix="/employee-fields", tags=["Employee fields"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldCreate(_Strict):
    key: str = Field(max_length=50)
    label: str = Field(max_length=100)
    field_type: str = "text"
    options: Optional[List[str]] = None
    is_required: bool = False
    is_unique: bool = False
    regex: Optional[str] = Field(default=None, max_length=200)
    visibility: str = "hr_only"
    is_sensitive: bool = False
    help_text: Optional[str] = Field(default=None, max_length=300)


class FieldUpdate(_Strict):
    label: Optional[str] = Field(default=None, max_length=100)
    field_type: Optional[str] = None
    options: Optional[List[str]] = None
    is_required: Optional[bool] = None
    is_unique: Optional[bool] = None
    regex: Optional[str] = Field(default=None, max_length=200)
    visibility: Optional[str] = None
    is_sensitive: Optional[bool] = None
    help_text: Optional[str] = Field(default=None, max_length=300)
    is_archived: Optional[bool] = None


class ReorderRequest(_Strict):
    ids: List[int] = Field(max_length=500)


class LabelRequest(_Strict):
    # null or blank restores the default wording.
    label: Optional[str] = Field(default=None, max_length=50)


async def _get(db: AsyncSession, tenant_id, field_id: int) -> EmployeeFieldDefinition:
    defn = (
        await db.execute(
            select(EmployeeFieldDefinition).where(
                EmployeeFieldDefinition.id == field_id, EmployeeFieldDefinition.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status_code=404, detail="Custom field not found")
    return defn


def _snapshot(defn: EmployeeFieldDefinition) -> Dict[str, Any]:
    return {k: getattr(defn, k) for k in efs.DEFINITION_AUDIT_FIELDS}


@router.get("")
async def list_fields(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """{employee_number_label, can_manage, fields: [...]}. Archived fields are
    listed only for people who manage them (to restore one)."""
    from app.services.user_service import UserService

    can_manage = await employee_access.has_permission(db, current_user, "settings", "edit")
    access = await efs.viewer_access(db, current_user)
    defs = await efs.list_definitions(db, current_user.tenant_id, include_archived=include_archived and can_manage)
    return {
        "employee_number_label": await UserService.employee_number_label(db, current_user.tenant_id),
        "default_employee_number_label": DEFAULT_EMPLOYEE_NUMBER_LABEL,
        "can_manage": can_manage,
        "fields": [efs.definition_dict(d) for d in defs if can_manage or efs.definition_visible_to(d, access)],
    }


@router.post("", status_code=201)
async def create_field(
    body: FieldCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await employee_access.require(db, current_user, "settings", "edit")
    defn = await efs.create_definition(db, current_user.tenant_id, body.model_dump(), current_user.id)
    audit_service.record(
        db, actor=current_user, action="custom_field_create", resource_type="employee_field",
        resource_id=defn.id, request=request, details={"label": defn.label, "after": _snapshot(defn)},
    )
    return efs.definition_dict(defn)


@router.post("/reorder")
async def reorder_fields(
    body: ReorderRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await employee_access.require(db, current_user, "settings", "edit")
    await efs.reorder(db, current_user.tenant_id, body.ids)
    audit_service.record(
        db, actor=current_user, action="custom_field_reorder", resource_type="employee_field",
        request=request, details={"order": body.ids},
    )
    return {"ok": True}


@router.put("/employee-number-label")
async def set_employee_number_label(
    body: LabelRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename Personnel # for this company (e.g. "Badge no.", "Staff ID")."""
    await employee_access.require(db, current_user, "settings", "edit")
    from app.services.settings_service import SettingsService

    settings = await SettingsService.get_or_create_app_settings(db, current_user.tenant_id)
    before = settings.employee_number_label
    label = (body.label or "").strip() or None
    settings.employee_number_label = label
    await db.flush()
    audit_service.record(
        db, actor=current_user, action="employee_number_label_update", resource_type="settings",
        request=request, details={"from": before, "to": label},
    )
    return {"employee_number_label": label or DEFAULT_EMPLOYEE_NUMBER_LABEL}


@router.patch("/{field_id}")
async def update_field(
    field_id: int,
    body: FieldUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await employee_access.require(db, current_user, "settings", "edit")
    defn = await _get(db, current_user.tenant_id, field_id)
    before = _snapshot(defn)
    await efs.update_definition(db, defn, body.model_dump(exclude_unset=True))
    changes = audit_service.diff(before, _snapshot(defn))
    if changes:
        audit_service.record(
            db, actor=current_user, action="custom_field_update", resource_type="employee_field",
            resource_id=defn.id, request=request, details={"label": defn.label, "changes": changes},
        )
    return efs.definition_dict(defn)


@router.delete("/{field_id}")
async def delete_field(
    field_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a field nobody has filled in; archive one that holds values."""
    await employee_access.require(db, current_user, "settings", "edit")
    defn = await _get(db, current_user.tenant_id, field_id)
    label, fid = defn.label, defn.id
    outcome = await efs.archive_or_delete(db, defn)
    audit_service.record(
        db, actor=current_user,
        action={"archived": "custom_field_archive", "deleted": "custom_field_delete"}[outcome],
        resource_type="employee_field", resource_id=fid, request=request, details={"label": label},
    )
    return {"result": outcome}
