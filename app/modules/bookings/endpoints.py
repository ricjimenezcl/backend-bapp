"""
Endpoints API para el sistema de reservas (Booking)
FastAPI routes para crear, actualizar y gestionar reservas
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, List
import logging

from app.core.database import get_db_async
from app.dependencies import get_current_user
from app.services.booking_service import BookingService
from app.infra.event_bus import event_bus
from app.schemas.booking import (
    CreateBookingRequest, ConfirmBookingRequest, CancelBookingRequest,
    BookingResponse, BookingDetailResponse, BookingListResponse,
    CheckAvailabilityResponse, ServiceAvailabilityRequest, ServiceAvailabilityResponse,
    CreateBookingNoteRequest, BookingNoteResponse
)
from app.models.user import User
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bookings", tags=["bookings"])


# ============================================================================
# HELPER: Obtener booking service
# ============================================================================

async def get_booking_service(db: AsyncSession = Depends(get_db_async)) -> BookingService:
    """Dependencia para obtener el servicio de bookings"""
    return BookingService(db, event_bus)


# ============================================================================
# CREAR RESERVAS
# ============================================================================

@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: CreateBookingRequest,
    current_user: User = Depends(get_current_user),
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
        booking_response = await booking_service.create_booking_from_email(current_user.email, request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error creando reserva: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creando la reserva"
        )

    # Enviar emails al cliente y proveedor (non-blocking)
    try:
        from sqlalchemy.future import select as _select
        from app.models.provider import Provider as _Provider
        from app.models.user import User as _User

        provider_id_val = int(booking_response.provider_id)
        booking_id_val = int(booking_response.id)

        # providers.id → providers.user_id → users.email
        prov_row = await booking_service.db.execute(_select(_Provider).where(_Provider.id == provider_id_val))
        prov_obj = prov_row.scalar_one_or_none()
        if prov_obj:
            user_row = await booking_service.db.execute(_select(_User).where(_User.id == prov_obj.user_id))
            provider_user = user_row.scalar_one_or_none()
            if provider_user:
                booking_data = {
                    "id": booking_id_val,
                    "scheduled_date": str(booking_response.scheduled_date) if booking_response.scheduled_date else None,
                    "scheduled_time": str(booking_response.scheduled_time) if booking_response.scheduled_time else None,
                    "service_category": getattr(booking_response, "service_category", "GENERAL"),
                    "location_address": getattr(booking_response, "location_address", ""),
                    "description": getattr(booking_response, "description", None),
                    "total_price": str(booking_response.total_price) if booking_response.total_price else "0",
                }
                provider_data = {
                    "id": provider_user.id,
                    "email": provider_user.email,
                    "full_name": provider_user.full_name,
                    "phone_number": getattr(provider_user, "phone_number", None),
                }
                client_data = {
                    "id": current_user.id,
                    "email": current_user.email,
                    "full_name": current_user.full_name,
                }
                from app.services.notification_helpers import create_task_notify_booking_created_data
                create_task_notify_booking_created_data(booking_data, provider_data, client_data)
                logger.info(f"📢 Email task creado para booking {booking_id_val} → proveedor {provider_user.email}, cliente {current_user.email}")
        else:
            logger.warning(f"⚠️ Provider id={provider_id_val} no encontrado en tabla providers")
    except Exception as e:
        logger.error(f"⚠️ Error enviando emails de reserva: {str(e)}")

    return booking_response


# ============================================================================
# OBTENER RESERVAS POR CLIENTE (DEBE IR ANTES DE /{booking_id})
# ============================================================================

@router.get("/client/{client_id}", response_model=BookingListResponse)
async def get_client_bookings(
    client_id: int,
    current_user: User = Depends(get_current_user),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    📋 Obtener todas las reservas de un cliente

    Solo el cliente puede ver sus propias reservas.
    SECURITY: Usa SIEMPRE el ID del usuario autenticado (token), NO el parámetro
    """
    try:
        current_user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        bookings = await booking_service.get_bookings_for_client(current_user_id)
        return BookingListResponse(
            total=len(bookings),
            page=1,
            size=len(bookings),
            items=bookings
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ============================================================================
# OBTENER RESERVAS
# ============================================================================

@router.get("/provider", response_model=List[BookingResponse])
async def get_provider_bookings(
    current_user: User = Depends(get_current_user),
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
        return await booking_service.get_bookings_for_provider(provider_id)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error obteniendo reservas del proveedor: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo reservas: {str(e)}"
        )


@router.get("/my-bookings", response_model=List[BookingResponse])
async def get_my_bookings(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    booking_service: BookingService = Depends(get_booking_service),
):
    """📋 Mis reservas (cliente). Alias de /bookings/client/{id} que devuelve lista plana."""
    user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
    bookings = await booking_service.get_bookings_for_client(user_id)
    if status_filter:
        bookings = [b for b in bookings if b.status.lower() == status_filter.lower()]
    return bookings


@router.get("/provider-bookings", response_model=List[BookingResponse])
async def get_provider_bookings_alias(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    booking_service: BookingService = Depends(get_booking_service),
):
    """📋 Reservas del proveedor. Alias de /bookings/provider que devuelve lista plana."""
    if current_user.role != "PROVIDER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo proveedores")
    provider_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
    bookings = await booking_service.get_bookings_for_provider(provider_id)
    if status_filter:
        bookings = [b for b in bookings if b.status.lower() == status_filter.lower()]
    return bookings


@router.get("/available-slots")
async def get_available_slots(
    provider_id: int = Query(...),
    date: str = Query(..., description="YYYY-MM-DD"),
    slot_duration: int = Query(60),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async),
):
    """⏰ Slots disponibles para un proveedor en una fecha."""
    from datetime import date as date_type, time as time_type
    from sqlalchemy import select
    from app.models.provider import ProviderWorkingHours
    from app.models.booking import Booking as BookingModel

    try:
        query_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa YYYY-MM-DD.")

    day_of_week = query_date.weekday()
    wh_result = await db.execute(
        select(ProviderWorkingHours).where(
            ProviderWorkingHours.provider_id == provider_id,
            ProviderWorkingHours.day_of_week == day_of_week,
            ProviderWorkingHours.is_active == True,
        )
    )
    wh = wh_result.scalar_one_or_none()

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

    occupied_result = await db.execute(
        select(BookingModel).where(
            BookingModel.provider_id == provider_id,
            BookingModel.scheduled_date == query_date,
            BookingModel.status.in_(["PENDING", "CONFIRMED", "IN_PROGRESS"]),
        )
    )
    occupied = occupied_result.scalars().all()

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
# AVAILABILITY CHECK + SET
# ============================================================================

@router.get("/availability/check", response_model=CheckAvailabilityResponse)
async def check_availability(
    provider_id: str,
    service_id: str,
    scheduled_date: str,  # YYYY-MM-DD
    scheduled_time: str,  # HH:MM
    duration: int,
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    🔍 Verificar disponibilidad de un proveedor

    Query params:
    - **provider_id**: UUID del proveedor
    - **service_id**: UUID del servicio
    - **scheduled_date**: Fecha (YYYY-MM-DD)
    - **scheduled_time**: Hora (HH:MM)
    - **duration**: Duración en minutos
    """
    try:
        from datetime import date, time
        date_obj = date.fromisoformat(scheduled_date)
        hour, minute = map(int, scheduled_time.split(':'))
        time_obj = time(hour, minute)
        provider_id_int = int(provider_id) if isinstance(provider_id, str) else provider_id
        service_id_int = int(service_id) if isinstance(service_id, str) else service_id
        return await booking_service.check_availability(
            provider_id_int, service_id_int, date_obj, time_obj, duration
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato inválido: {str(e)}"
        )


@router.post("/availability/set", response_model=ServiceAvailabilityResponse)
async def set_availability(
    request: ServiceAvailabilityRequest,
    current_user: User = Depends(get_current_user),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    🕐 Configurar disponibilidad del proveedor

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
        return await booking_service.set_availability(provider_id, request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ============================================================================
# LISTAR RESERVAS
# ============================================================================

@router.get("", response_model=BookingListResponse)
async def list_bookings(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
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
        result = await booking_service.list_bookings(user_id, current_user.role, page, size, status)
        return BookingListResponse(
            total=result["total"],
            page=result["page"],
            size=result["size"],
            items=result["items"]
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ============================================================================
# DETALLE
# ============================================================================

@router.get("/{booking_id}", response_model=BookingDetailResponse)
async def get_booking(
    booking_id: str,
    current_user: User = Depends(get_current_user),
    booking_service: BookingService = Depends(get_booking_service)
):
    """
    📋 Obtener detalles de una reserva específica

    Solo el cliente y el proveedor pueden ver los detalles.
    """
    try:
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        current_user_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        return await booking_service.get_booking(booking_id_int, current_user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ============================================================================
# ACTUALIZAR ESTADOS
# ============================================================================

@router.post("/{booking_id}/confirm", response_model=BookingResponse)
async def confirm_booking(
    booking_id: str,
    request: ConfirmBookingRequest,
    current_user: User = Depends(get_current_user),
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
        return await booking_service.confirm_booking(booking_id_int, provider_id, request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: str,
    request: CancelBookingRequest,
    current_user: User = Depends(get_current_user),
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
        return await booking_service.cancel_booking(booking_id_int, user_id, request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


class BookingStatusUpdate(BaseModel):
    status: str  # confirmed | rejected | in_progress | completed | cancelled


@router.put("/{booking_id}/status", response_model=BookingResponse)
async def update_booking_status(
    booking_id: str,
    body: BookingStatusUpdate,
    current_user: User = Depends(get_current_user),
    booking_service: BookingService = Depends(get_booking_service),
):
    """🔄 Actualizar estado de una reserva (proveedor)."""
    try:
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        provider_id = int(current_user.id) if isinstance(current_user.id, str) else current_user.id
        new_status = body.status.upper()

        if new_status == "CONFIRMED":
            return await booking_service.confirm_booking(
                booking_id_int, provider_id, ConfirmBookingRequest()
            )
        elif new_status in ("REJECTED", "CANCELLED"):
            return await booking_service.cancel_booking(
                booking_id_int, provider_id, CancelBookingRequest(reason="Rejected by provider")
            )
        elif new_status == "COMPLETED":
            return await booking_service.complete_booking(booking_id_int, provider_id)
        else:
            raise HTTPException(status_code=400, detail=f"Estado no soportado: {body.status}")
    except HTTPException:
        raise
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# NOTAS
# ============================================================================

@router.post("/{booking_id}/notes", response_model=BookingNoteResponse, status_code=status.HTTP_201_CREATED)
async def add_note(
    booking_id: str,
    request: CreateBookingNoteRequest,
    current_user: User = Depends(get_current_user),
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
        return await booking_service.add_note(booking_id_int, user_id, request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


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
