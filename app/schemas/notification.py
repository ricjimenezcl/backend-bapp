from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

class NotificationSchema(BaseModel):
    id: int
    type: str
    title: str
    message: str
    payload: Optional[Any]
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
