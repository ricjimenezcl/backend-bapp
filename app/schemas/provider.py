from pydantic import BaseModel, EmailStr, validator, ConfigDict, Field
from datetime import datetime
from typing import Optional, List
import re
from decimal import Decimal
import base64
from app.utils.chile_validators import (
    validate_phone as _validate_phone,
    validate_rut as _validate_rut,
    normalize_rut as _normalize_rut,
    INVALID_PHONE_MSG,
    INVALID_RUT_MSG,
)

class ProviderRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None
    run: Optional[str] = None
    bio: Optional[str] = None
    avatar: Optional[str] = None
    identity_document: Optional[str] = None  # base64 o url temporal
    selfie: Optional[str] = None  # base64 o url temporal
    terms_accepted: bool = False
    email_opt_in: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "proveedor@example.com",
                "password": "Password123",
                "full_name": "María González",
                "phone": "+56987654321",
                "run": "12345678-9",
                "bio": "Profesional con 5 años de experiencia",
                "avatar": "base64string..."
            }
        }
    )

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('La contraseña debe tener al menos 8 caracteres')
        if not re.search(r'[A-Z]', v):
            raise ValueError('La contraseña debe contener al menos una letra mayúscula')
        if not re.search(r'[a-z]', v):
            raise ValueError('La contraseña debe contener al menos una letra minúscula')
        if not re.search(r'\d', v):
            raise ValueError('La contraseña debe contener al menos un número')
        return v

    @validator('phone')
    def validate_phone(cls, v):
        if v and not _validate_phone(v):
            raise ValueError(INVALID_PHONE_MSG)
        return v

    @validator('run')
    def validate_run(cls, v):
        if v is None or v == "":
            return None
        if not _validate_rut(v):
            raise ValueError(INVALID_RUT_MSG)
        return _normalize_rut(v)


class ProviderUpdateRequest(BaseModel):
    run: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[str] = None
    email: Optional[EmailStr] = None
    identity_document: Optional[str] = None
    selfie: Optional[str] = None
    validation_status: Optional[str] = None
    validation_notes: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "full_name": "María González Actualizado",
                "phone": "+56987654321",
                "run": "12345678-9",
                "bio": "Nueva bio actualizada",
                "avatar": "base64string...",
                "email": "nuevoemail@example.com",
                "status": "ACTIVE"
            }
        }
    )

    @validator('phone')
    def validate_phone(cls, v):
        if v is not None and v != "" and not _validate_phone(v):
            raise ValueError(INVALID_PHONE_MSG)
        return v

    @validator('run')
    def validate_run(cls, v):
        if v is not None and v != "":
            if not _validate_rut(v):
                raise ValueError(INVALID_RUT_MSG)
            return _normalize_rut(v)
        return v

    @validator('status')
    def validate_status(cls, v):
        if v is not None and v != "":
            valid_statuses = ["ACTIVE", "INACTIVE", "SUSPENDED"]
            if v not in valid_statuses:
                raise ValueError(f'Status must be one of: {", ".join(valid_statuses)}')
        return v
    

class ProviderResponse(BaseModel):
    id: int
    user_id: int
    run: Optional[str] = None
    full_name: str
    phone: Optional[str]
    avatar: Optional[str]
    bio: Optional[str]
    rating_avg: Decimal
    created_at: datetime
    updated_at: datetime
    email: str  # Nuevo campo desde users
    status: str  # Nuevo campo desde users
    identity_document_url: Optional[str] = None
    selfie_url: Optional[str] = None
    validation_status: Optional[str] = None
    validation_notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ServiceProviderCreateRequest(BaseModel):
    servicio: int  # main_category_id
    categoria: int  # service_category_id
    nombre_prestador: str
    fono: str
    detalle: Optional[str] = None
    direccion: str
    lat: Decimal
    lng: Decimal
    id_contacto: int  # user_id del proveedor

    model_config = ConfigDict(from_attributes=True)

# ADD THIS MISSING CLASS
class ServiceProviderCreate(BaseModel):
    provider_id: int
    service_id: int
    business_name: str
    description: Optional[str] = None
    address: str
    latitude: Decimal
    longitude: Decimal
    phone: str
    hourly_rate: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)

# Agrega esta clase en provider.py (después de ServiceProviderCreate)

class ServiceProviderUpdateRequest(BaseModel):
    business_name: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    phone: Optional[str] = None
    portfolio_images: Optional[List[str]] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "business_name": "Nuevo Nombre del Negocio",
                "description": "Descripción actualizada del servicio",
                "address": "Nueva Dirección 123, Ciudad",
                "latitude": -33.456789,
                "longitude": -70.123456,
                "phone": "+56987654321"
            }
        }
    )

    @validator('phone')
    def validate_phone(cls, v):
        if v is not None and v != "" and not _validate_phone(v):
            raise ValueError(INVALID_PHONE_MSG)
        return v

class ServiceProviderCreateResponse(BaseModel):
    id: int
    provider_id: int
    service_id: int
    business_name: str
    description: Optional[str]
    address: str
    latitude: Decimal
    longitude: Decimal
    phone: str
    hourly_rate: Optional[Decimal]
    is_available: bool
    validation_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ServiceCategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    icon: Optional[str]
    parent_category: Optional[str] = None  
    is_active: bool
    main_category_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ServiceProviderWithCategoryResponse(BaseModel):
    id: int
    service_provider_id: Optional[int] = Field(None, description="ID de service_providers (alias de id, para reservas y slots)")
    provider_user_id: Optional[int] = Field(None, description="ID de users (para WebSocket y auth)")
    avatar: Optional[str] = None
    provider_id: int
    service_id: int
    business_name: str
    full_name: str
    description: Optional[str]
    address: str
    latitude: Decimal
    longitude: Decimal
    distance: Decimal
    phone: str
    hourly_rate: Optional[Decimal]
    is_available: bool
    validation_status: str
    rating_avg: Decimal
    total_reviews: int
    portfolio_images: Optional[List[str]] = None
    created_at: datetime
    service_category: Optional[ServiceCategoryResponse] = None
    full_name: Optional[str] = Field(None, description="Nombre del proveedor (opcional)")
    distance: Optional[float] = Field(None, ge=0, description="Distancia en km (opcional)")

    model_config = ConfigDict(from_attributes=True)

# Define ServiceProviderResponse as an alias
ServiceProviderResponse = ServiceProviderWithCategoryResponse

class ProviderDetailedResponse(BaseModel):
    """Respuesta completa del proveedor con todos sus servicios"""
    id: int
    user_id: int
    run: Optional[str] = None
    full_name: str
    phone: Optional[str]
    avatar: Optional[str]
    bio: Optional[str]
    rating_avg: Decimal
    total_reviews: int = 0
    email: str
    status: str
    business_name: Optional[str] = None  # Nombre del negocio (puede diferir del full_name)
    services: List['ServiceProviderWithCategoryResponse'] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)