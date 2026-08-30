from pydantic import BaseModel
from typing import Optional


class SubcategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    main_category_id: int

    class Config:
        from_attributes = True


class ServiceNewResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    subcategory_id: int
    service_category_id: Optional[int] = None  # FK legacy a service_categories para búsqueda

    class Config:
        from_attributes = True
