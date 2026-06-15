"""
Event Handlers for Notifications
Listens to events and creates notifications + sends external alerts
"""

from app.services.event_dispatcher import EventPayload, EventType, get_dispatcher
from app.services.notification_service import NotificationService
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.models.provider import Provider
from app.core.database import get_db_async
from typing import Optional
import asyncio
import logging


logger = logging.getLogger(__name__)


class NotificationEventHandler:
    """Handles event-driven notifications"""
    
    def __init__(self):
        self.dispatcher = get_dispatcher()
        # Lazy-load services to avoid import errors if modules are missing
        self.email_service = None
        self.twilio_service = None
    
    def _get_email_service(self):
        """Lazy-load email service"""
        if self.email_service is None:
            from app.services.email_service import EmailService
            self.email_service = EmailService()
        return self.email_service
    
    def _get_twilio_service(self):
        """Lazy-load Twilio service"""
        if self.twilio_service is None:
            try:
                from app.services.twilio_service import TwilioService
                self.twilio_service = TwilioService()
            except ImportError:
                logger.warning("⚠️  Twilio not available, SMS/WhatsApp will be skipped")
                self.twilio_service = False
        return self.twilio_service if self.twilio_service is not False else None
    
    def setup_handlers(self) -> None:
        """Register all notification event handlers"""
        self.dispatcher.subscribe(EventType.BOOKING_CREATED, self.on_booking_created)
        self.dispatcher.subscribe(EventType.BOOKING_ACCEPTED, self.on_booking_accepted)
        self.dispatcher.subscribe(EventType.BOOKING_REJECTED, self.on_booking_rejected)
        logger.info("✅ Notification handlers registered")
    
    async def on_booking_created(self, payload: EventPayload) -> None:
        """
        Handle booking.created event
        Notify provider via: Email + SMS + WhatsApp
        """
        try:
            booking_data = payload.data
            provider_id = booking_data.get("provider_id")
            client_id = booking_data.get("client_id")
            service_name = booking_data.get("service_name", "Unknown")
            booking_id = booking_data.get("booking_id")
            scheduled_date = booking_data.get("scheduled_date", "Not specified")
            price = booking_data.get("price", 0)
            
            logger.info(f"📬 Processing BOOKING_CREATED for provider {provider_id}")
            
            # Get database session
            async for db in get_db_async():
                try:
                    # Get provider user
                    result = await db.execute(
                        select(User).where(User.id == provider_id)
                    )
                    provider_user = result.scalars().first()
                    
                    if not provider_user:
                        logger.warning(f"   ⚠️  Provider user {provider_id} not found")
                        return
                    
                    # Get provider profile for phone
                    result = await db.execute(
                        select(Provider).where(Provider.user_id == provider_id)
                    )
                    provider_profile = result.scalars().first()
                    
                    # Get client user for name
                    result = await db.execute(
                        select(User).where(User.id == client_id)
                    )
                    client_user = result.scalars().first()
                    client_name = client_user.email if client_user else "Unknown Client"
                    
                    # Create notification in database
                    notification_service = NotificationService(db)
                    await notification_service.create_notification(
                        user_id=provider_id,
                        notification_type="booking_received",
                        title="Nueva Reserva Recibida",
                        content=f"Nueva reserva de {client_name} para {service_name} el {scheduled_date}",
                        related_entity_type="booking",
                        related_entity_id=int(booking_id) if booking_id else None,
                    )
                    
                    # Send Email
                    email_service = self._get_email_service()
                    if email_service:
                        email_subject = f"Nueva Reserva: {service_name}"
                        email_body = f"""
                        <h2>Nueva Reserva Recibida</h2>
                        <p>Cliente: {client_name}</p>
                        <p>Servicio: {service_name}</p>
                        <p>Fecha Programada: {scheduled_date}</p>
                        <p>Valor: ${price}</p>
                        <p>
                            <a href="https://app.bapp.cl/provider/bookings/{booking_id}">
                                Ver Reserva
                            </a>
                        </p>
                        """
                        
                        try:
                            await email_service.send_email(
                                to_email=provider_user.email,
                                subject=email_subject,
                                body=email_body
                            )
                            logger.info(f"   ✅ Email sent to {provider_user.email}")
                        except Exception as e:
                            logger.warning(f"   ⚠️  Email send failed: {str(e)}")
                    
                    # Send SMS if phone available
                    if provider_profile and provider_profile.phone:
                        twilio_service = self._get_twilio_service()
                        if twilio_service:
                            try:
                                sms_message = f"Nueva reserva de {client_name} para {service_name} el {scheduled_date}. Monto: ${price}"
                                await twilio_service.send_sms(
                                    phone_number=provider_profile.phone,
                                    message=sms_message
                                )
                                logger.info(f"   ✅ SMS sent to {provider_profile.phone}")
                            except Exception as e:
                                logger.warning(f"   ⚠️  SMS send failed: {str(e)}")
                    
                    # Send WhatsApp if phone available
                    if provider_profile and provider_profile.phone:
                        twilio_service = self._get_twilio_service()
                        if twilio_service:
                            try:
                                wa_message = f"🔔 *Nueva Reserva*\n\nCliente: {client_name}\nServicio: {service_name}\nFecha: {scheduled_date}\nMonto: ${price}\n\nResponde aquí o accede a tu app."
                                await twilio_service.send_whatsapp(
                                    phone_number=provider_profile.phone,
                                    message=wa_message
                                )
                                logger.info(f"   ✅ WhatsApp sent to {provider_profile.phone}")
                            except Exception as e:
                                logger.warning(f"   ⚠️  WhatsApp send failed: {str(e)}")
                    
                    logger.info(f"   ✅ All notifications sent for provider {provider_id}")
                    
                except Exception as inner_e:
                    logger.error(f"   ❌ Error processing booking created: {str(inner_e)}")
                    raise
        
        except Exception as e:
            logger.error(f"❌ Error in on_booking_created: {str(e)}")
    
    async def on_booking_accepted(self, payload: EventPayload) -> None:
        """
        Handle booking.accepted event
        Notify client via: Email
        """
        try:
            booking_data = payload.data
            provider_id = booking_data.get("provider_id")
            client_id = booking_data.get("client_id")
            service_name = booking_data.get("service_name", "Unknown")
            booking_id = booking_data.get("booking_id")
            
            logger.info(f"📬 Processing BOOKING_ACCEPTED for client {client_id}")
            
            # Get database session
            async for db in get_db_async():
                try:
                    # Get client user
                    result = await db.execute(
                        select(User).where(User.id == client_id)
                    )
                    client_user = result.scalars().first()
                    
                    if not client_user:
                        logger.warning(f"   ⚠️  Client user {client_id} not found")
                        return
                    
                    # Get provider user for name
                    result = await db.execute(
                        select(User).where(User.id == provider_id)
                    )
                    provider_user = result.scalars().first()
                    
                    result = await db.execute(
                        select(Provider).where(Provider.user_id == provider_id)
                    )
                    provider_profile = result.scalars().first()
                    provider_name = provider_profile.full_name if provider_profile else "Provider"
                    
                    # Create notification in database
                    notification_service = NotificationService(db)
                    await notification_service.create_notification(
                        user_id=client_id,
                        notification_type="booking_confirmed",
                        title="Reserva Aceptada",
                        content=f"{provider_name} ha aceptado tu reserva para {service_name}",
                        related_entity_type="booking",
                        related_entity_id=int(booking_id) if booking_id else None,
                    )
                    
                    # Send Email
                    email_service = self._get_email_service()
                    if email_service:
                        email_subject = f"Reserva Aceptada: {service_name}"
                        email_body = f"""
                        <h2>Tu Reserva fue Aceptada</h2>
                        <p>Proveedor: {provider_name}</p>
                        <p>Servicio: {service_name}</p>
                        <p>
                            <a href="https://app.bapp.cl/client/bookings/{booking_id}">
                                Ver Detalles de tu Reserva
                            </a>
                        </p>
                        """
                        
                        try:
                            await email_service.send_email(
                                to_email=client_user.email,
                                subject=email_subject,
                                body=email_body
                            )
                            logger.info(f"   ✅ Email sent to {client_user.email}")
                        except Exception as e:
                            logger.warning(f"   ⚠️  Email send failed: {str(e)}")
                    
                    logger.info(f"   ✅ All notifications sent for client {client_id}")
                    
                except Exception as inner_e:
                    logger.error(f"   ❌ Error processing booking accepted: {str(inner_e)}")
                    raise
        
        except Exception as e:
            logger.error(f"❌ Error in on_booking_accepted: {str(e)}")
    
    async def on_booking_rejected(self, payload: EventPayload) -> None:
        """
        Handle booking.rejected event
        Notify client via: Email
        """
        try:
            booking_data = payload.data
            provider_id = booking_data.get("provider_id")
            client_id = booking_data.get("client_id")
            service_name = booking_data.get("service_name", "Unknown")
            booking_id = booking_data.get("booking_id")
            rejection_reason = booking_data.get("rejection_reason", "No disponible en ese momento")
            
            logger.info(f"📬 Processing BOOKING_REJECTED for client {client_id}")
            
            # Get database session
            async for db in get_db_async():
                try:
                    # Get client user
                    result = await db.execute(
                        select(User).where(User.id == client_id)
                    )
                    client_user = result.scalars().first()
                    
                    if not client_user:
                        logger.warning(f"   ⚠️  Client user {client_id} not found")
                        return
                    
                    # Get provider user for name
                    result = await db.execute(
                        select(Provider).where(Provider.user_id == provider_id)
                    )
                    provider_profile = result.scalars().first()
                    provider_name = provider_profile.full_name if provider_profile else "Provider"
                    
                    # Create notification in database
                    notification_service = NotificationService(db)
                    await notification_service.create_notification(
                        user_id=client_id,
                        notification_type="booking_rejected",
                        title="Reserva Rechazada",
                        content=f"{provider_name} ha rechazado tu reserva para {service_name}",
                        related_entity_type="booking",
                        related_entity_id=int(booking_id) if booking_id else None,
                    )
                    
                    # Send Email
                    email_service = self._get_email_service()
                    if email_service:
                        email_subject = f"Reserva Rechazada: {service_name}"
                        email_body = f"""
                        <h2>Tu Reserva fue Rechazada</h2>
                        <p>Proveedor: {provider_name}</p>
                        <p>Servicio: {service_name}</p>
                        <p>Motivo: {rejection_reason}</p>
                        <p>
                            <a href="https://app.bapp.cl/client/services">
                                Buscar Otros Proveedores
                            </a>
                        </p>
                        """
                        
                        try:
                            await email_service.send_email(
                                to_email=client_user.email,
                                subject=email_subject,
                                body=email_body
                            )
                            logger.info(f"   ✅ Email sent to {client_user.email}")
                        except Exception as e:
                            logger.warning(f"   ⚠️  Email send failed: {str(e)}")
                    
                    logger.info(f"   ✅ All notifications sent for client {client_id}")
                    
                except Exception as inner_e:
                    logger.error(f"   ❌ Error processing booking rejected: {str(inner_e)}")
                    raise
        
        except Exception as e:
            logger.error(f"❌ Error in on_booking_rejected: {str(e)}")


# Global handler instance
_notification_handler: Optional[NotificationEventHandler] = None


def get_notification_handler() -> NotificationEventHandler:
    """Get or create the global notification event handler"""
    global _notification_handler
    if _notification_handler is None:
        _notification_handler = NotificationEventHandler()
        _notification_handler.setup_handlers()
    return _notification_handler
