"""
Schemas for monetization system (Products, Transactions, Platform Products, Slots)
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal


# ============================================
# PRODUCT SCHEMAS
# ============================================

class ProductBase(BaseModel):
    """Base schema for products"""
    sku: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    target_role: str = Field(..., pattern="^(CLIENT|PROVIDER|ALL)$")
    duration_days: int = Field(..., gt=0)
    price_usd: Decimal = Field(..., decimal_places=2)
    price_clp: Decimal = Field(..., decimal_places=2)
    free_limit: int = Field(default=0, ge=0)
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None


class ProductCreate(ProductBase):
    """Schema for creating products"""
    pass


class ProductUpdate(BaseModel):
    """Schema for updating products"""
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    price_usd: Optional[Decimal] = Field(None, decimal_places=2)
    price_clp: Optional[Decimal] = Field(None, decimal_places=2)
    is_active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


class ProductResponse(ProductBase):
    """Schema for product responses"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# PLATFORM PRODUCT SCHEMAS
# ============================================

class PlatformProductBase(BaseModel):
    """Base schema for platform products"""
    product_id: int
    platform: str = Field(..., pattern="^(google_play|apple_iap|web)$")
    platform_product_id: str = Field(..., max_length=255)
    platform_price: Optional[str] = Field(None, max_length=50)
    is_active: bool = True


class PlatformProductCreate(PlatformProductBase):
    """Schema for creating platform products"""
    pass


class PlatformProductResponse(PlatformProductBase):
    """Schema for platform product responses"""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# TRANSACTION SCHEMAS
# ============================================

class TransactionBase(BaseModel):
    """Base schema for transactions"""
    user_id: int
    product_id: Optional[int] = None
    platform: str = Field(..., pattern="^(google_play|apple_iap|web)$")
    amount: Decimal = Field(..., decimal_places=2)
    currency: str = Field(default="CLP", max_length=3)


class TransactionCreate(TransactionBase):
    """Schema for creating transactions"""
    purchase_token: Optional[str] = None
    receipt_data: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_info: Optional[Dict[str, Any]] = None


class TransactionUpdate(BaseModel):
    """Schema for updating transactions"""
    status: Optional[str] = Field(None, pattern="^(pending|completed|failed|refunded|expired)$")
    platform_transaction_id: Optional[str] = None
    platform_order_id: Optional[str] = None
    validated_at: Optional[datetime] = None
    validation_response: Optional[str] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    benefit_metadata: Optional[Dict[str, Any]] = None


class TransactionResponse(BaseModel):
    """Schema for transaction responses"""
    id: int
    user_id: int
    product_id: Optional[int] = None
    platform: str
    amount: Decimal
    currency: str
    status: str
    transaction_id: Optional[str] = None
    platform_transaction_id: Optional[str] = None
    platform_order_id: Optional[str] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TransactionDetailResponse(TransactionResponse):
    """Schema for detailed transaction responses (includes product info)"""
    product: Optional[ProductResponse] = None


# ============================================
# PROVIDER SERVICE SLOT SCHEMAS
# ============================================

class ProviderServiceSlotBase(BaseModel):
    """Base schema for provider service slots"""
    provider_id: int
    slot_number: int = Field(..., gt=0)
    is_free: bool = True


class ProviderServiceSlotCreate(ProviderServiceSlotBase):
    """Schema for creating provider service slots"""
    is_active: bool = False


class ProviderServiceSlotUpdate(BaseModel):
    """Schema for updating provider service slots"""
    service_provider_id: Optional[int] = None
    transaction_id: Optional[int] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None


class ProviderServiceSlotResponse(ProviderServiceSlotBase):
    """Schema for provider service slot responses"""
    id: int
    service_provider_id: Optional[int]
    transaction_id: Optional[int]
    activated_at: Optional[datetime]
    expires_at: Optional[datetime]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# PAYMENT VERIFICATION SCHEMAS
# ============================================

class GooglePlayVerificationRequest(BaseModel):
    """Schema for Google Play purchase verification"""
    purchase_token: str
    product_id: str
    package_name: str = "io.ionic.bappsearch"


class AppleIAPVerificationRequest(BaseModel):
    """Schema for Apple IAP purchase verification"""
    receipt_data: str  # Base64 encoded receipt
    shared_secret: Optional[str] = None


class TransbankVerificationRequest(BaseModel):
    """Schema for Transbank payment verification"""
    token: str


class PaymentVerificationResponse(BaseModel):
    """Generic payment verification response"""
    success: bool
    transaction_id: Optional[int] = None
    message: str
    expires_at: Optional[datetime] = None
    error: Optional[str] = None


# ============================================
# PRODUCT CATALOG SCHEMAS
# ============================================

class ProductCatalogItem(BaseModel):
    """Schema for product catalog items (includes platform info)"""
    id: int
    sku: str
    name: str
    description: Optional[str]
    target_role: str
    duration_days: int
    price_usd: Decimal
    price_clp: Decimal
    free_limit: int
    is_active: bool
    metadata: Optional[Dict[str, Any]]
    platforms: List[PlatformProductResponse] = []

    class Config:
        from_attributes = True


class ProductCatalogResponse(BaseModel):
    """Schema for product catalog response"""
    products: List[ProductCatalogItem]
    total: int
