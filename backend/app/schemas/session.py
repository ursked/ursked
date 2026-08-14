from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SessionResponse(BaseModel):
    id: int
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    login_at: datetime
    last_activity_at: Optional[datetime] = None
    expires_at: datetime
    is_current: bool = False

    model_config = {"from_attributes": True}
