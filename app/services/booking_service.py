# Constantes
RESERVA_NO_ENCONTRADA = "Reserva no encontrada"
"""
BookingService - Lógica de negocio para el sistema de reservas
"""

from datetime import datetime, date, time, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func

from app.models.booking import (
    Booking, BookingStatusHistory, BookingCancellation, 
    ServiceAvailability, BookingNote, BookingStatus, CancellationReason, DayOfWeek
)
from app.models.user import User
from app.models.provider import Provider  # ✅ OPCIÓN B: Import Provider model
from app.models.service_category import ServiceCategory
from app.models.service import Service
from app.schemas.booking import (
    CreateBookingRequest, ConfirmBookingRequest, CancelBookingRequest,
    BookingResponse, BookingDetailResponse, CheckAvailabilityResponse,
    ServiceAvailabilityRequest, ServiceAvailabilityResponse,
    CreateBookingNoteRequest, BookingNoteResponse
)
from app.infra.event_bus.bus import EventBus
from app.infra.event_bus.event import BookingCreatedEvent, BookingStatusChangedEvent
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class BookingService:
    """Servicio para manejar toda la lógica de reservas"""
    
    def __init__(self, db: Session, event_bus: Optional[EventBus] = None):
        self.db = db
        self.event_bus = event_bus
    
    def _resolve_provider_id(self, user_id: int) -> Optional[int]:
        """Resolve providers.id from users.id"""
        provider = self.db.query(Provider).filter(Provider.user_id == user_id).first()
        if provider:
            return provider.id
        return None
    
    # ========================================================================
    # CREAR RESERVAS
    # ========================================================================
    
    def create_booking_from_email(self, client_email: str, request: CreateBookingRequest) -> BookingResponse:
        """Crear una nueva reserva desde el email del cliente"""
        try:
            # Buscar el cliente por email
            client = self.db.query(User).filter(User.email == client_email).first()
            if not client:
                logger.error(f"[BOOKING] Client not found with email: {client_email}")
                raise ValueError("Cliente no encontrado")
            
            # Validar rol del cliente
            if client.role != "CLIENT":
                logger.error(f"[BOOKING] User is not CLIENT. Email: {client_email}, Role: {client.role}")
                raise ValueError(f"Solo los clientes pueden crear reservas. Tu rol es: {client.role}")
            
            return self.create_booking(client.id, request)
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"[BOOKING] Error creating booking from email: {str(e)}")
            raise ValueError(f"Error al crear la reserva: {str(e)}")
    
    def create_booking(self, client_id: int, request: CreateBookingRequest) -> BookingResponse:
        """Crear una nueva reserva"""
        try:
            logger.info(f"[BOOKING] Creating booking - Client: {client_id}, Provider: {request.provider_id}, Service: {request.service_id}")
            
            # Validar que el cliente exista
            client = self.db.query(User).filter(User.id == client_id).first()
            if not client:
                logger.error(f"[BOOKING] Client not found: {client_id}")
                raise ValueError("Cliente no encontrado")
            
            # Validar rol del cliente
            if client.role != "CLIENT":
                logger.error(f"[BOOKING] User is not CLIENT. Role: {client.role}")
                raise ValueError(f"Solo los clientes pueden crear reservas. Tu rol es: {client.role}")
            
            # Validar que el proveedor exista (usando Provider.id - OPCIÓN B)
            provider = self.db.query(Provider).filter(Provider.id == request.provider_id).first()
            if not provider:
                logger.error(f"[BOOKING] Provider not found: {request.provider_id}")
                raise ValueError("Proveedor no encontrado")
            
            # Validar que el servicio exista (usando service_categories)
            from app.models.service_category import ServiceCategory
            service_cat = self.db.query(ServiceCategory).filter(ServiceCategory.id == request.service_id).first()
            if not service_cat:
                logger.warning(f"[BOOKING] ServiceCategory not found: {request.service_id}, proceeding anyway")
            
            # Crear la reserva
            booking = Booking(
                client_id=client_id,
                provider_id=request.provider_id,
                service_id=request.service_id,
                scheduled_date=request.scheduled_date,
                scheduled_time=request.scheduled_time,
                duration=request.duration,
                description=request.description,
                total_price=request.total_price,
                status='PENDING',
                service_provider_id=request.service_provider_id,
                location_address=request.location_address or "",
                location_lat=request.location_lat,
                location_lng=request.location_lng,
                service_category=request.service_category or "GENERAL"
            )
            
            self.db.add(booking)
            self.db.flush()
            
            logger.info(f"[BOOKING] Booking flushed with ID: {booking.id}")
            
            # Registrar el cambio de estado inicial
            self._record_status_change(
                booking_id=booking.id,
                previous_status=None,
                new_status='PENDING',
                changed_by_id=int(client_id),
                reason="CREATED"
            )
            
            self.db.commit()
            
            logger.info(f"[BOOKING] Booking committed successfully: {booking.id}")
            
            # Emitir evento
            if self.event_bus:
                self.event_bus.publish(BookingCreatedEvent(
                    booking_id=str(booking.id),
                    client_id=str(client_id),
                    provider_id=str(request.provider_id),
                    service_id=str(request.service_id),
                    scheduled_time=request.scheduled_time.isoformat() if request.scheduled_time else None
                ))
            
            logger.info(f"✅ Reserva creada exitosamente: {booking.id}")
            return self._booking_to_response(booking)
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error creando reserva: {str(e)}", exc_info=True)
            raise
    
    # ========================================================================
    # OBTENER RESERVAS
    # ========================================================================
    
    def get_booking(self, booking_id: int, user_id: int) -> BookingDetailResponse:
        """Obtener una reserva específica"""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        
        # Verificar permisos - user_id puede ser client_id (users.id) o necesitamos resolver provider.id
        resolved_provider_id = self._resolve_provider_id(user_id)
        if booking.client_id != user_id and booking.provider_id != resolved_provider_id:
            raise PermissionError("No tienes permiso para ver esta reserva")
        
        return self._booking_to_detail_response(booking)
    
    
    def list_bookings(self, user_id: int, user_role: str, 
                     page: int = 1, size: int = 10,
                     status: Optional[str] = None) -> dict:
        """Listar reservas según el rol del usuario"""
        query = self.db.query(Booking)
        
        if user_role == "CLIENT":
            query = query.filter(Booking.client_id == user_id)
        elif user_role == "PROVIDER":
            resolved_provider_id = self._resolve_provider_id(user_id)
            if not resolved_provider_id:
                return {"total": 0, "page": page, "size": size, "items": []}
            query = query.filter(Booking.provider_id == resolved_provider_id)
        elif user_role != "ADMIN":
            raise PermissionError("Rol no autorizado")
        
        if status:
            query = query.filter(Booking.status == BookingStatus[status])
        
        total = query.count()
        
        bookings = query.order_by(desc(Booking.created_at)).limit(size).offset((page - 1) * size).all()
        
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [self._booking_to_response(b) for b in bookings]
        }
    
    # ========================================================================
    # ACTUALIZAR ESTADOS
    # ========================================================================
    
    def confirm_booking(self, booking_id: UUID, provider_id: UUID, 
                       request: ConfirmBookingRequest) -> BookingResponse:
        """Confirmar una reserva (provider_id recibido es users.id)"""
        # Convert UUIDs to int for database queries
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        user_id_int = int(provider_id) if isinstance(provider_id, str) else provider_id
        
        # Resolver providers.id desde users.id
        resolved_provider_id = self._resolve_provider_id(user_id_int)
        if not resolved_provider_id:
            raise PermissionError("No se encontró proveedor para este usuario")
        
        booking = self.db.query(Booking).filter(Booking.id == booking_id_int).first()
        
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede confirmar")
        
        if booking.status != 'PENDING':
            raise ValueError(f"Estado inválido: {booking.status}")
        
        booking.status = 'CONFIRMED'
        from datetime import timezone
        booking.updated_at = datetime.now(timezone.utc)
        
        self._record_status_change(
            booking_id=booking_id_int,
            previous_status='PENDING',
            new_status='CONFIRMED',
            changed_by_id=user_id_int,
            reason="CONFIRMED_BY_PROVIDER"
        )
        
        if request.notes:
            self._add_note(booking_id_int, "INTERNAL", request.notes, user_id_int)
        
        self.db.commit()
        
        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status="PENDING",
                new_status="CONFIRMED",
                changed_by_id=str(provider_id)
            ))
        
        return self._booking_to_response(booking)
    
    
    def cancel_booking(self, booking_id: UUID, user_id: UUID, 
                      request: CancelBookingRequest) -> BookingResponse:
        """Cancelar una reserva (user_id es users.id)"""
        # Convert UUIDs to int for database queries
        booking_id_int = int(booking_id) if isinstance(booking_id, str) else booking_id
        user_id_int = int(user_id) if isinstance(user_id, str) else user_id
        
        # Resolver providers.id si el usuario es proveedor
        resolved_provider_id = self._resolve_provider_id(user_id_int)
        
        booking = self.db.query(Booking).filter(Booking.id == booking_id_int).first()
        
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        
        # Verificar permiso: puede ser el cliente (client_id = users.id) o el proveedor (provider_id = providers.id)
        if booking.client_id != user_id_int and booking.provider_id != resolved_provider_id:
            raise PermissionError("No tienes permiso para cancelar")
        
        if booking.status == 'COMPLETED':
            raise ValueError("No se puede cancelar una reserva completada")

        if booking.status == 'CANCELLED':
            return self._booking_to_response(booking)

        previous_status = booking.status

        # ── Paso 1: actualizar estado (crítico) ──────────────────────────
        from datetime import timezone
        booking.status = 'CANCELLED'
        booking.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(booking)

        # ── Paso 2: registro de cancelación (no crítico) ─────────────────
        try:
            existing = self.db.query(BookingCancellation).filter(
                BookingCancellation.booking_id == booking_id_int
            ).first()
            if not existing:
                cancellation = BookingCancellation(
                    booking_id=booking_id_int,
                    cancelled_by_id=user_id_int,
                    reason=request.reason.value,
                    reason_comment=request.reason_comment,
                )
                self.db.add(cancellation)
                self.db.commit()
        except Exception as e:
            logger.warning(f"[CANCEL] BookingCancellation insert skipped: {e}")
            self.db.rollback()

        # ── Paso 3: historial de estado (no crítico) ─────────────────────
        try:
            self._record_status_change(
                booking_id=booking_id_int,
                previous_status=previous_status,
                new_status='CANCELLED',
                changed_by_id=user_id_int,
                reason=request.reason.value,
                reason_comment=request.reason_comment
            )
            self.db.commit()
        except Exception as e:
            logger.warning(f"[CANCEL] status_history insert skipped: {e}")
            self.db.rollback()

        # ── Paso 4: evento (no crítico) ──────────────────────────────────
        if self.event_bus:
            try:
                self.event_bus.publish(BookingStatusChangedEvent(
                    booking_id=str(booking_id),
                    previous_status=str(previous_status),
                    new_status="CANCELLED",
                    changed_by_id=str(user_id)
                ))
            except Exception as e:
                logger.warning(f"[CANCEL] event_bus publish skipped: {e}")

        return self._booking_to_response(booking)
    
    # ========================================================================
    # DISPONIBILIDAD
    # ========================================================================
    
    def check_availability(self, provider_id: int, service_id: int,
                          scheduled_date: date, scheduled_time: time,
                          duration: int) -> CheckAvailabilityResponse:
        """Verificar disponibilidad de un proveedor para una fecha/hora (PUBLIC)"""
        is_available, reason = self._check_availability(provider_id, service_id, scheduled_date, scheduled_time)
        
        return CheckAvailabilityResponse(
            is_available=is_available,
            reason=reason,
            next_available_date=None,
            next_available_time=None
        )
    
    def _check_availability(self, provider_id: int, service_id: int,
                           scheduled_date: date, scheduled_time: time) -> Tuple[bool, Optional[str]]:
        """Verificar disponibilidad (INTERNAL).

        provider_id → providers.id
        service_id  → service_providers.id  (FK corregida)
        """
        day_of_week = scheduled_date.weekday()  # 0=Lunes … 6=Domingo

        availability = self.db.query(ServiceAvailability).filter(
            and_(
                ServiceAvailability.provider_id == provider_id,
                ServiceAvailability.service_id == service_id,  # service_providers.id
                ServiceAvailability.day_of_week == day_of_week,
                ServiceAvailability.is_available == True
            )
        ).first()

        if not availability:
            return False, "Sin horario configurado para ese día"

        if scheduled_time < availability.start_time or scheduled_time > availability.end_time:
            return False, "Hora fuera del rango disponible"

        # Verificar que no exista otra reserva activa en ese slot
        conflicting = self.db.query(Booking).filter(
            and_(
                Booking.provider_id == provider_id,
                Booking.scheduled_date == scheduled_date,
                Booking.scheduled_time == scheduled_time,
                Booking.status.in_(['PENDING', 'CONFIRMED'])
            )
        ).count()

        if conflicting > 0:
            return False, "Horario ya reservado"

        return True, None
    
    
    def set_availability(self, provider_id: UUID, 
                        request: ServiceAvailabilityRequest) -> ServiceAvailabilityResponse:
        """Configurar disponibilidad"""
        
        # Convert UUIDs to int for database queries
        provider_id_int = int(provider_id) if isinstance(provider_id, str) else provider_id
        service_id_int = int(request.service_id) if isinstance(request.service_id, str) else request.service_id
        
        availability = self.db.query(ServiceAvailability).filter(
            and_(
                ServiceAvailability.provider_id == provider_id_int,
                ServiceAvailability.service_id == service_id_int,
                ServiceAvailability.day_of_week == request.day_of_week
            )
        ).first()
        
        if availability:
            availability.start_time = request.start_time
            availability.end_time = request.end_time
            availability.is_available = request.is_available
        else:
            availability = ServiceAvailability(
                provider_id=provider_id_int,
                service_id=service_id_int,
                day_of_week=request.day_of_week,
                start_time=request.start_time,
                end_time=request.end_time,
                is_available=request.is_available,
                timezone=request.timezone
            )
            self.db.add(availability)
        
        self.db.commit()
        return self._availability_to_response(availability)
    
    # ========================================================================
    # NOTAS
    # ========================================================================
    
    def add_note(self, booking_id: int, created_by_id: int, request) -> BookingNoteResponse:
        """Agregar una nota a una reserva (PUBLIC)"""
        self._add_note(booking_id, request.note_type, request.content, created_by_id)
        self.db.commit()
        
        # Return response
        return BookingNoteResponse(
            id=str(booking_id),  # Simplified for now
            booking_id=str(booking_id),
            note_type=request.note_type,
            content=request.content,
            created_by_id=str(created_by_id),
            created_at=datetime.now(timezone.utc)
        )
    
    def _add_note(self, booking_id: int, note_type: str, content: str, created_by_id: int):
        """Agregar nota"""
        note = BookingNote(
            booking_id=booking_id,
            note_type=note_type,
            content=content,
            created_by_id=created_by_id
        )
        self.db.add(note)
    
    # ========================================================================
    # HISTORIAL
    # ========================================================================
    
    def _record_status_change(self, booking_id: int, previous_status: Optional[BookingStatus],
                             new_status: BookingStatus, changed_by_id: int,
                             reason: Optional[str] = None, reason_comment: Optional[str] = None):
        """Registrar cambio de estado"""
        history = BookingStatusHistory(
            booking_id=booking_id,
            previous_status=previous_status,
            new_status=new_status,
            changed_by_id=changed_by_id,
            reason=reason,
            reason_comment=reason_comment
        )
        self.db.add(history)
    
    # ========================================================================
    # CONVERSIONES
    # ========================================================================
    
    def _booking_to_response(self, booking: Booking) -> BookingResponse:
        """Convertir a response"""
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
            service_category=booking.service_category
        )
    
    def _booking_to_detail_response(self, booking: Booking) -> BookingDetailResponse:
        """Convertir a detail response"""
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
                    "created_at": h.created_at
                }
                for h in booking.status_history
            ]
        )
    
    def _availability_to_response(self, availability: ServiceAvailability) -> ServiceAvailabilityResponse:
        """Convertir disponibilidad a response"""
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
            updated_at=availability.updated_at
        )
    # ========================================================================
    # OBTENER RESERVAS POR CLIENTE
    # ========================================================================

    def get_bookings_for_client(self, client_id: int) -> List[BookingResponse]:
        """Obtener todas las reservas de un cliente (SÍNCRONO)"""
        try:
            logger.info(f"[BOOKING] get_bookings_for_client called with client_id={client_id} (type={type(client_id)})")
            
            # Debug: count all bookings first
            total = self.db.query(Booking).count()
            logger.info(f"[BOOKING] Total bookings in DB: {total}")
            
            bookings = self.db.query(Booking).filter(
                Booking.client_id == client_id
            ).order_by(desc(Booking.created_at)).all()
            
            logger.info(f"[BOOKING] Found {len(bookings)} bookings for client_id={client_id}")
            
            results = []
            for booking in bookings:
                try:
                    results.append(self._booking_to_response(booking))
                except Exception as conv_err:
                    logger.error(f"[BOOKING] Error converting booking id={booking.id}: {conv_err}")
                    import traceback
                    traceback.print_exc()
            return results
        except Exception as e:
            logger.error(f"Error getting bookings for client {client_id}: {str(e)}")
            return []
    
    async def get_bookings_for_client_async(self, client_id: int) -> List[BookingResponse]:
        """Obtener todas las reservas de un cliente (ASÍNCRONO)"""
        try:
            from sqlalchemy.future import select
            result = await self.db.execute(
                select(Booking)
                .where(Booking.client_id == client_id)
                .order_by(desc(Booking.created_at))
            )
            bookings = result.scalars().all()
            
            return [self._booking_to_response(booking) for booking in bookings]
        except Exception as e:
            logger.error(f"Error getting bookings for client {client_id}: {str(e)}")
            return []
    
    # ========================================================================
    # MÉTODOS WRAPPER PARA ENDPOINTS
    # ========================================================================
    
    def accept_booking(self, booking_id: int, user_id: int) -> BookingResponse:
        """
        Aceptar una reserva - cambia estado de PENDING a CONFIRMED
        (Usado por endpoint PATCH /{booking_id}/accept)
        Recibe user_id (users.id) y resuelve providers.id internamente
        """
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        
        resolved_provider_id = self._resolve_provider_id(user_id)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede aceptar")
        
        if booking.status != 'PENDING':
            raise ValueError(f"Estado inválido: {booking.status}")
        
        booking.status = 'CONFIRMED'
        from datetime import timezone
        booking.updated_at = datetime.now(timezone.utc)
        
        self._record_status_change(
            booking_id=booking_id,
            previous_status='PENDING',
            new_status='CONFIRMED',
            changed_by_id=provider_id,
            reason="CONFIRMED_BY_PROVIDER"
        )
        
        self.db.commit()
        
        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status="PENDING",
                new_status="CONFIRMED",
                changed_by_id=str(provider_id)
            ))
        
        return self._booking_to_response(booking)
    
    def reject_booking(self, booking_id: int, user_id: int) -> BookingResponse:
        """Rechazar una reserva (Solo Proveedor). Recibe user_id (users.id)"""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        
        resolved_provider_id = self._resolve_provider_id(user_id)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede rechazar")
        
        if booking.status != 'PENDING':
            raise ValueError(f"Estado inválido: {booking.status}")
        
        booking.status = 'REJECTED'
        from datetime import timezone
        booking.updated_at = datetime.now(timezone.utc)
        
        self._record_status_change(
            booking_id=booking_id,
            previous_status='PENDING',
            new_status='REJECTED',
            changed_by_id=provider_id,
            reason="REJECTED_BY_PROVIDER"
        )
        
        self.db.commit()
        
        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status="PENDING",
                new_status="REJECTED",
                changed_by_id=str(provider_id)
            ))
        
        return self._booking_to_response(booking)
    
    # ==================== ASYNC NOTIFICATION METHODS ====================
    
    async def accept_booking_with_notifications(
        self, 
        booking_id: int, 
        provider_id: int,
        db_session: AsyncSession = None
    ) -> BookingResponse:
        """
        Accept booking and dispatch notifications
        Called from async endpoint
        """
        # First: accept the booking (using sync method)
        response = self.accept_booking(booking_id, provider_id)
        
        # Emit event for event-driven notifications
        try:
            from app.services.event_dispatcher import get_dispatcher, EventType
            dispatcher = get_dispatcher()
            
            booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
            if booking:
                await dispatcher.emit(EventType.BOOKING_ACCEPTED, {
                    "booking_id": booking.id,
                    "client_id": booking.client_id,
                    "provider_id": booking.provider_id,
                    "service_name": booking.service_category,
                })
                logger.info(f"✅ booking.accepted event emitted for booking {booking_id}")
        except Exception as e:
            logger.error(f"⚠️ Error emitting booking accepted event: {str(e)}")
        
        # Second: dispatch notifications asynchronously
        try:
            # Get updated booking
            booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
            client = self.db.query(User).filter(User.id == booking.client_id).first()
            provider = self.db.query(User).filter(User.id == booking.provider_id).first()
            
            if booking and client and provider:
                # Import here to avoid circular dependency
                from app.services.notification_dispatcher import NotificationDispatcher
                
                dispatcher = NotificationDispatcher(db_session or self.db)
                
                # Dispatch in background
                import asyncio
                asyncio.create_task(
                    dispatcher.dispatch_booking_accepted(booking, client, provider)
                )
                logger.info(f"✅ Notification dispatch task created for booking {booking_id}")
        except Exception as e:
            logger.error(f"⚠️ Error dispatching notifications: {str(e)}")
            # Don't fail the request, just log the error
        
        return response
    
    async def reject_booking_with_notifications(
        self, 
        booking_id: int, 
        provider_id: int,
        db_session: AsyncSession = None
    ) -> BookingResponse:
        """
        Reject booking and dispatch notifications
        Called from async endpoint
        """
        # First: reject the booking (using sync method)
        response = self.reject_booking(booking_id, provider_id)
        
        # Emit event for event-driven notifications
        try:
            from app.services.event_dispatcher import get_dispatcher, EventType
            dispatcher = get_dispatcher()
            
            booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
            if booking:
                await dispatcher.emit(EventType.BOOKING_REJECTED, {
                    "booking_id": booking.id,
                    "client_id": booking.client_id,
                    "provider_id": booking.provider_id,
                    "service_name": booking.service_category,
                    "rejection_reason": "Provider unavailable"
                })
                logger.info(f"✅ booking.rejected event emitted for booking {booking_id}")
        except Exception as e:
            logger.error(f"⚠️ Error emitting booking rejected event: {str(e)}")
        
        # Second: dispatch notifications asynchronously
        try:
            # Get updated booking
            booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
            client = self.db.query(User).filter(User.id == booking.client_id).first()
            provider = self.db.query(User).filter(User.id == booking.provider_id).first()
            
            if booking and client and provider:
                # Import here to avoid circular dependency
                from app.services.notification_dispatcher import NotificationDispatcher
                
                dispatcher = NotificationDispatcher(db_session or self.db)
                
                # Dispatch in background
                import asyncio
                asyncio.create_task(
                    dispatcher.dispatch_booking_rejected(booking, client, provider)
                )
                logger.info(f"✅ Notification dispatch task created for booking {booking_id}")
        except Exception as e:
            logger.error(f"⚠️ Error dispatching notifications: {str(e)}")
            # Don't fail the request, just log the error
        
        return response
    
    def complete_booking(self, booking_id: int, user_id: int) -> BookingResponse:
        """Marcar reserva como completada (Solo Proveedor). Recibe user_id (users.id)"""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        
        resolved_provider_id = self._resolve_provider_id(user_id)
        if booking.provider_id != resolved_provider_id:
            raise PermissionError("Solo el proveedor puede completar")
        
        if booking.status not in ['CONFIRMED', 'IN_PROGRESS']:
            raise ValueError(f"Estado inválido: {booking.status}")
        
        booking.status = 'COMPLETED'
        from datetime import timezone
        booking.completed_at = datetime.now(timezone.utc)
        booking.updated_at = datetime.now(timezone.utc)
        
        self._record_status_change(
            booking_id=booking_id,
            previous_status=booking.status,
            new_status='COMPLETED',
            changed_by_id=provider_id,
            reason="COMPLETED_BY_PROVIDER"
        )
        
        self.db.commit()
        
        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status=str(booking.status),
                new_status="COMPLETED",
                changed_by_id=str(provider_id)
            ))
        
        return self._booking_to_response(booking)
    
    def cancel_booking_by_client(self, booking_id: int, client_id: int, 
                                 reason: str = "CLIENT_CANCELLED") -> BookingResponse:
        """Cancelar una reserva como cliente"""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        
        if not booking:
            raise ValueError(RESERVA_NO_ENCONTRADA)
        
        if booking.client_id != client_id:
            raise PermissionError("Solo el cliente puede cancelar su reserva")
        
        if booking.status == 'COMPLETED':
            raise ValueError("No se puede cancelar una reserva completada")
        
        previous_status = booking.status
        booking.status = 'CANCELLED'
        from datetime import timezone
        booking.updated_at = datetime.now(timezone.utc)
        
        self._record_status_change(
            booking_id=booking_id,
            previous_status=previous_status,
            new_status='CANCELLED',
            changed_by_id=client_id,
            reason=reason
        )
        
        self.db.commit()
        
        if self.event_bus:
            self.event_bus.publish(BookingStatusChangedEvent(
                booking_id=str(booking_id),
                previous_status=str(previous_status),
                new_status="CANCELLED",
                changed_by_id=str(client_id)
            ))
        
        return self._booking_to_response(booking)
    
    def get_bookings_for_provider(self, user_id: int) -> List[BookingResponse]:
        """Obtener todas las reservas asignadas a un proveedor (recibe users.id)"""
        try:
            # Resolver providers.id desde users.id
            provider = self.db.query(Provider).filter(Provider.user_id == user_id).first()
            if not provider:
                logger.warning(f"[BOOKING] No provider found for user_id={user_id}")
                return []
            
            logger.info(f"[BOOKING] Resolved provider.id={provider.id} from user_id={user_id}")
            
            bookings = self.db.query(Booking).filter(
                Booking.provider_id == provider.id
            ).order_by(desc(Booking.created_at)).all()
            
            logger.info(f"[BOOKING] Found {len(bookings)} bookings for provider.id={provider.id}")
            
            results = []
            for booking in bookings:
                try:
                    results.append(self._booking_to_response(booking))
                except Exception as conv_err:
                    logger.error(f"[BOOKING] Error converting booking id={booking.id}: {conv_err}")
                    import traceback
                    traceback.print_exc()
            
            logger.info(f"[BOOKING] Successfully converted {len(results)}/{len(bookings)} bookings")
            return results
        except Exception as e:
            logger.error(f"Error getting bookings for provider user_id={user_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
