# Constantes
RESERVA_NO_ENCONTRADA = "Reserva no encontrada"
"""
BookingService - Lógica de negocio para el sistema de reservas
Async-first: usa AsyncSession de SQLAlchemy 2.0
"""

from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
from typing import Optional, List, Tuple
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func

from app.models.booking import (
    Booking, BookingStatusHistory, BookingCancellation,
    ServiceAvailability, BookingNote, BookingStatus, CancellationReason, DayOfWeek
)
from app.models.user import User
from app.models.provider import Provider
from app.models.service_category import ServiceCategory
from app.schemas.booking import (
    CreateBookingRequest, ConfirmBookingRequest, CancelBookingRequest,
    BookingResponse, BookingDetailResponse, CheckAvailabilityResponse,
    ServiceAvailabilityRequest, ServiceAvailabilityResponse,
    CreateBookingNoteRequest, BookingNoteResponse
)
from app.infra.event_bus.bus import EventBus
from app.infra.event_bus.event import BookingCreatedEvent, BookingStatusChangedEvent


class BookingService:
    """Servicio async para manejar toda la lógica de reservas."""

    def __init__(self, db: AsyncSession, event_bus: Optional[EventBus] = None):
        self.db = db
        self.event_bus = event_bus

    # =========================================================================
    # HELPERS INTERNOS (sin await — solo session.add)
    # =========================================================================

    async def _resolve_provider_id(self, user_id: int) -> Optional[int]:
        """Resolve providers.id from users.id."""
        result = await self.db.execute(
            select(Provider).where(Provider.user_id == user_id)
        )
        provider = result.scalar_one_or_none()
        return provider.id if provider else None

    def _record_status_change(
        self,
        booking_id: int,
        previous_status: Optional[str],
        new_status: str,
        changed_by_id: int,
        reason: Optional[str] = None,
        reason_comment: Optional[str] = None,
    ):
        """Registrar cambio de estado (solo db.add — no commit)."""
        history = BookingStatusHistory(
            booking_id=booking_id,
            previous_status=previous_status,
            new_status=new_status,
            changed_by_id=changed_by_id,
            reason=reason,
            reason_comment=reason_comment,
        )
        self.db.add(history)

    def _add_note(self, booking_id: int, note_type: str, content: str, created_by_id: int):
        """Agregar nota (solo db.add — no commit)."""
        self.db.add(BookingNote(
            booking_id=booking_id,
            note_type=note_type,
            content=content,
            created_by_id=created_by_id,
        ))

    # =========================================================================
    # CREAR RESERVAS
    # =========================================================================

    async def create_booking_from_email(
        self, client_email: str, request: CreateBookingRequest
    ) -> BookingResponse:
        """Crear reserva a partir del email del cliente."""
        result = await self.db.execute(select(User).where(User.email == client_email))
        client = result.scalar_one_or_none()
        if not client:
            raise ValueError("Cliente no encontrado")
        if client.role != "CLIENT":
            raise ValueError(f"Solo los clientes pueden crear reservas. Tu rol es: {client.role}")
        return await self.create_booking(client.id, request)

    async def create_booking(
        self, client_id: int, request: CreateBookingRequest
    ) -> BookingResponse:
        """Crear una nueva reserva."""
        try:
            logger.info(
                f"[BOOKING] Creating booking — client={client_id}, "
                f"provider={request.provider_id}, service={request.service_id}"
            )

            # Validar cliente
            result = await self.db.execute(select(User).where(User.id == client_id))
            client = result.scalar_one_or_none()
            if not client:
                raise ValueError("Cliente no encontrado")
            if client.role != "CLIENT":
                raise ValueError(f"Solo los clientes pueden crear reservas. Tu rol es: {client.role}")

            # Validar proveedor
            result = await self.db.execute(
                select(Provider).where(Provider.id == request.provider_id)
            )
            if not result.scalar_one_or_none():
                raise ValueError("Proveedor no encontrado")

            # Crear reserva
            booking = Booking(
                client_id=client_id,
                provider_id=request.provider_id,
                service_id=request.service_id,
                scheduled_date=request.scheduled_date,
                scheduled_time=request.scheduled_time,
                duration=request.duration,
                description=request.description,
                total_price=request.total_price,
                status="PENDING",
                service_provider_id=request.service_provider_id,
                location_address=request.location_address or "",
                location_lat=request.location_lat,
                location_lng=request.location_lng,
                service_category=request.service_category or "GENERAL",
            )
            self.db.add(booking)
            await self.db.flush()

            logger.info(f"[BOOKING] Booking flushed with ID: {booking.id}")

            self._record_status_change(
                booking_id=booking.id,
                previous_status=None,
                new_status="PENDING",
                changed_by_id=int(client_id),
                reason="CREATED",
            )
            await self.db.commit()
            await self.db.refresh(booking)

            logger.info(f"[BOOKING] Booking committed: {booking.id}")

            if self.event_bus:
                self.event_bus.publish(BookingCreatedEvent(
                    booking_id=str(booking.id),
                    client_id=str(client_id),
                    provider_id=str(request.provider_id),
                    service_id=str(request.service_id),
                    scheduled_time=(
                        request.scheduled_time.isoformat() if request.scheduled_time else None
                    ),
                ))

            return self._booking_to_response(booking)

        except Exception:
            await self.db.rollback()
            logger.error("[BOOKING] Error creating booking", exc_info=True)
            raise

    # =========================================================================
    # OBTENER RESERVAS
    # =========================================================================

    async def get_booking(self, booking_id: int, user_id: int) -> BookingDetailResponse:
        """Obtener una reserva específica."""
        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)

        resolved_provider_id = await self._resolve_provider_id(user_id)
        if booking.client_id != user_id and booking.provider_id != resolved_provider_id:
            raise PermissionError("No tienes permiso para ver esta reserva")

        return self._booking_to_detail_response(booking)

    async def list_bookings(
        self,
        user_id: int,
        user_role: str,
        page: int = 1,
        size: int = 10,
        status: Optional[str] = None,
    ) -> dict:
        """Listar reservas según el rol del usuario."""
        stmt = select(Booking)

        if user_role == "CLIENT":
            stmt = stmt.where(Booking.client_id == user_id)
        elif user_role == "PROVIDER":
            resolved_provider_id = await self._resolve_provider_id(user_id)
            if not resolved_provider_id:
                return {"total": 0, "page": page, "size": size, "items": []}
            stmt = stmt.where(Booking.provider_id == resolved_provider_id)
        elif user_role != "ADMIN":
            raise PermissionError("Rol no autorizado")

        if status:
            stmt = stmt.where(Booking.status == BookingStatus[status])

        count_result = await self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = count_result.scalar()

        result = await self.db.execute(
            stmt.order_by(desc(Booking.created_at))
            .limit(size)
            .offset((page - 1) * size)
        )
        bookings = result.scalars().all()

        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [self._booking_to_response(b) for b in bookings],
        }

    async def get_bookings_for_client(self, client_id: int) -> List[BookingResponse]:
        """Obtener todas las reservas de un cliente."""
        try:
            result = await self.db.execute(
                select(Booking)
                .where(Booking.client_id == client_id)
                .order_by(desc(Booking.created_at))
            )
            bookings = result.scalars().all()
            logger.info(f"[BOOKING] Found {len(bookings)} bookings for client_id={client_id}")
            return [self._booking_to_response(b) for b in bookings]
        except Exception as e:
            logger.error(f"Error getting bookings for client {client_id}: {e}")
            return []

    async def get_bookings_for_provider(self, user_id: int) -> List[BookingResponse]:
        """Obtener todas las reservas asignadas a un proveedor (recibe users.id)."""
        try:
            result = await self.db.execute(
                select(Provider).where(Provider.user_id == user_id)
            )
            provider = result.scalar_one_or_none()
            if not provider:
                logger.warning(f"[BOOKING] No provider found for user_id={user_id}")
                return []

            result = await self.db.execute(
                select(Booking)
                .where(Booking.provider_id == provider.id)
                .order_by(desc(Booking.created_at))
            )
            bookings = result.scalars().all()
            logger.info(
                f"[BOOKING] Found {len(bookings)} bookings for provider.id={provider.id}"
            )
            return [self._booking_to_response(b) for b in bookings]
        except Exception as e:
            logger.error(f"Error getting bookings for provider user_id={user_id}: {e}")
            return []

    # =========================================================================
    # ACTUALIZAR ESTADOS
    # =========================================================================

    async def confirm_booking(
        self,
        booking_id: int,
        provider_user_id: int,
        request: ConfirmBookingRequest,
    ) -> BookingResponse:
        """Confirmar una reserva (provider_user_id es users.id)."""
        resolved_provider_id = await self._resolve_provider_id(provider_user_id)
        if not resolved_provider_id:
            raise PermissionError("No se encontró proveedor para este usuario")

        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede confirmar")
        if booking.status != "PENDING":
            raise ValueError(f"Estado inválido: {booking.status}")

        booking.status = "APPROVED"
        booking.updated_at = datetime.now(timezone.utc)
        self._record_status_change(
            booking_id=booking_id,
            previous_status="PENDING",
            new_status="APPROVED",
            changed_by_id=provider_user_id,
            reason="APPROVED_BY_PROVIDER",
        )
        if request.notes:
            self._add_note(booking_id, "INTERNAL", request.notes, provider_user_id)
        await self.db.commit()
        await self.db.refresh(booking)

        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status="PENDING",
                new_status="APPROVED",
                changed_by_id=str(provider_user_id),
            ))

        return self._booking_to_response(booking)

    async def cancel_booking(
        self,
        booking_id: int,
        user_id: int,
        request: CancelBookingRequest,
    ) -> BookingResponse:
        """Cancelar una reserva (user_id es users.id)."""
        resolved_provider_id = await self._resolve_provider_id(user_id)

        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        if booking.client_id != user_id and booking.provider_id != resolved_provider_id:
            raise PermissionError("No tienes permiso para cancelar")
        if booking.status == "COMPLETED":
            raise ValueError("No se puede cancelar una reserva completada")
        if booking.status == "CANCELLED":
            return self._booking_to_response(booking)

        previous_status = booking.status
        booking.status = "CANCELLED"
        booking.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(booking)

        # Registro de cancelación (no crítico)
        try:
            existing = await self.db.execute(
                select(BookingCancellation).where(
                    BookingCancellation.booking_id == booking_id
                )
            )
            if not existing.scalar_one_or_none():
                self.db.add(BookingCancellation(
                    booking_id=booking_id,
                    cancelled_by_id=user_id,
                    reason=request.reason.value,
                    reason_comment=request.reason_comment,
                ))
                await self.db.commit()
        except Exception as e:
            logger.warning(f"[CANCEL] BookingCancellation insert skipped: {e}")
            await self.db.rollback()

        try:
            self._record_status_change(
                booking_id=booking_id,
                previous_status=previous_status,
                new_status="CANCELLED",
                changed_by_id=user_id,
                reason=request.reason.value,
                reason_comment=request.reason_comment,
            )
            await self.db.commit()
        except Exception as e:
            logger.warning(f"[CANCEL] status_history insert skipped: {e}")
            await self.db.rollback()

        if self.event_bus:
            try:
                self.event_bus.publish(BookingStatusChangedEvent(
                    booking_id=str(booking_id),
                    previous_status=str(previous_status),
                    new_status="CANCELLED",
                    changed_by_id=str(user_id),
                ))
            except Exception as e:
                logger.warning(f"[CANCEL] event_bus publish skipped: {e}")

        return self._booking_to_response(booking)

    async def accept_booking(self, booking_id: int, user_id: int) -> BookingResponse:
        """Aceptar reserva: PENDING → CONFIRMED."""
        resolved_provider_id = await self._resolve_provider_id(user_id)

        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede aceptar")
        if booking.status != "PENDING":
            raise ValueError(f"Estado inválido: {booking.status}")

        booking.status = "APPROVED"
        booking.updated_at = datetime.now(timezone.utc)
        self._record_status_change(
            booking_id=booking_id,
            previous_status="PENDING",
            new_status="APPROVED",
            changed_by_id=user_id,
            reason="APPROVED_BY_PROVIDER",
        )
        await self.db.commit()
        await self.db.refresh(booking)

        if self.event_bus:
            try:
                self.event_bus.publish(BookingStatusChangedEvent(
                    booking_id=str(booking_id),
                    previous_status="PENDING",
                    new_status="APPROVED",
                    changed_by_id=str(user_id),
                ))
            except Exception as e:
                logger.warning(f"[ACCEPT] event_bus publish skipped: {e}")
        return self._booking_to_response(booking)

    async def reject_booking(self, booking_id: int, user_id: int) -> BookingResponse:
        """Rechazar reserva: PENDING → REJECTED."""
        resolved_provider_id = await self._resolve_provider_id(user_id)

        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede rechazar")
        if booking.status != "PENDING":
            raise ValueError(f"Estado inválido: {booking.status}")

        booking.status = "REJECTED"
        booking.updated_at = datetime.now(timezone.utc)
        self._record_status_change(
            booking_id=booking_id,
            previous_status="PENDING",
            new_status="REJECTED",
            changed_by_id=user_id,
            reason="REJECTED_BY_PROVIDER",
        )
        await self.db.commit()
        await self.db.refresh(booking)

        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status="PENDING",
                new_status="REJECTED",
                changed_by_id=str(user_id),
            ))
        return self._booking_to_response(booking)

    async def complete_booking(self, booking_id: int, user_id: int) -> BookingResponse:
        """Marcar reserva como completada."""
        resolved_provider_id = await self._resolve_provider_id(user_id)

        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede completar")
        if booking.status not in ["PENDING", "APPROVED", "CONFIRMED", "IN_PROGRESS"]:
            raise ValueError(f"No se puede completar una reserva en estado: {booking.status}")

        previous_status = booking.status
        booking.status = "COMPLETED"
        booking.completed_at = datetime.now(timezone.utc)
        booking.updated_at = datetime.now(timezone.utc)
        self._record_status_change(
            booking_id=booking_id,
            previous_status=previous_status,
            new_status="COMPLETED",
            changed_by_id=user_id,
            reason="COMPLETED_BY_PROVIDER",
        )
        await self.db.commit()
        await self.db.refresh(booking)

        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status=str(previous_status),
                new_status="COMPLETED",
                changed_by_id=str(user_id),
            ))
        return self._booking_to_response(booking)

    async def cancel_booking_by_client(
        self,
        booking_id: int,
        client_id: int,
        reason: str = "CLIENT_CANCELLED",
    ) -> BookingResponse:
        """Cancelar reserva como cliente."""
        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        if booking.client_id != client_id:
            raise PermissionError("Solo el cliente puede cancelar su reserva")
        if booking.status == "COMPLETED":
            raise ValueError("No se puede cancelar una reserva completada")

        previous_status = booking.status
        booking.status = "CANCELLED"
        booking.updated_at = datetime.now(timezone.utc)
        self._record_status_change(
            booking_id=booking_id,
            previous_status=previous_status,
            new_status="CANCELLED",
            changed_by_id=client_id,
            reason=reason,
        )
        await self.db.commit()
        await self.db.refresh(booking)

        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status=str(previous_status),
                new_status="CANCELLED",
                changed_by_id=str(client_id),
            ))
        return self._booking_to_response(booking)

    # =========================================================================
    # ACCEPT/REJECT CON NOTIFICACIONES
    # =========================================================================

    async def accept_booking_with_notifications(
        self,
        booking_id: int,
        provider_id: int,
        db_session: AsyncSession = None,
    ) -> BookingResponse:
        """Accept booking and dispatch notifications."""
        response = await self.accept_booking(booking_id, provider_id)

        try:
            from app.services.event_dispatcher import get_dispatcher, EventType
            dispatcher = get_dispatcher()
            result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
            booking = result.scalar_one_or_none()
            if booking:
                await dispatcher.emit(EventType.BOOKING_ACCEPTED, {
                    "booking_id": booking.id,
                    "client_id": booking.client_id,
                    "provider_id": booking.provider_id,
                    "service_name": booking.service_category,
                })
        except Exception as e:
            logger.error(f"Error emitting booking accepted event: {e}")

        try:
            result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
            booking = result.scalar_one_or_none()
            if booking:
                client_r = await self.db.execute(
                    select(User).where(User.id == booking.client_id)
                )
                provider_r = await self.db.execute(
                    select(User).where(User.id == booking.provider_id)
                )
                client = client_r.scalar_one_or_none()
                provider = provider_r.scalar_one_or_none()
                if client and provider:
                    from app.services.notification_dispatcher import NotificationDispatcher
                    import asyncio
                    nd = NotificationDispatcher(db_session or self.db)
                    asyncio.create_task(
                        nd.dispatch_booking_accepted(booking, client, provider)
                    )
        except Exception as e:
            logger.error(f"Error dispatching accept notifications: {e}")

        return response

    async def reject_booking_with_notifications(
        self,
        booking_id: int,
        provider_id: int,
        reason_comment: Optional[str] = None,
        db_session: AsyncSession = None,
    ) -> BookingResponse:
        """Rechazar reserva: notifica, envía SES y elimina el registro."""
        # 1. Cargar datos ANTES de eliminar (para notificaciones y SES)
        result = await self.db.execute(select(Booking).where(Booking.id == booking_id))
        booking = result.scalar_one_or_none()
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)

        resolved_provider_id = await self._resolve_provider_id(provider_id)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede rechazar")
        if booking.status != "PENDING":
            raise ValueError(f"Solo se pueden rechazar reservas en estado PENDING. Estado actual: {booking.status}")

        client_id  = booking.client_id
        service    = booking.service_category or "Servicio"

        # 2. Cargar cliente y proveedor para notificaciones
        client_r   = await self.db.execute(select(User).where(User.id == client_id))
        provider_r = await self.db.execute(select(User).where(User.id == provider_id))
        client     = client_r.scalar_one_or_none()
        provider_u = provider_r.scalar_one_or_none()

        # 3. Guardar historial de estado antes de eliminar (no-crítico)
        try:
            self._record_status_change(
                booking_id=booking_id,
                previous_status="PENDING",
                new_status="REJECTED",
                changed_by_id=provider_id,
                reason="REJECTED_BY_PROVIDER",
                reason_comment=reason_comment,
            )
            await self.db.commit()
        except Exception as e:
            logger.warning(f"[REJECT] status_history insert skipped: {e}")
            await self.db.rollback()

        # 4. Construir respuesta ANTES de eliminar
        snapshot = self._booking_to_response(booking)
        snapshot.status = "REJECTED"

        # 5. Eliminar la reserva
        await self.db.delete(booking)
        await self.db.commit()
        logger.info(f"[REJECT] Booking {booking_id} deleted from DB")

        # 6. Enviar SES al cliente (no-crítico)
        if client:
            try:
                from app.core.config import settings
                from app.services.email_service import EmailService
                import asyncio
                email_svc = EmailService()
                reschedule_url = f"{settings.FRONTEND_URL}/services" if hasattr(settings, 'FRONTEND_URL') else "https://bapp.cl/services"
                provider_name = getattr(provider_u, 'full_name', '') or "Tu proveedor" if provider_u else "Tu proveedor"
                asyncio.create_task(email_svc.send_booking_rejected_email(
                    client_email=client.email,
                    client_name=getattr(client, 'full_name', '') or client.email,
                    provider_name=provider_name,
                    search_link=reschedule_url,
                ))
            except Exception as e:
                logger.warning(f"[REJECT] SES send skipped (non-critical): {e}")

        # 7. Notificación in-app (no-crítico)
        try:
            from app.services.notification_dispatcher import NotificationDispatcher
            import asyncio
            nd = NotificationDispatcher(db_session or self.db)
            asyncio.create_task(
                nd.dispatch_booking_rejected_notification(client_id, booking_id, service)
            )
        except Exception as e:
            logger.warning(f"[REJECT] In-app notification skipped (non-critical): {e}")

        # 8. Event bus (no-crítico)
        try:
            from app.services.event_dispatcher import get_dispatcher, EventType
            dispatcher = get_dispatcher()
            await dispatcher.emit(EventType.BOOKING_REJECTED, {
                "booking_id": booking_id,
                "client_id": client_id,
                "provider_id": provider_id,
                "service_name": service,
                "rejection_reason": reason_comment or "Proveedor no disponible",
            })
        except Exception as e:
            logger.warning(f"[REJECT] Event bus skipped (non-critical): {e}")

        return snapshot

    # =========================================================================
    # DISPONIBILIDAD
    # =========================================================================

    async def check_availability(
        self,
        provider_id: int,
        service_id: int,
        scheduled_date: date,
        scheduled_time: time,
        duration: int,
    ) -> CheckAvailabilityResponse:
        is_available, reason = await self._check_availability(
            provider_id, service_id, scheduled_date, scheduled_time
        )
        return CheckAvailabilityResponse(
            is_available=is_available,
            reason=reason,
            next_available_date=None,
            next_available_time=None,
        )

    async def _check_availability(
        self,
        provider_id: int,
        service_id: int,
        scheduled_date: date,
        scheduled_time: time,
    ) -> Tuple[bool, Optional[str]]:
        day_of_week = scheduled_date.weekday()

        result = await self.db.execute(
            select(ServiceAvailability).where(
                and_(
                    ServiceAvailability.provider_id == provider_id,
                    ServiceAvailability.service_id == service_id,
                    ServiceAvailability.day_of_week == day_of_week,
                    ServiceAvailability.is_available == True,
                )
            )
        )
        availability = result.scalar_one_or_none()
        if not availability:
            return False, "Sin horario configurado para ese día"

        if scheduled_time < availability.start_time or scheduled_time > availability.end_time:
            return False, "Hora fuera del rango disponible"

        conflict_result = await self.db.execute(
            select(func.count()).select_from(Booking).where(
                and_(
                    Booking.provider_id == provider_id,
                    Booking.scheduled_date == scheduled_date,
                    Booking.scheduled_time == scheduled_time,
                    Booking.status.in_(["PENDING", "APPROVED", "CONFIRMED"]),
                )
            )
        )
        if conflict_result.scalar() > 0:
            return False, "Horario ya reservado"

        return True, None

    async def set_availability(
        self, provider_id: int, request: ServiceAvailabilityRequest
    ) -> ServiceAvailabilityResponse:
        result = await self.db.execute(
            select(ServiceAvailability).where(
                and_(
                    ServiceAvailability.provider_id == provider_id,
                    ServiceAvailability.service_id == request.service_id,
                    ServiceAvailability.day_of_week == request.day_of_week,
                )
            )
        )
        availability = result.scalar_one_or_none()

        if availability:
            availability.start_time = request.start_time
            availability.end_time = request.end_time
            availability.is_available = request.is_available
        else:
            availability = ServiceAvailability(
                provider_id=provider_id,
                service_id=request.service_id,
                day_of_week=request.day_of_week,
                start_time=request.start_time,
                end_time=request.end_time,
                is_available=request.is_available,
                timezone=request.timezone,
            )
            self.db.add(availability)

        await self.db.commit()
        await self.db.refresh(availability)
        return self._availability_to_response(availability)

    # =========================================================================
    # NOTAS
    # =========================================================================

    async def add_note(
        self, booking_id: int, created_by_id: int, request
    ) -> BookingNoteResponse:
        self._add_note(booking_id, request.note_type, request.content, created_by_id)
        await self.db.commit()
        return BookingNoteResponse(
            id=str(booking_id),
            booking_id=str(booking_id),
            note_type=request.note_type,
            content=request.content,
            created_by_id=str(created_by_id),
            created_at=datetime.now(timezone.utc),
        )

    # =========================================================================
    # CONVERSIONES (no tocan la BD)
    # =========================================================================

    def _booking_to_response(self, booking: Booking) -> BookingResponse:
        return BookingResponse(
            id=str(booking.id),
            client_id=str(booking.client_id),
            provider_id=str(booking.provider_id),
            service_id=str(booking.service_id) if booking.service_id else None,
            scheduled_date=booking.scheduled_date,
            scheduled_time=booking.scheduled_time,
            duration=booking.duration,
            description=booking.description,
            total_price=booking.total_price,
            currency=booking.currency or "CLP",
            status=booking.status,
            created_at=booking.created_at,
            updated_at=booking.updated_at,
            completed_at=booking.completed_at,
            service_provider_id=booking.service_provider_id,
            location_address=booking.location_address,
            location_lat=float(booking.location_lat) if booking.location_lat else None,
            location_lng=float(booking.location_lng) if booking.location_lng else None,
            service_category=booking.service_category,
        )

    def _booking_to_detail_response(self, booking: Booking) -> BookingDetailResponse:
        base = self._booking_to_response(booking)
        return BookingDetailResponse(
            **base.dict(),
            status_history=[
                {
                    "id": str(h.id),
                    "previous_status": h.previous_status,
                    "new_status": h.new_status,
                    "changed_by_id": str(h.changed_by_id),
                    "reason": h.reason,
                    "reason_comment": h.reason_comment,
                    "created_at": h.created_at,
                }
                for h in booking.status_history
            ],
        )

    def _availability_to_response(
        self, availability: ServiceAvailability
    ) -> ServiceAvailabilityResponse:
        return ServiceAvailabilityResponse(
            id=str(availability.id),
            provider_id=str(availability.provider_id),
            service_id=str(availability.service_id),
            day_of_week=availability.day_of_week,
            start_time=availability.start_time,
            end_time=availability.end_time,
            is_available=availability.is_available,
            timezone=availability.timezone,
            created_at=availability.created_at,
            updated_at=availability.updated_at,
        )
