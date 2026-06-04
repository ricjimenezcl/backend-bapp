from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_
from typing import List
from datetime import datetime, date, time, timedelta
import logging

from app.core.database import get_db_async
from app.dependencies import get_current_active_user, get_current_provider_user # Asumiendo existencia o usando get_current_active_user + check
from app.models.user import User
from app.models.booking import Booking
from app.models.provider import Provider, ProviderWorkingHours
from app.schemas.booking import BookingCreate, BookingResponse
from app.services.booking_service import BookingService
from app.services.premium_service import PremiumService
from app.core.redis import cache_get, cache_set, rate_limit
from app.infra.pubsub import publish_booking_event
from app.infra.redis import invalidate_client_bookings_cache, invalidate_provider_bookings_cache, invalidate_slots_cache

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/client/{client_id}", response_model=List[BookingResponse])
async def get_client_bookings(
    client_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener reservas del cliente (Solo Clientes - pueden ver solo sus propias reservas)
    
    SECURITY NOTE: 
    - Ignora el client_id del parámetro
    - Usa SOLO el current_user.id del token JWT
    - Evita que usuarios intenten acceder a reservas ajenas manipulando la URL
    """
    if current_user.role != "CLIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only clients can access this endpoint"
        )
    
    # Security: Usar SIEMPRE el ID del usuario autenticado, NO el parámetro
    # Esto evita errores 403 cuando el parámetro no coincide con el token
    from sqlalchemy.future import select
    from sqlalchemy import desc
    
    # Rate limiting por usuario (10 req/min)
    rl_key = f"rate:bookings:client:{current_user.id}"
    if not rate_limit(rl_key, 10, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Cache key por usuario
    cache_key = f"bookings:client:{current_user.id}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    # Usar query async para obtener reservas
    result = await db.execute(
        select(Booking)
        .where(Booking.client_id == current_user.id)
        .order_by(desc(Booking.created_at))
    )
    bookings = result.scalars().all()
    
    # Convertir a responses
    booking_service = BookingService(db)
    responses = [booking_service._booking_to_response(booking) for booking in bookings]
    cache_set(cache_key, [r.model_dump(mode='json') for r in responses], ttl=30)
    return responses


@router.get("/provider", response_model=List[BookingResponse])
async def get_provider_bookings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener reservas asignadas a mis servicios (Solo Proveedores)
    """
    if current_user.role != "PROVIDER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can access this endpoint"
        )
    
    # Rate limiting por usuario (10 req/min)
    rl_key = f"rate:bookings:provider:{current_user.id}"
    if not rate_limit(rl_key, 10, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")

    # Cache key por proveedor
    cache_key = f"bookings:provider:{current_user.id}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    booking_service = BookingService(db)
    # Security: Resolve provider inside service using current_user.id
    responses = await booking_service.get_bookings_for_provider(current_user.id)
    cache_set(cache_key, [r.model_dump(mode='json') if hasattr(r, 'model_dump') else r for r in responses], ttl=30)
    return responses




@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    booking_in: BookingCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Crear una nueva solicitud de reserva (Clientes y Proveedores como clientes)
    Dispatch SMS, WhatsApp, y in-app notifications al proveedor
    ⚠️ PREMIUM ACCESS PROTECTED for clients
    """
    # Permitir que tanto CLIENTs como PROVIDERs creen reservas
    if current_user.role not in ["CLIENT", "PROVIDER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only clients and providers can create bookings"
        )
    
    # Validar acceso premium si es cliente
    if current_user.role == "CLIENT":
        premium_service = PremiumService(db)
        await premium_service.validate_provider_access(
            client_id=current_user.id,
            provider_id=booking_in.provider_id
        )
    
    logger.info(f"[BOOKING] Creating booking - Client: {current_user.id}, Provider: {booking_in.provider_id}, Service: {booking_in.service_id}")

    # Delegar completamente al servicio (fuente única de verdad)
    try:
        from app.schemas.booking import CreateBookingRequest
        booking_service = BookingService(db)
        booking_response = await booking_service.create_booking(
            client_id=current_user.id,
            request=CreateBookingRequest(
                provider_id=booking_in.provider_id,
                service_id=booking_in.service_id,
                service_provider_id=booking_in.service_provider_id,
                scheduled_date=booking_in.scheduled_date,
                scheduled_time=booking_in.scheduled_time,
                duration=booking_in.duration,
                total_price=booking_in.total_price,
                description=booking_in.description,
                location_address=booking_in.location_address,
                location_lat=booking_in.location_lat,
                location_lng=booking_in.location_lng,
                service_category=booking_in.service_category,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Error creando reserva: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Error al crear la reserva: {str(e)}")

    # Obtener id del booking creado para eventos y cache
    new_booking_id = int(booking_response.id if hasattr(booking_response, 'id') else booking_response.get('id', 0))
    provider_id_val = int(booking_response.provider_id if hasattr(booking_response, 'provider_id') else booking_response.get('provider_id', 0))

    # Emit event (non-blocking)
    try:
        from app.services.event_dispatcher import get_dispatcher, EventType
        dispatcher = get_dispatcher()
        await dispatcher.emit(EventType.BOOKING_CREATED, {
            "booking_id": new_booking_id,
            "client_id": current_user.id,
            "provider_id": provider_id_val,
            "service_name": booking_in.service_category or "GENERAL",
            "scheduled_date": str(booking_in.scheduled_date) if booking_in.scheduled_date else "Not specified",
            "price": float(booking_in.total_price) if booking_in.total_price else 0,
            "description": booking_in.description,
        })
    except Exception as e:
        logger.error(f"⚠️ Error emitting booking created event: {str(e)}")

    # Publish to Redis pub/sub
    try:
        publish_booking_event(
            client_id=current_user.id,
            provider_id=provider_id_val,
            event_type="booking.created",
            payload={"booking_id": new_booking_id, "status": "PENDING"},
        )
        invalidate_client_bookings_cache(current_user.id)
        invalidate_provider_bookings_cache(provider_id_val)
        invalidate_slots_cache(provider_id_val)
    except Exception as e:
        logger.error(f"⚠️ Error publishing booking.created to Redis: {str(e)}")

    # Dispatch notifications (non-blocking)
    try:
        from app.services.notification_helpers import create_task_notify_booking_created
        from sqlalchemy.future import select as _select
        provider_row = await db.execute(_select(User).where(User.id == provider_id_val))
        provider_user = provider_row.scalar_one_or_none()
        if provider_user:
            from app.models.booking import Booking as _Booking
            booking_row = await db.execute(_select(_Booking).where(_Booking.id == new_booking_id))
            booking_obj = booking_row.scalar_one_or_none()
            if booking_obj:
                create_task_notify_booking_created(booking_obj, provider_user, current_user, db)
    except Exception as e:
        logger.error(f"⚠️ Error dispatching booking created notifications: {str(e)}")

    return booking_response


@router.patch("/{booking_id}/accept", response_model=BookingResponse)
async def accept_booking(
    booking_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Aceptar una reserva (Solo Proveedor dueño del servicio)
    Dispatch SMS, WhatsApp, y in-app notifications
    """
    if current_user.role != "PROVIDER":
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can accept bookings"
        )
        
    booking_service = BookingService(db)
    result = await booking_service.accept_booking_with_notifications(booking_id, current_user.id, db)
    
    # Publish to Redis pub/sub
    try:
        publish_booking_event(
            client_id=result.client_id if hasattr(result, 'client_id') else int(result.get('client_id', 0)),
            provider_id=current_user.id,
            event_type="booking.accepted",
            payload={"booking_id": booking_id, "status": "APPROVED"}
        )
        invalidate_client_bookings_cache(int(result.client_id if hasattr(result, 'client_id') else result.get('client_id', 0)))
        invalidate_provider_bookings_cache(current_user.id)
        invalidate_slots_cache(current_user.id)
    except Exception as e:
        logger.error(f"⚠️ Redis publish booking.accepted error: {e}")
    
    return result


@router.post("/{booking_id}/approve", response_model=BookingResponse)
async def approve_booking(
    booking_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Aprobar una reserva — semántico (alias de /accept).
    PENDING → APPROVED
    """
    if current_user.role != "PROVIDER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can approve bookings"
        )
    booking_service = BookingService(db)
    result = await booking_service.accept_booking_with_notifications(booking_id, current_user.id, db)
    try:
        publish_booking_event(
            client_id=result.client_id if hasattr(result, 'client_id') else int(result.get('client_id', 0)),
            provider_id=current_user.id,
            event_type="booking.approved",
            payload={"booking_id": booking_id, "status": "APPROVED"}
        )
        invalidate_client_bookings_cache(int(result.client_id if hasattr(result, 'client_id') else result.get('client_id', 0)))
        invalidate_provider_bookings_cache(current_user.id)
        invalidate_slots_cache(current_user.id)
    except Exception as e:
        logger.error(f"⚠️ Redis publish booking.approved error: {e}")
    return result


@router.post("/{booking_id}/confirm", response_model=BookingResponse)
async def confirm_booking_compat(
    booking_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Alias de /approve para compatibilidad con clientes anteriores.
    Deprecado: usar POST /{id}/approve.
    """
    if current_user.role != "PROVIDER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can confirm bookings"
        )
    booking_service = BookingService(db)
    result = await booking_service.accept_booking_with_notifications(booking_id, current_user.id, db)
    try:
        invalidate_client_bookings_cache(int(result.client_id if hasattr(result, 'client_id') else result.get('client_id', 0)))
        invalidate_provider_bookings_cache(current_user.id)
        invalidate_slots_cache(current_user.id)
    except Exception as e:
        logger.error(f"⚠️ Cache invalidation error on confirm: {e}")
    return result


@router.patch("/{booking_id}/reject", response_model=BookingResponse)
async def reject_booking(
    booking_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Rechazar una reserva (Solo Proveedor dueño del servicio)
    Dispatch SMS, WhatsApp, y in-app notifications
    """
    if current_user.role != "PROVIDER":
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can reject bookings"
        )

    # Body opcional con motivo de rechazo
    body: dict = {}
    try:
        from fastapi import Request
        pass  # reason_comment viene por query param o body
    except Exception:
        pass

    booking_service = BookingService(db)
    result = await booking_service.reject_booking_with_notifications(booking_id, current_user.id, db_session=db)
    
    # Publish to Redis pub/sub
    try:
        publish_booking_event(
            client_id=result.client_id if hasattr(result, 'client_id') else int(result.get('client_id', 0)),
            provider_id=current_user.id,
            event_type="booking.rejected",
            payload={"booking_id": booking_id, "status": "REJECTED"}
        )
        invalidate_client_bookings_cache(int(result.client_id if hasattr(result, 'client_id') else result.get('client_id', 0)))
        invalidate_provider_bookings_cache(current_user.id)
        invalidate_slots_cache(current_user.id)
    except Exception as e:
        logger.error(f"⚠️ Redis publish booking.rejected error: {e}")
    
    return result


@router.patch("/{booking_id}/complete", response_model=BookingResponse)
async def complete_booking(
    booking_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Marcar reserva como Completada (Solo Proveedores).
    Notifica al cliente que su reserva fue completada.
    """
    if current_user.role != "PROVIDER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can complete bookings"
        )

    booking_service = BookingService(db)
    result = await booking_service.complete_booking(booking_id, current_user.id)

    # Extraer client_id del resultado
    client_id = (
        result.client_id if hasattr(result, "client_id")
        else int(result.get("client_id", 0))
    )

    # Publish to Redis pub/sub
    try:
        publish_booking_event(
            client_id=client_id,
            provider_id=current_user.id,
            event_type="booking.completed",
            payload={"booking_id": booking_id, "status": "COMPLETED"}
        )
        invalidate_client_bookings_cache(client_id)
        invalidate_provider_bookings_cache(current_user.id)
        invalidate_slots_cache(current_user.id)
    except Exception as e:
        logger.error(f"⚠️ Redis publish booking.completed error: {e}")

    # Notificación in-app al cliente (BOOKING_COMPLETED)
    if client_id:
        try:
            from app.services.notification_service import NotificationService
            from app.models.notification import NotificationType
            from app.api.websocket.connection_manager import connection_manager
            from app.infra.pubsub import publish_to_user

            notif_service = NotificationService(db)
            notif = await notif_service.create_notification(
                user_id=client_id,
                notification_type=NotificationType.BOOKING_COMPLETED,
                title="Reserva completada",
                content=f"Tu reserva #{booking_id} fue marcada como completada. ¡No olvides dejar una reseña!",
                related_entity_type="booking",
                related_entity_id=booking_id,
            )
            ws_payload = {
                "type": "notification",
                "notificationId": notif.id,
                "notificationType": NotificationType.BOOKING_COMPLETED.value,
                "title": notif.title,
                "content": notif.content,
                "relatedEntityType": "booking",
                "relatedEntityId": booking_id,
            }
            if connection_manager.is_user_online(client_id):
                import asyncio
                asyncio.create_task(connection_manager.broadcast_to_user(client_id, ws_payload))
            else:
                import asyncio
                asyncio.create_task(publish_to_user(client_id, ws_payload))
        except Exception as e:
            logger.warning(f"[BOOKING] BOOKING_COMPLETED notification error (non-critical): {e}")

    # Dispatch SII receipt asynchronously — desacoplado del path de pago
    try:
        from app.services.sii_service import dispatch_sii_receipt_async
        from sqlalchemy.future import select as _select
        from app.models.booking import Booking as _Booking
        from app.models.provider import Provider as _Provider
        from app.models.user import User as _User

        booking_row = await db.execute(_select(_Booking).where(_Booking.id == booking_id))
        booking_obj = booking_row.scalar_one_or_none()
        if booking_obj:
            prov_row = await db.execute(_select(_Provider).where(_Provider.id == booking_obj.provider_id))
            prov_obj = prov_row.scalar_one_or_none()
            client_row = await db.execute(_select(_User).where(_User.id == booking_obj.client_id))
            client_obj = client_row.scalar_one_or_none()
            import asyncio as _asyncio
            _asyncio.create_task(dispatch_sii_receipt_async(
                booking_id=booking_id,
                provider_rut=getattr(prov_obj, 'run', '') or '',
                provider_business_name=getattr(prov_obj, 'full_name', '') or '',
                provider_service_category=booking_obj.service_category or 'GENERAL',
                provider_address=booking_obj.location_address or '',
                client_rut='',
                client_name=getattr(client_obj, 'full_name', '') or getattr(client_obj, 'email', '') or '',
                client_address=booking_obj.location_address or '',
                service_name=booking_obj.service_category or 'GENERAL',
                amount=float(booking_obj.total_price or 0),
                db=db,
            ))
    except Exception as e:
        logger.warning(f"[SII] Error preparando dispatch de boleta (non-critical): {e}")

    return result


@router.get("/available-slots")
async def get_available_slots(
    provider_id: int = Query(..., description="ID del proveedor"),
    date_str: str = Query(..., alias="date", description="Fecha en formato YYYY-MM-DD"),
    slot_duration: int = Query(60, description="Duración del slot en minutos (default 60)"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async),
):
    """
    Retorna los slots de tiempo disponibles para un proveedor en una fecha dada.

    Algoritmo:
      1. Obtiene el horario laboral del proveedor para ese día de la semana.
      2. Genera slots de `slot_duration` minutos dentro del horario.
      3. Resta los slots ya ocupados por reservas PENDING/APPROVED/CONFIRMED/IN_PROGRESS.
    """
    # Validar fecha
    try:
        query_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa YYYY-MM-DD.")

    if query_date < date.today():
        raise HTTPException(status_code=400, detail="No se pueden consultar slots para fechas pasadas.")

    # Cache
    cache_key = f"slots:{provider_id}:{date_str}:{slot_duration}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    # 1. Horario laboral del proveedor para ese día (0=Lunes … 6=Domingo)
    day_of_week = query_date.weekday()
    hours_result = await db.execute(
        select(ProviderWorkingHours).where(
            and_(
                ProviderWorkingHours.provider_id == provider_id,
                ProviderWorkingHours.day_of_week == day_of_week,
                ProviderWorkingHours.is_active == True,
            )
        )
    )
    working_hours = hours_result.scalar_one_or_none()

    if working_hours is None:
        result = {"date": date_str, "provider_id": provider_id, "slots": [], "reason": "El proveedor no trabaja ese día."}
        cache_set(cache_key, result, ttl=300)
        return result

    # 2. Generar todos los slots del día
    def time_to_minutes(t: time) -> int:
        return t.hour * 60 + t.minute

    def minutes_to_time_str(minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    start_min = time_to_minutes(working_hours.start_time)
    end_min = time_to_minutes(working_hours.end_time)
    all_slots: list[str] = []
    current_min = start_min
    while current_min + slot_duration <= end_min:
        all_slots.append(minutes_to_time_str(current_min))
        current_min += slot_duration

    # 3. Reservas ya ocupadas ese día para ese proveedor
    bookings_result = await db.execute(
        select(Booking).where(
            and_(
                Booking.provider_id == provider_id,
                Booking.scheduled_date == query_date,
                Booking.status.in_(["PENDING", "APPROVED", "CONFIRMED", "IN_PROGRESS"]),
            )
        )
    )
    occupied_bookings = bookings_result.scalars().all()

    occupied_start_minutes: set[int] = set()
    for b in occupied_bookings:
        if b.scheduled_time:
            occupied_start_minutes.add(time_to_minutes(b.scheduled_time))
            # Marcar todos los slots que caen dentro de la duración de la reserva
            duration_min = b.duration or slot_duration
            for offset in range(0, duration_min, slot_duration):
                occupied_start_minutes.add(time_to_minutes(b.scheduled_time) + offset)

    available_slots = [s for s in all_slots if int(s.split(":")[0]) * 60 + int(s.split(":")[1]) not in occupied_start_minutes]

    result = {
        "date": date_str,
        "provider_id": provider_id,
        "working_hours": {
            "start": working_hours.start_time.strftime("%H:%M"),
            "end": working_hours.end_time.strftime("%H:%M"),
        },
        "slot_duration_minutes": slot_duration,
        "slots": available_slots,
        "total_available": len(available_slots),
    }
    cache_set(cache_key, result, ttl=60)
    return result


@router.delete("/{booking_id}", response_model=BookingResponse)
async def cancel_booking(
    booking_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Cancelar una reserva (Solo el cliente que la creó)
    """
    booking_service = BookingService(db)
    result = await booking_service.cancel_booking_by_client(booking_id, current_user.id)
    try:
        provider_id = int(result.provider_id if hasattr(result, 'provider_id') else result.get('provider_id', 0))
        invalidate_client_bookings_cache(current_user.id)
        invalidate_provider_bookings_cache(provider_id)
        invalidate_slots_cache(provider_id)
    except Exception as e:
        logger.error(f"⚠️ Cache invalidation error on cancel: {e}")
    return result
