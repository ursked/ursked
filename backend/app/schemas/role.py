from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_system: bool = False
    is_active: bool = True


class UserRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: RoleResponse
    title: Optional[str] = None
    assigned_at: Optional[datetime] = None


class UserRoleAssign(BaseModel):
    role_code: str
    title: Optional[str] = None


class UserRoleRemove(BaseModel):
    role_code: str


class UserRoleBulkUpdate(BaseModel):
    role_codes: List[str]


class ReportsToUpdate(BaseModel):
    reports_to_id: Optional[int] = None
