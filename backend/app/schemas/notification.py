from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class NotificationRow(BaseModel):
    id: int
    type: str
    title: str
    body: Optional[str] = None
    action_type: Optional[str] = None
    action_ref_id: Optional[int] = None
    is_read: bool
    is_actioned: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NotificationList(BaseModel):
    items: List[NotificationRow]
    unread_count: int
