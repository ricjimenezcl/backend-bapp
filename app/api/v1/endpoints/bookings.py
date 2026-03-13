from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List
from datetime import datetime
import logging

from app.core.database import get_db_async
from app.dependencies import get_current_active_user, get_current_provider_user # Asumiendo existencia o usando get_current_active_user + check
from app.models.user import User
from app.models.booking import Booking
from app.models.provider import Provider, ProviderWorkingHours
from app.models.service_category import ServiceCategory
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
    cache_set(cache_key, responses, ttl=30)
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
    cache_set(cache_key, responses, ttl=30)
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
    
    # Validar que el proveedor exista (async)
    result = await db.execute(
        select(Provider).where(Provider.id == booking_in.provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proveedor no encontrado con ID: {booking_in.provider_id}"
        )
    
    # Validar que la categoría de servicio exista (async)
    result = await db.execute(
        select(ServiceCategory).where(ServiceCategory.id == booking_in.service_id)
    )
    service_cat = result.scalar_one_or_none()
    if not service_cat:
        logger.warning(f"[BOOKING] ServiceCategory not found: {booking_in.service_id}, proceeding anyway")

    # Validar horario del proveedor si tiene horarios definidos
    if booking_in.scheduled_date and booking_in.scheduled_time:
        try:
            from datetime import date as date_type, time as time_type
            scheduled_date = (
                booking_in.scheduled_date
                if isinstance(booking_in.scheduled_date, date_type)
                else date_type.fromisoformat(str(booking_in.scheduled_date))
            )
            scheduled_time = (
                booking_in.scheduled_time
                if isinstance(booking_in.scheduled_time, time_type)
                else time_type.fromisoformat(str(booking_in.scheduled_time)[:5])
            )
            # 0=Lunes … 6=Domingo (Python weekday)
            day_of_week = scheduled_date.weekday()

            hours_result = await db.execute(
                select(ProviderWorkingHours).where(
                    ProviderWorkingHours.provider_id == booking_in.provider_id,
                    ProviderWorkingHours.day_of_week == day_of_week,
                    ProviderWorkingHours.is_active == True,
                )
            )
            provider_hours = hours_result.scalar_one_or_none()

            if provider_hours is not None:
                if not (provider_hours.start_time <= scheduled_time <= provider_hours.end_time):
                    from app.api.v1.endpoints.working_hours import DAY_NAMES
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"El proveedor no trabaja el {DAY_NAMES[day_of_week]} a esa hora. "
                            f"Horario disponible: {provider_hours.start_time.strftime('%H:%M')} - "
                            f"{provider_hours.end_time.strftime('%H:%M')}"
                        ),
                    )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[BOOKING] Error validando horario proveedor (non-critical): {e}")

    # Crear la reserva directamente con async session
    try:
        new_booking = Booking(
            client_id=current_user.id,
            provider_id=booking_in.provider_id,
            service_id=booking_in.service_id,
            service_provider_id=booking_in.service_provider_id,
            scheduled_date=booking_in.scheduled_date,
            scheduled_time=booking_in.scheduled_time,
            duration=booking_in.duration,
            description=booking_in.description,
            total_price=booking_in.total_price,
            price=booking_in.total_price,  # campo legacy
            status='PENDING',
            location_address=booking_in.location_address or "",
            location_lat=booking_in.location_lat,
            location_lng=booking_in.location_lng,
            service_category=booking_in.service_category or (service_cat.name if service_cat else "GENERAL"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db.add(new_booking)
        await db.flush()
        
        logger.info(f"[BOOKING] Booking flushed with ID: {new_booking.id}")
        
        await db.commit()
        await db.refresh(new_booking)
        
        logger.info(f"✅ Reserva creada exitosamente: {new_booking.id}")
        
        # Construir response
        booking_response = BookingResponse(
            id=str(new_booking.id),
            client_id=str(new_booking.client_id),
            provider_id=str(new_booking.provider_id),
            service_id=str(new_booking.service_id) if new_booking.service_id else "",
            scheduled_date=new_booking.scheduled_date,
            scheduled_time=new_booking.scheduled_time,
            duration=new_booking.duration or 0,
            description=new_booking.description,
            total_price=new_booking.total_price or 0,
            currency=new_booking.currency or "CLP",
            status=new_booking.status,
            created_at=new_booking.created_at,
            updated_at=new_booking.updated_at,
            completed_at=new_booking.completed_at,
            service_provider_id=new_booking.service_provider_id,
            location_address=new_booking.location_address,
            location_lat=float(new_booking.location_lat) if new_booking.location_lat else None,
            location_lng=float(new_booking.location_lng) if new_booking.location_lng else None,
            service_category=new_booking.service_category
        )
        
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error creando reserva: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error al crear la reserva: {str(e)}"
        )
    
    # Emit event for notification dispatcher (non-blocking)
    try:
        from app.services.event_dispatcher import get_dispatcher, EventType
        dispatcher = get_dispatcher()
        await dispatcher.emit(EventType.BOOKING_CREATED, {
            "booking_id": new_booking.id,
            "client_id": new_booking.client_id,
            "provider_id": new_booking.provider_id,
            "service_name": booking_in.service_category or "GENERAL",
            "scheduled_date": str(booking_in.scheduled_date) if booking_in.scheduled_date else "Not specified",
            "price": float(booking_in.total_price) if booking_in.total_price else 0,
            "description": booking_in.description
        })
    except Exception as e:
        logger.error(f"⚠️ Error emitting booking created event: {str(e)}")
    
    # Publish to Redis pub/sub (notifica al proveedor vía WS en tiempo real)
    try:
        publish_booking_event(
            client_id=new_booking.client_id,
            provider_id=new_booking.provider_id,
            event_type="booking.created",
            payload={
                "booking_id": new_booking.id,
                "service_name": booking_in.service_category or "GENERAL",
                "scheduled_date": str(booking_in.scheduled_date) if booking_in.scheduled_date else None,
                "status": "PENDING"
            }
        )
        # Invalida cache para que la próxima carga traiga datos actualizados
        invalidate_client_bookings_cache(new_booking.client_id)
        invalidate_provider_bookings_cache(new_booking.provider_id)
        invalidate_slots_cache(new_booking.provider_id)
    except Exception as e:
        logger.error(f"⚠️ Error publishing booking.created to Redis: {str(e)}")
    
    # Dispatch notifications asynchronously (non-blocking)
    try:
        from app.services.notification_helpers import create_task_notify_booking_created
        
        result = await db.execute(
            select(User).where(User.id == new_booking.provider_id)
        )
        provider_user = result.scalar_one_or_none()
        if provider_user:
            create_task_notify_booking_created(new_booking, provider_user, current_user, db)
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
            payload={"booking_id": booking_id, "status": "ACCEPTED"}
        )
        invalidate_client_bookings_cache(int(result.client_id if hasattr(result, 'client_id') else result.get('client_id', 0)))
        invalidate_provider_bookings_cache(current_user.id)
        invalidate_slots_cache(current_user.id)
    except Exception as e:
        logger.error(f"⚠️ Redis publish booking.accepted error: {e}")
    
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
        
    booking_service = BookingService(db)
    result = await booking_service.reject_booking_with_notifications(booking_id, current_user.id, db)
    
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
