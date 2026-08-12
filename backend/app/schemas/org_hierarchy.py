from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Org Level Schemas ────────────────────────────────────────────────


class OrgLevelItem(BaseModel):
    level_number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)


class OrgLevelsSet(BaseModel):
    """PUT payload: replace all levels for a tenant atomically. No upper bound
    on the number of levels — deep hierarchies are supported."""

    levels: List[OrgLevelItem] = Field(min_length=1)


class OrgLevelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    level_number: int
    name: str


class OrgLevelsResponse(BaseModel):
    levels: List[OrgLevelResponse]


# ── Org Node Schemas ─────────────────────────────────────────────────


class OrgNodeCreate(BaseModel):
    parent_id: Optional[int] = None
    level_id: int
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    head_user_id: Optional[int] = None
    deputy_head_user_id: Optional[int] = None
    sort_order: int = 0


class OrgNodeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    parent_id: Optional[int] = None
    head_user_id: Optional[int] = None
    deputy_head_user_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class OrgNodeMemberSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    first_name: str
    last_name: str
    email: str
    job_title: Optional[str] = None
    avatar: Optional[str] = None
    is_primary: bool = True


class OrgNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: Optional[int] = None
    level_id: int
    level_name: str = ""
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    head_user_id: Optional[int] = None
    head_user_name: Optional[str] = None
    deputy_head_user_id: Optional[int] = None
    deputy_head_user_name: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    member_count: int = 0


class OrgTreeNode(BaseModel):
    """Recursive tree node with nested children."""

    id: int
    parent_id: Optional[int] = None
    level_id: int
    level_name: str = ""
    level_number: int = 0
    name: str
    code: Optional[str] = None
    head_user_id: Optional[int] = None
    head_user_name: Optional[str] = None
    deputy_head_user_id: Optional[int] = None
    deputy_head_user_name: Optional[str] = None
    member_count: int = 0
    is_active: bool = True
    children: List["OrgTreeNode"] = []


class OrgTreeResponse(BaseModel):
    levels: List[OrgLevelResponse]
    nodes: List[OrgTreeNode]


# ── Member Assignment ────────────────────────────────────────────────


class AssignMembersRequest(BaseModel):
    user_ids: List[int] = Field(min_length=1)


class UnassignMembersRequest(BaseModel):
    user_ids: List[int] = Field(min_length=1)


class OrgNodeMembersResponse(BaseModel):
    node_id: int
    node_name: str
    members: List[OrgNodeMemberSummary]
    total: int


# ── Approval Chain ───────────────────────────────────────────────────


class ApprovalChainStep(BaseModel):
    node_id: int
    node_name: str
    level_name: str
    approver_id: int
    approver_name: str
    is_deputy: bool = False


class ApprovalChainResponse(BaseModel):
    employee_id: int
    employee_name: str
    chain: List[ApprovalChainStep]
