from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

VALID_MODULES = [
    "employees",
    "organization",
    "schedules",
    "leave",
    "finances",
    "settings",
    "reports",
]


class RolePermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_id: int
    module: str
    can_view: bool
    can_create: bool
    can_edit: bool
    can_delete: bool
    extra_permissions: Optional[Dict[str, Any]] = None


class RolePermissionUpdateItem(BaseModel):
    module: str
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    extra_permissions: Optional[Dict[str, Any]] = None


class BulkPermissionUpdate(BaseModel):
    permissions: List[RolePermissionUpdateItem]


class PermissionMatrixEntry(BaseModel):
    role_id: int
    role_code: str
    role_name: str
    modules: Dict[str, RolePermissionResponse]


class PermissionMatrixResponse(BaseModel):
    entries: List[PermissionMatrixEntry]


class MyPermissionsResponse(BaseModel):
    """Returned to frontend for the PermissionsContext."""
    permissions: Dict[str, Dict[str, bool]]  # {module: {view: true, create: false, ...}}
    extra: Dict[str, bool]  # {view_salary: true, ...}
