from pydantic import BaseModel, model_validator
from typing import Optional
from datetime import datetime


class NotificationSchema(BaseModel):
    id: int
    type: str
    title: str
    content: str
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def map_orm_fields(cls, data):
        """Map ORM model attributes to schema field names."""
        if hasattr(data, "__dict__"):
            nt = getattr(data, "notification_type", None)
            type_str = nt.value if hasattr(nt, "value") else str(nt) if nt else "message"
            return {
                "id": data.id,
                "type": type_str,
                "title": data.title,
                "content": data.content,
                "related_entity_type": data.related_entity_type,
                "related_entity_id": data.related_entity_id,
                "is_read": data.is_read,
                "created_at": data.created_at,
            }
        return data
