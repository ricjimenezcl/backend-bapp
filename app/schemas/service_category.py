from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ServiceCategoryBase(BaseModel):
    name: str
    description: Optional[str] = None
    parent_category: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool = True

class ServiceCategoryResponse(ServiceCategoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class CategoryGroup(BaseModel):
    category_name: str
    services: list[ServiceCategoryResponse]