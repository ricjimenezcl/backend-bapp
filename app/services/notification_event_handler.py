"""
Event Handlers for Notifications
Listens to events and creates notifications + sends external alerts
"""

from app.services.event_dispatcher import EventPayload, EventType, get_dispatcher
from app.services.notification_service import NotificationService
from app.services.email_service import email_service
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.models.provider import Provider
from app.core.database import AsyncSessionLocal
from typing import Optional, Dict, Any
import asyncio
import logging

logger = logging.getLogger(__name__)


def _get_connection_manager():
    from app.api.websocket.connection_manager import connection_manager
    return connection_manager


class NotificationEventHandler:
    """Handles event-driven notifications"""
    
    def __init__(self):
        self.dispatcher = get_dispatcher()
    
    def setup_handlers(self) -> None:
        """Register all notification event handlers"""
        self.dispatcher.subscribe(EventType.BOOKING_CREATED, self.on_booking_created)
        self.dispatcher.subscribe(EventType.BOOKING_ACCEPTED, self.on_booking_accepted)
        self.dispatcher.subscribe(EventType.BOOKING_REJECTED, self.on_booking_rejected)
        self.dispatcher.subscribe(EventType.BOOKING_COMPLETED, self.on_booking_completed)
        logger.info("✅ Notification handlers registered")
    
    async def _get_user_info(self, db: AsyncSession, user_id: int):
        """Helper to get user and provider info"""
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        
        provider = None
        if user and user.role == "PROVIDER":
            result = await db.execute(select(Provider).where(Provider.user_id == user_id))
            provider = result.scalars().first()
            
        return user, provider

    async def on_booking_created(self, payload: EventPayload) -> None:
        """Handle booking.created event"""
        try:
            data = payload.data
            async with AsyncSessionLocal() as db:
                provider_user, _ = await self._get_user_info(db, data.get("provider_id"))
                client_user, _ = await self._get_user_info(db, data.get("client_id"))
                
                if not provider_user or not client_user:
                    return

                # Enviar correos usando el nuevo EmailService
                await email_service.send_booking_created(
                    client_email=client_user.email,
                    provider_email=provider_user.email,
                    data={
                        "service_name": data.get("service_name", "Servicio BAPP"),
                        "booking_date": data.get("scheduled_date", "A convenir"),
                        "other_party_name": provider_user.full_name or provider_user.email,
                        "location": data.get("location", "Ver en la app")
                    }
                )
                logger.info(f"✅ Booking created emails sent for Booking {data.get('booking_id')}")
        except Exception as e:
            logger.error(f"❌ Error in on_booking_created handler: {e}")

    async def on_booking_accepted(self, payload: EventPayload) -> None:
        """Handle booking.accepted event"""
        try:
            data = payload.data
            async with AsyncSessionLocal() as db:
                client_user, _ = await self._get_user_info(db, data.get("client_id"))
                provider_user, _ = await self._get_user_info(db, data.get("provider_id"))
                
                if client_user:
                    await email_service.send_booking_reminder( # Usamos el mismo template de status
                        client_user.email,
                        client_user.full_name or client_user.email,
                        is_provider=False,
                        data={
                            "title": "¡Tu reserva ha sido aceptada! ✅",
                            "message": f"El proveedor {provider_user.full_name if provider_user else ''} ha aceptado tu solicitud.",
                            "service_name": data.get("service_name", ""),
                            "booking_date": data.get("scheduled_date", ""),
                            "other_party_name": provider_user.full_name if provider_user else "Proveedor",
                            "location": data.get("location", ""),
                            "action_text": "Ver Detalles",
                            "action_url": f"/client/bookings"
                        }
                    )
        except Exception as e:
            logger.error(f"❌ Error in on_booking_accepted handler: {e}")

    async def on_booking_rejected(self, payload: EventPayload) -> None:
        """Handle booking.rejected event"""
        # Implementación opcional si se requiere email de rechazo
        pass

    async def on_booking_completed(self, payload: EventPayload) -> None:
        """Handle booking.completed event - Send review request"""
        try:
            data = payload.data
            async with AsyncSessionLocal() as db:
                client_user, _ = await self._get_user_info(db, data.get("client_id"))
                provider_user, _ = await self._get_user_info(db, data.get("provider_id"))
                
                if client_user and provider_user:
                    await email_service.send_review_reminder(
                        email=client_user.email,
                        user_name=client_user.full_name or client_user.email,
                        provider_name=provider_user.full_name or provider_user.email,
                        booking_id=str(data.get("booking_id"))
                    )
                    logger.info(f"✅ Review reminder sent to {client_user.email}")
        except Exception as e:
            logger.error(f"❌ Error in on_booking_completed handler: {e}")

# Singleton instance
_handler = None

def get_notification_handler():
    global _handler
    if _handler is None:
        _handler = NotificationEventHandler()
    return _handler
