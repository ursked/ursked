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
    # None when granted_by is None: granted at setup, not by a person.
    granted_by_name: Optional[str] = None
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
    # Why the CALLER may not approve this request (their own, or its subject
    # made them an approver), so the screen can say so instead of offering a
    # button the API refuses. None = they may.
    approval_block: Optional[str] = None


class GrantHistoryRow(BaseModel):
    id: int
    at: Optional[datetime] = None
    action: str
    label: str
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    subject_id: Optional[int] = None
    subject_name: Optional[str] = None
    kind: Optional[str] = None


class PendingRequestRef(BaseModel):
    id: int
    kind: str


class MyStatusResponse(BaseModel):
    is_viewer: bool
    is_approver: bool
    pending_kinds: List[str] = []
    pending_requests: List[PendingRequestRef] = []


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
