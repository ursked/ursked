from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class DepartmentCreate(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: bool


class DivisionCreate(BaseModel):
    name: str
    code: Optional[str] = None
    department_id: Optional[int] = None
    description: Optional[str] = None


class DivisionUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    department_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DivisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: Optional[str] = None
    department_id: Optional[int] = None
    description: Optional[str] = None
    is_active: bool


class SectionCreate(BaseModel):
    name: str
    code: Optional[str] = None
    division_id: Optional[int] = None
    description: Optional[str] = None


class SectionUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    division_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: Optional[str] = None
    division_id: Optional[int] = None
    description: Optional[str] = None
    is_active: bool


class UnitCreate(BaseModel):
    name: str
    code: Optional[str] = None
    section_id: Optional[int] = None
    description: Optional[str] = None


class UnitUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    section_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class UnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: Optional[str] = None
    section_id: Optional[int] = None
    description: Optional[str] = None
    is_active: bool


class OrganizationTree(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    type: str
    children: Optional[List["OrganizationTree"]] = None


class OrgListResponse(BaseModel):
    items: List
    total: int
    page: int
    per_page: int
    total_pages: int
