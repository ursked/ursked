from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Org Level Schemas ────────────────────────────────────────────────


class OrgLevelItem(BaseModel):
    # The existing level this item keeps. Omit for a new level. Levels are
    # matched by id so deleting a middle level cannot rename the others.
    id: Optional[int] = None
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


_SCHEDULE_VISIBILITY_MODES = {"own_node", "own_and_children", "own_and_parent", "all"}


def _validate_schedule_visibility(v: Optional[str]) -> Optional[str]:
    """Accept a known mode, or None/'inherit' (both mean 'inherit from parent')."""
    if v is None or v == "" or v == "inherit":
        return None
    if v not in _SCHEDULE_VISIBILITY_MODES:
        raise ValueError(
            "schedule_visibility must be one of: inherit, "
            + ", ".join(sorted(_SCHEDULE_VISIBILITY_MODES))
        )
    return v


class OrgNodeCreate(BaseModel):
    parent_id: Optional[int] = None
    level_id: int
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    head_user_id: Optional[int] = None
    deputy_head_user_id: Optional[int] = None
    sort_order: int = 0
    schedule_visibility: Optional[str] = None

    @field_validator("schedule_visibility")
    @classmethod
    def _check_visibility(cls, v: Optional[str]) -> Optional[str]:
        return _validate_schedule_visibility(v)


class OrgNodeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    parent_id: Optional[int] = None
    head_user_id: Optional[int] = None
    deputy_head_user_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    schedule_visibility: Optional[str] = None

    @field_validator("schedule_visibility")
    @classmethod
    def _check_visibility(cls, v: Optional[str]) -> Optional[str]:
        return _validate_schedule_visibility(v)


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
    schedule_visibility: Optional[str] = None


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
    """One step of the chain filing would produce (see LeaveApprovalService)."""
    step_order: int = 1
    approver_id: int
    approver_name: str
    # auto | hybrid_org_chart | manual_* | fallback_* | self_approval
    source: str = "auto"
    is_deputy: bool = False
    # The unit whose head (or deputy) this is, for org-chart steps.
    node_id: Optional[int] = None
    node_name: Optional[str] = None
    level_name: Optional[str] = None


class _NamedRef(BaseModel):
    id: int
    name: str


class _RuleRef(BaseModel):
    id: int
    description: str


class _PolicyRuleRef(BaseModel):
    id: int
    name: str
    deactivated: bool


class OrgNodeDeletePreview(BaseModel):
    node_id: int
    node_name: str
    parent_id: Optional[int] = None
    parent_name: Optional[str] = None
    can_delete: bool
    blocked_reason: Optional[str] = None
    members_moved: List[_NamedRef] = []
    secondary_members: List[_NamedRef] = []
    children_moved: List[_NamedRef] = []
    approver_rules_deactivated: List[_RuleRef] = []
    policy_rules_changed: List[_PolicyRuleRef] = []


class ApprovalChainResponse(BaseModel):
    employee_id: int
    employee_name: str
    chain: List[ApprovalChainStep]
