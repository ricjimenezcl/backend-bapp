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
# ALIAS ENDPOINTS — frontend compatibility
# ============================================================================

@router.get("/my-bookings", response_model=List[BookingResponse])
def get_my_bookings(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service),
):
    """📋 Mis reservas (cliente). Alias de /bookings/client/{id} que devuelve lista plana."""
    user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
    bookings = booking_service.get_bookings_for_client(user_id)
    if status_filter:
        bookings = [b for b in bookings if b.status.lower() == status_filter.lower()]
    return bookings


@router.get("/provider-bookings", response_model=List[BookingResponse])
def get_provider_bookings_alias(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service),
):
    """📋 Reservas del proveedor. Alias de /bookings/provider que devuelve lista plana."""
    if current_user.role != "PROVIDER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo proveedores")
    provider_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
    bookings = booking_service.get_bookings_for_provider(provider_id)
    if status_filter:
        bookings = [b for b in bookings if b.status.lower() == status_filter.lower()]
    return bookings


class BookingStatusUpdate(BaseModel if True else object):
    status: str  # confirmed | rejected | in_progress | completed | cancelled


from pydantic import BaseModel as _BaseModel


class _StatusBody(_BaseModel):
    status: str


@router.put("/{booking_id}/status", response_model=BookingResponse)
def update_booking_status(
    booking_id: str,
    body: _StatusBody,
    current_user: User = Depends(get_current_user_sync),
    booking_service: BookingService = Depends(get_booking_service),
):
    """🔄 Actualizar estado de una reserva (proveedor)."""
    try:
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        provider_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        new_status = body.status.upper()

        if new_status == "CONFIRMED":
            from app.schemas.booking import ConfirmBookingRequest
            return booking_service.confirm_booking(booking_id_int, provider_id, ConfirmBookingRequest())
        elif new_status in ("REJECTED", "CANCELLED"):
            from app.schemas.booking import CancelBookingRequest
            return booking_service.cancel_booking(
                booking_id_int, provider_id, CancelBookingRequest(reason="Rejected by provider")
            )
        elif new_status == "COMPLETED":
            return booking_service.complete_booking(booking_id_int, provider_id)
        else:
            raise HTTPException(status_code=400, detail=f"Estado no soportado: {body.status}")
    except HTTPException:
        raise
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/available-slots")
def get_available_slots(
    provider_id: int = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
    slot_duration: int = Query(60),
    current_user: User = Depends(get_current_user_sync),
    db: Session = Depends(get_db),
):
    """⏰ Slots disponibles para un proveedor en una fecha."""
    from datetime import date as date_type, time as time_type
    from app.models.provider import ProviderWorkingHours
    from app.models.booking import Booking as BookingModel

    try:
        query_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa YYYY-MM-DD.")

    day_of_week = query_date.weekday()
    wh = (
        db.query(ProviderWorkingHours)
        .filter(
            ProviderWorkingHours.provider_id == provider_id,
            ProviderWorkingHours.day_of_week == day_of_week,
            ProviderWorkingHours.is_active == True,
        )
        .first()
    )

    if not wh:
        return {"date": date, "provider_id": provider_id, "available_slots": [], "total_available": 0, "slot_duration": slot_duration}

    def _t2m(t): return t.hour * 60 + t.minute
    def _m2s(m): return f"{m // 60:02d}:{m % 60:02d}"

    start_min, end_min = _t2m(wh.start_time), _t2m(wh.end_time)
    all_slots = []
    cur = start_min
    while cur + slot_duration <= end_min:
        all_slots.append(_m2s(cur))
        cur += slot_duration

    occupied = db.query(BookingModel).filter(
        BookingModel.provider_id == provider_id,
        BookingModel.scheduled_date == query_date,
        BookingModel.status.in_(["PENDING", "CONFIRMED", "IN_PROGRESS"]),
    ).all()

    blocked = set()
    for b in occupied:
        if b.scheduled_time:
            base = _t2m(b.scheduled_time)
            dur = b.duration or slot_duration
            for off in range(0, dur, slot_duration):
                blocked.add(base + off)

    available = [s for s in all_slots if _t2m(time_type.fromisoformat(s)) not in blocked]
    return {
        "date": date,
        "provider_id": provider_id,
        "slot_duration": slot_duration,
        "available_slots": available,
        "total_available": len(available),
    }


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
