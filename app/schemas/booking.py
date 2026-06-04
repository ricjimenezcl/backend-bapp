# Constantes de descripciones reutilizables
SERVICE_UUID_DESC = "UUID del servicio"
"""
Schemas Pydantic para el sistema de reservas (Booking)
Validación de requests y responses
"""

from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field, validator


# ============================================================================
# ENUMS
# ============================================================================

class BookingStatusEnum(str, Enum):
    PENDING     = "PENDING"
    APPROVED    = "APPROVED"      # Aprobada por el proveedor
    REJECTED    = "REJECTED"      # Rechazada por el proveedor
    COMPLETED   = "COMPLETED"
    # Legacy — compatibilidad con datos históricos
    CONFIRMED   = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    CANCELLED   = "CANCELLED"
    NOSHOW      = "NOSHOW"


class CancellationReasonEnum(str, Enum):
    CLIENT_REQUEST = "CLIENT_REQUEST"
    PROVIDER_REQUEST = "PROVIDER_REQUEST"
    ADMIN_REQUEST = "ADMIN_REQUEST"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CLIENT_NO_SHOW = "CLIENT_NO_SHOW"
    OTHER = "OTHER"


# ============================================================================
# BOOKING SCHEMAS
# ============================================================================

class CreateBookingRequest(BaseModel):
    """Request para crear una nueva reserva"""
    provider_id: int = Field(..., description="ID del proveedor (Integer)")
    service_id: int = Field(..., description="ID del servicio (Integer)")
    service_provider_id: Optional[int] = Field(None, description="ID del servicio publicado por el proveedor")
    scheduled_date: date = Field(..., description="Fecha de la reserva")
    scheduled_time: time = Field(..., description="Hora de la reserva")
    duration: int = Field(..., ge=15, le=480, description="Duración en minutos (15-480)")
    total_price: Decimal = Field(..., ge=0, description="Precio total")
    description: Optional[str] = Field(None, max_length=500, description="Descripción adicional")
    location_address: Optional[str] = Field(None, max_length=255, description="Dirección de la ubicación")
    location_lat: Optional[float] = Field(None, description="Latitud de la ubicación")
    location_lng: Optional[float] = Field(None, description="Longitud de la ubicación")
    service_category: Optional[str] = Field(None, max_length=255, description="Categoría del servicio")
    
    class Config:
        example = {
            "provider_id": 42,
            "service_id": 31,
            "scheduled_date": "2026-02-15",
            "scheduled_time": "10:00:00",
            "duration": 60,
            "total_price": "50000.00",
            "description": "Limpieza completa del hogar"
        }


# Alias para compatibilidad con endpoints que importan BookingCreate
BookingCreate = CreateBookingRequest


# Alias for backward compatibility with endpoint imports
BookingCreate = CreateBookingRequest


class ConfirmBookingRequest(BaseModel):
    """Request para confirmar una reserva"""
    notes: Optional[str] = Field(None, max_length=500, description="Notas del proveedor")
    
    class Config:
        example = {
            "notes": "Llegué 10 minutos antes"
        }


class CancelBookingRequest(BaseModel):
    """Request para cancelar una reserva"""
    reason: CancellationReasonEnum = Field(..., description="Razón de la cancelación")
    reason_comment: Optional[str] = Field(None, max_length=500, description="Comentario adicional")
    
    class Config:
        example = {
            "reason": "CLIENT_REQUEST",
            "reason_comment": "Cambio de planes"
        }


class BookingStatusHistoryResponse(BaseModel):
    """Response del historial de estado de una reserva"""
    id: str
    previous_status: Optional[BookingStatusEnum]
    new_status: BookingStatusEnum
    changed_by_id: str
    reason: Optional[str]
    reason_comment: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class BookingResponse(BaseModel):
    """Response de una reserva individual"""
    id: str
    client_id: str
    provider_id: str
    service_id: Optional[str] = None
    scheduled_date: date
    scheduled_time: Optional[time] = None
    duration: Optional[int] = None
    description: Optional[str] = None
    total_price: Optional[Decimal] = None
    currency: str
    status: BookingStatusEnum
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    service_provider_id: Optional[int] = None
    location_address: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    service_category: Optional[str] = None
    
    class Config:
        from_attributes = True
        example = {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "client_id": "223e4567-e89b-12d3-a456-426614174000",
            "provider_id": "323e4567-e89b-12d3-a456-426614174000",
            "service_id": "423e4567-e89b-12d3-a456-426614174000",
            "scheduled_date": "2026-02-15",
            "scheduled_time": "10:00:00",
            "duration": 60,
            "description": "Limpieza completa",
            "total_price": "50000.00",
            "currency": "CLP",
            "status": "CONFIRMED",
            "created_at": "2026-01-27T10:00:00",
            "updated_at": "2026-01-27T10:00:00",
            "completed_at": None
        }


class BookingDetailResponse(BookingResponse):
    """Response detallado de una reserva con relaciones"""
    status_history: List[BookingStatusHistoryResponse] = []
    
    class Config:
        from_attributes = True


class BookingListResponse(BaseModel):
    """Response para listar reservas (paginado)"""
    total: int
    page: int
    size: int
    items: List[BookingResponse]
    
    class Config:
        from_attributes = True


class UpdateBookingStatusRequest(BaseModel):
    """Request para cambiar manualmente el estado de una reserva"""
    status: BookingStatusEnum = Field(..., description="Nuevo estado")
    reason: Optional[str] = Field(None, description="Razón del cambio")
    reason_comment: Optional[str] = Field(None, description="Comentario del cambio")
    
    class Config:
        example = {
            "status": "IN_PROGRESS",
            "reason": "START",
            "reason_comment": "Iniciando el servicio"
        }


# ============================================================================
# SERVICE AVAILABILITY SCHEMAS
# ============================================================================

class ServiceAvailabilityRequest(BaseModel):
    """Request para crear o actualizar disponibilidad de un servicio publicado."""
    service_id: int = Field(..., description="ID de service_providers (servicio publicado)")
    day_of_week: int = Field(..., ge=0, le=6, description="Día de la semana (0=Lunes, 6=Domingo)")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Hora inicio HH:MM")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Hora fin HH:MM")
    is_available: bool = Field(default=True, description="¿Está disponible?")
    timezone: str = Field(default="America/Santiago", description="Zona horaria")

    class Config:
        example = {
            "service_id": 42,
            "day_of_week": 0,
            "start_time": "09:00",
            "end_time": "17:00",
            "is_available": True,
            "timezone": "America/Santiago"
        }


class ServiceAvailabilityResponse(BaseModel):
    """Response de disponibilidad de un servicio publicado."""
    id: int
    provider_id: int
    service_id: int
    day_of_week: int
    day_name: str
    start_time: str
    end_time: str
    is_available: bool
    timezone: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TimeSlot(BaseModel):
    """Un slot horario con su estado de disponibilidad."""
    time: str        # "09:00"
    available: bool  # False si está reservado (PENDING o CONFIRMED)


class AvailableSlotsResponse(BaseModel):
    """Slots horarios disponibles para una fecha y servicio concretos."""
    date: date
    service_provider_id: int
    slots: List[TimeSlot]


class CheckAvailabilityRequest(BaseModel):
    """Request para verificar disponibilidad"""
    provider_id: str = Field(..., description="UUID del proveedor")
    service_id: str = Field(..., description=SERVICE_UUID_DESC)
    scheduled_date: date = Field(..., description="Fecha a verificar")
    scheduled_time: time = Field(..., description="Hora a verificar")
    duration: int = Field(..., ge=15, le=480, description="Duración en minutos")


class CheckAvailabilityResponse(BaseModel):
    """Response de verificación de disponibilidad"""
    is_available: bool
    reason: Optional[str] = None
    next_available_date: Optional[date] = None
    next_available_time: Optional[time] = None
    
    class Config:
        example = {
            "is_available": True,
            "reason": None,
            "next_available_date": None,
            "next_available_time": None
        }


# ============================================================================
# BOOKING NOTES SCHEMAS
# ============================================================================

class CreateBookingNoteRequest(BaseModel):
    """Request para agregar una nota a una reserva"""
    note_type: str = Field(..., description="INTERNAL, CLIENT_VISIBLE, PROVIDER_VISIBLE")
    content: str = Field(..., max_length=1000, description="Contenido de la nota")
    
    class Config:
        example = {
            "note_type": "INTERNAL",
            "content": "Cliente llegó 15 minutos tarde"
        }


class BookingNoteResponse(BaseModel):
    """Response de una nota de reserva"""
    id: str
    booking_id: str
    note_type: str
    content: str
    created_by_id: str
    created_at: datetime
    
    class Config:
        from_attributes = True

    duration: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True