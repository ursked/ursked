from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# Conditions are a TREE: a leaf {field,operator,value} or a group
# {"all"|"any"|"not": ...}. Actions may be direct-effect dicts or a range-band
# {"type":"bands","field":...,"bands":[...]}. The heavy validation lives in
# PolicyRuleService._validate (single source of truth vs the engine grammar), so
# the schema stays permissive and just carries the JSON through.
ConditionTree = Union[List[Dict[str, Any]], Dict[str, Any]]


class PolicyRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    rule_type: str = Field(..., pattern="^(overtime|tardiness|leave_conversion|attendance|night_differential|holiday_shift)$")
    priority: int = 0
    is_active: bool = True
    conditions: ConditionTree
    actions: List[Dict[str, Any]]
    employment_types: Optional[List[str]] = None
    scope_org_node_ids: Optional[List[int]] = None
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None


class PolicyRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    rule_type: Optional[str] = Field(None, pattern="^(overtime|tardiness|leave_conversion|attendance|night_differential|holiday_shift)$")
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    conditions: Optional[ConditionTree] = None
    actions: Optional[List[Dict[str, Any]]] = None
    employment_types: Optional[List[str]] = None
    scope_org_node_ids: Optional[List[int]] = None
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None


class PolicyRuleResponse(BaseModel):
    id: int
    tenant_id: str
    name: str
    description: Optional[str] = None
    rule_type: str
    priority: int
    is_active: bool
    conditions: Any
    actions: Any
    employment_types: Optional[List[str]] = None
    scope_org_node_ids: Optional[List[int]] = None
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Dry-run simulator ────────────────────────────────────────────────

class PolicySimulateRequest(BaseModel):
    start_date: date
    end_date: date
    employee_ids: Optional[List[int]] = None  # None = all employees


class SimulatedEffect(BaseModel):
    employee_id: int
    employee_name: Optional[str] = None
    date: date
    rule_id: int
    rule_name: str
    action: str
    detail: Optional[str] = None


class PolicySimulateResponse(BaseModel):
    records_evaluated: int
    effects: List[SimulatedEffect]
