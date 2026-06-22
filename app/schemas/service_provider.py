# Either delete this file entirely, or make sure it doesn't conflict
# If you need to keep it, rename the class to avoid conflicts
from pydantic import BaseModel
from typing import Optional
from decimal import Decimal
from datetime import datetime

# Rename to avoid conflict
class ServiceProviderBaseSchema(BaseModel):
    service_category: str
    business_name: str
    description: Optional[str] = None
    address: str
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    phone: Optional[str] = None
    hourly_rate: Optional[Decimal] = None

class ServiceProviderCreateSchema(ServiceProviderBaseSchema):
    pass

class ServiceProviderResponseSchema(ServiceProviderBaseSchema):
    id: int
    provider_id: int  # ✅ OPCIÓN B: Added for provider ID mapping
    user_id: int
    is_available: bool = True
    validation_status: str = "pending"
    rating_avg: Decimal = 0.0
    total_reviews: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True