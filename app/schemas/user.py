from pydantic import BaseModel, EmailStr, validator, ConfigDict
from datetime import datetime
from typing import Optional
import re
from app.utils.chile_validators import normalize_phone

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str

    @validator('password')
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

    @validator('role')
    def validate_role(cls, v):
        v_upper = v.upper()
        valid_roles = {"CLIENT", "PROVIDER", "ADMIN"}
        if v_upper not in valid_roles:
            raise ValueError(f'Role must be one of: {", ".join(valid_roles)}')
        return v_upper

class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    status: str
    created_at: datetime
    has_premium: bool = False
    premium_expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# En app/schemas/user.py
class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str
    user_id: int
    role: str
    email: str
    status: str
    terms_accepted: bool = False
    
    # Campos específicos según el rol
    provider_id: Optional[int] = None
    client_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)

class TokenData(BaseModel):
    email: Optional[str] = None

class ClientRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None
    terms_accepted: bool = False
    email_opt_in: bool = False
    registration_source: Optional[str] = "web"

    @validator('email')
    def normalize_email(cls, v):
        return v.strip().lower()

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
        if v and not re.match(r'^(\+56|56)?\s?9\s?\d{4}\s?\d{4}$', v.replace(' ', '')):
            raise ValueError('Formato de teléfono chileno inválido')
        return normalize_phone(v) if v else v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "cliente@example.com",
                "password": "Password123",
                "full_name": "Juan Pérez",
                "phone": "+56912345678"
            }
        }
    )

class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None

    @validator('phone')
    def validate_phone(cls, v):
        if v and not re.match(r'^(\+56|56)?\s?9\s?\d{4}\s?\d{4}$', v.replace(' ', '')):
            raise ValueError('Invalid Chilean phone number format')
        return v
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "full_name": "Juan Pérez Updated",
                "phone": "+56912345678",
                "avatar": "base64string..."
            }
        }
    )

class UserProfileResponse(BaseModel):
    id: int
    user_id: int
    full_name: str
    phone: Optional[str] = None
    avatar: Optional[str] = None
    # Bio excluida intencionalmente para clientes
    rating_avg: int
    
    model_config = ConfigDict(from_attributes=True)

class UserDetailResponse(UserResponse):
    profile: Optional[UserProfileResponse] = None

    model_config = ConfigDict(from_attributes=True)