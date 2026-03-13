from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.schemas.service_category import ServiceCategoryResponse

class MainCategoryBase(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True

class MainCategoryResponse(MainCategoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class MainCategoryWithServices(MainCategoryResponse):
    services: List[ServiceCategoryResponse] = []