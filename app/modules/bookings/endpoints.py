"""
Endpoints API para el sistema de reservas (Booking)
FastAPI routes para crear, actualizar y gestionar reservas
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional, List
import logging

from app.core.database import get_db
from app.dependencies import get_current_user_sync
from app.services.booking_service import BookingService
from app.infra.event_bus import event_bus
from app.schemas.booking import (
    CreateBookingRequest, ConfirmBookingRequest, CancelBookingRequest,
    BookingResponse, BookingDetailResponse, BookingListResponse,
    CheckAvailabilityResponse, ServiceAvailabilityRequest, ServiceAvailabilityResponse,
    CreateBookingNoteRequest, BookingNoteResponse
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bookings", tags=["bookings"])


# ============================================================================
# HELPER: Obtener booking service
# ============================================================================

def get_booking_service(db: Session = Depends(get_db)) -> BookingService:
    """Dependencia para obtener el servicio de bookings"""
    return BookingService(db, event_bus)


# ============================================================================
# CREAR RESERVAS
# ============================================================================

@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    request: CreateBookingRequest,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    ✅ Crear una nueva reserva
    
    - **provider_id**: ID del proveedor
    - **service_id**: ID del servicio
    - **scheduled_date**: Fecha de la reserva (YYYY-MM-DD)
    - **scheduled_time**: Hora de la reserva (HH:MM:SS)
    - **duration**: Duración en minutos (15-480)
    - **total_price**: Precio total
    - **description**: Descripción adicional (opcional)
    
    Solo los clientes pueden crear reservas.
    """
    try:
        # Validar que el usuario sea cliente
        # BookingService resolverá el cliente desde el email
        return booking_service.create_booking_from_email(current_user.email, request)
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creando reserva: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creando la reserva"
        )


# ============================================================================
# OBTENER RESERVAS POR CLIENTE (DEBE IR ANTES DE /{booking_id})
# ============================================================================

@router.get("/client/{client_id}", response_model=BookingListResponse)
def get_client_bookings(
    client_id: int,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    📋 Obtener todas las reservas de un cliente
    
    Solo el cliente puede ver sus propias reservas.
    SECURITY: Usa SIEMPRE el ID del usuario autenticado (token), NO el parámetro
    """
    try:
        # Security: Usar SIEMPRE el ID del usuario autenticado, NO el parámetro
        # Esto evita errores 403 cuando el parámetro no coincide con el token
        current_user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        
        print(f"🔍 GET /client/{{id}} - user_id={current_user_id}, param={client_id}")
        
        bookings = booking_service.get_bookings_for_client(current_user_id)
        
        print(f"✅ Reservas encontradas: {len(bookings)}")
        
        return BookingListResponse(
            total=len(bookings),
            page=1,
            size=len(bookings),
            items=bookings
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================================
# OBTENER RESERVAS
# ============================================================================

@router.get("/provider", response_model=List[BookingResponse])
def get_provider_bookings(
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    📋 Obtener todas las reservas asignadas a mis servicios (Solo Proveedores)
    
    Retorna las reservas que están pendientes o confirmadas en los servicios del proveedor.
    """
    try:
        if current_user.role != "PROVIDER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo los proveedores pueden acceder a sus reservas"
            )
        
        provider_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        return booking_service.get_bookings_for_provider(provider_id)
    
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error obteniendo reservas del proveedor: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo reservas: {str(e)}"
        )


@router.get("/{booking_id}", response_model=BookingDetailResponse)
def get_booking(
    booking_id: str,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    📋 Obtener detalles de una reserva específica
    
    Solo el cliente y el proveedor pueden ver los detalles.
    """
    try:
        # Convert to int (booking_id is from path so convert from string)
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        current_user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        return booking_service.get_booking(booking_id_int, current_user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )




@router.get("", response_model=BookingListResponse)
def list_bookings(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    📊 Listar reservas según el rol del usuario
    
    - **CLIENT**: Ve solo sus reservas como cliente
    - **PROVIDER**: Ve solo sus reservas como proveedor
    - **ADMIN**: Ve todas las reservas
    
    Query params:
    - **page**: Número de página (defecto 1)
    - **size**: Resultados por página (defecto 10, máximo 100)
    - **status**: Filtrar por estado (PENDING, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED)
    """
    try:
        user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        result = booking_service.list_bookings(
            user_id,
            current_user.role,
            page,
            size,
            status
        )
        
        return BookingListResponse(
            total=result["total"],
            page=result["page"],
            size=result["size"],
            items=result["items"]
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================================
# ACTUALIZAR ESTADOS
# ============================================================================

@router.post("/{booking_id}/confirm", response_model=BookingResponse)
def confirm_booking(
    booking_id: str,
    request: ConfirmBookingRequest,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    ✅ Confirmar una reserva (proveedor)
    
    El proveedor confirma que acepta la reserva.
    Esto cambia el estado de PENDING a CONFIRMED.
    
    - **notes**: Notas adicionales (opcional)
    """
    try:
        if current_user.role != "PROVIDER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo los proveedores pueden confirmar reservas"
            )
        
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        provider_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        return booking_service.confirm_booking(
            booking_id_int,
            provider_id,
            request
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.post("/{booking_id}/cancel", response_model=BookingResponse)
def cancel_booking(
    booking_id: str,
    request: CancelBookingRequest,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    ❌ Cancelar una reserva
    
    Cliente o proveedor pueden cancelar.
    
    - **reason**: Razón de cancelación (requerida)
    - **reason_comment**: Comentario adicional (opcional)
    """
    try:
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        return booking_service.cancel_booking(
            booking_id_int,
            user_id,
            request
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================================
# DISPONIBILIDAD
# ============================================================================

@router.get("/availability/check", response_model=CheckAvailabilityResponse)
def check_availability(
    provider_id: str,
    service_id: str,
    scheduled_date: str,  # YYYY-MM-DD
    scheduled_time: str,  # HH:MM
    duration: int,
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    🔍 Verificar disponibilidad de un proveedor
    
    Valida si un proveedor está disponible para una fecha, hora y duración específica.
    
    Query params:
    - **provider_id**: UUID del proveedor
    - **service_id**: UUID del servicio
    - **scheduled_date**: Fecha (YYYY-MM-DD)
    - **scheduled_time**: Hora (HH:MM)
    - **duration**: Duración en minutos
    
    Response:
    - **is_available**: ¿Está disponible?
    - **reason**: Razón si no está disponible
    - **next_available_date**: Próxima fecha disponible
    - **next_available_time**: Próxima hora disponible
    """
    try:
        from datetime import date, time
        
        date_obj = date.fromisoformat(scheduled_date)
        hour, minute = map(int, scheduled_time.split(':'))
        time_obj = time(hour, minute)
        
        provider_id_int = int(provider_id) if isinstance(provider_id, str) else provider_id
        service_id_int = int(service_id) if isinstance(service_id, str) else service_id
        
        return booking_service.check_availability(
            provider_id_int,
            service_id_int,
            date_obj,
            time_obj,
            duration
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato inválido: {str(e)}"
        )


@router.post("/availability/set", response_model=ServiceAvailabilityResponse)
def set_availability(
    request: ServiceAvailabilityRequest,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    🕐 Configurar disponibilidad del proveedor
    
    El proveedor establece sus horarios disponibles por servicio y día.
    
    - **service_id**: UUID del servicio
    - **day_of_week**: Día (0=Lunes, 6=Domingo)
    - **start_time**: Hora de inicio (HH:MM)
    - **end_time**: Hora de fin (HH:MM)
    - **is_available**: ¿Disponible?
    - **timezone**: Zona horaria (default: America/Santiago)
    """
    try:
        if current_user.role != "PROVIDER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo los proveedores pueden configurar disponibilidad"
            )
        
        provider_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        return booking_service.set_availability(provider_id, request)
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ============================================================================
# NOTAS
# ============================================================================

@router.post("/{booking_id}/notes", response_model=BookingNoteResponse, status_code=status.HTTP_201_CREATED)
def add_note(
    booking_id: str,
    request: CreateBookingNoteRequest,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    📝 Agregar una nota a la reserva
    
    - **note_type**: Tipo (INTERNAL, CLIENT_VISIBLE, PROVIDER_VISIBLE)
    - **content**: Contenido de la nota (máximo 1000 caracteres)
    """
    try:
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        return booking_service.add_note(
            booking_id_int,
            user_id,
            request
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health", tags=["health"])
def health_check():
    """🏥 Health check del servicio de bookings"""
    return {
        "status": "ok",
        "service": "booking",
        "message": "Booking service is running"
    }
