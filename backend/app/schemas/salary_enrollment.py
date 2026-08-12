from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class EnrollmentRow(BaseModel):
    id: int
    user_id: int
    user_name: str
    kind: str
    status: str
    granted_by: Optional[int] = None
    granted_at: Optional[datetime] = None


class RequestRow(BaseModel):
    id: int
    user_id: int
    user_name: str
    kind: str
    status: str
    reason: Optional[str] = None
    requested_at: Optional[datetime] = None
    decided_by: Optional[int] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None


class MyStatusResponse(BaseModel):
    is_viewer: bool
    is_approver: bool
    pending_kinds: List[str] = []


class CreateRequestBody(BaseModel):
    kind: str = Field(..., pattern="^(viewer|approver)$")
    reason: Optional[str] = None
    # Optional: an approver may request access on behalf of another user.
    user_id: Optional[int] = None


class DecisionBody(BaseModel):
    note: Optional[str] = None


class RevokeBody(BaseModel):
    user_id: int
    kind: str = Field(..., pattern="^(viewer|approver)$")


class RequestByToken(BaseModel):
    id: int
    user_id: int
    user_name: str
    kind: str
    reason: Optional[str] = None
    requested_at: Optional[datetime] = None
