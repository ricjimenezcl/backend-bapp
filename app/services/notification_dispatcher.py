"""
Notification Dispatcher - Orchestrates notifications across multiple channels
Coordinates sending notifications via SMS, WhatsApp, Email, and in-app (database)
"""

import logging
import asyncio
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.booking import Booking
from app.models.notification import Notification, NotificationType
from app.models.chat import ChatMessage
from app.models.conversation import Conversation
from app.services.twilio_service import get_twilio_service
from app.services.email_service import get_email_service
from app.services.notification_service import NotificationService
from app.api.websocket.connection_manager import connection_manager

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """
    Coordinates notification delivery across multiple channels:
    - In-app notifications (database)
    - SMS via Twilio
    - WhatsApp via Twilio
    - Email via Resend
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.notification_service = NotificationService(db)
        self.twilio_service = get_twilio_service()
        self.email_service = get_email_service()

    # ==================== BOOKING NOTIFICATIONS ====================

    async def dispatch_booking_created(
        self,
        booking: Booking,
        provider: User,
        client: User
    ) -> dict:
        """
        Dispatch notifications when booking is created
        Sends to: Provider (SMS + WhatsApp + In-app)
        
        Args:
            booking: Booking object
            provider: Provider user
            client: Client user
            
        Returns:
            dict: Delivery status for each channel
        """
        logger.info(f"📢 Dispatching booking created notification - Booking ID: {booking.id}")
        
        result = {
            "in_app": False,
            "sms": False,
            "whatsapp": False,
            "email": False
        }

        # 1. In-app notification (aislada para que no bloquee el resto)
        try:
            notification = await self.notification_service.create_booking_notification(
                user_id=provider.id,
                notification_type=NotificationType.BOOKING_RECEIVED,
                booking_id=booking.id,
                message=f"Nueva solicitud de {client.full_name or client.email}"
            )
            result["in_app"] = True
            logger.info(f"✅ In-app notification created - ID: {notification.id}")
        except Exception as e:
            logger.warning(f"⚠️ In-app notification failed: {str(e)}")

        # 2. SMS
        try:
            sms_result = await self.twilio_service.send_booking_created_sms(
                provider=provider,
                booking_id=booking.id,
                client_name=client.full_name or client.email
            )
            result["sms"] = sms_result
            logger.info(f"✅ SMS sent to {provider.phone_number}" if sms_result else f"⚠️ SMS failed for {provider.phone_number}")
        except Exception as e:
            logger.warning(f"⚠️ SMS failed: {str(e)}")

        # 3. WhatsApp
        try:
            whatsapp_result = await self.twilio_service.send_booking_created_whatsapp(
                provider=provider,
                booking_id=booking.id,
                client_name=client.full_name or client.email
            )
            result["whatsapp"] = whatsapp_result
            logger.info(f"✅ WhatsApp sent to {provider.phone_number}" if whatsapp_result else f"⚠️ WhatsApp failed for {provider.phone_number}")
        except Exception as e:
            logger.warning(f"⚠️ WhatsApp failed: {str(e)}")

        # 4. Email → cliente Y proveedor usando send_booking_created
        try:
            scheduled_date = str(booking.scheduled_date) if booking.scheduled_date else "A Coordinar"
            scheduled_time = str(booking.scheduled_time) if booking.scheduled_time else ""
            booking_date = f"{scheduled_date} {scheduled_time}".strip()

            email_result = await self.email_service.send_booking_created(
                client_email=client.email,
                provider_email=provider.email,
                data={
                    "client_name": client.full_name or client.email,
                    "provider_name": provider.full_name or provider.email,
                    "service_name": booking.service_category or "Servicio Solicitado",
                    "booking_date": booking_date,
                    "location": booking.location_address or "A Definir",
                    "description": booking.description or "Sin descripción",
                    "total_price": str(booking.total_price or "0"),
                    "booking_id": booking.id,
                }
            )
            result["email"] = email_result
            if email_result:
                logger.info(f"✅ Emails enviados a {client.email} y {provider.email}")
            else:
                logger.warning(f"⚠️ Email falló para {client.email} / {provider.email}")
        except Exception as e:
            logger.error(f"❌ Email dispatch failed: {str(e)}")

        # 5. WebSocket broadcast
        try:
            await self._broadcast_notification_via_websocket(
                user_id=provider.id,
                notification_type="booking_created",
                title="Nueva Solicitud de Servicio",
                message=f"Solicitud de {client.full_name or client.email}",
                data={
                    "booking_id": booking.id,
                    "client_id": client.id,
                    "client_name": client.full_name or client.email
                }
            )
        except Exception as e:
            logger.warning(f"⚠️ WebSocket broadcast failed: {str(e)}")

        logger.info(f"📊 Notification dispatch summary: {result}")
        return result

    async def dispatch_booking_accepted(
        self,
        booking: Booking,
        client: User,
        provider: User
    ) -> dict:
        """
        Dispatch notifications when booking is accepted by provider
        Sends to: Client (SMS + WhatsApp + In-app)
        
        Args:
            booking: Booking object
            client: Client user
            provider: Provider user
            
        Returns:
            dict: Delivery status for each channel
        """
        logger.info(f"📢 Dispatching booking accepted notification - Booking ID: {booking.id}")
        
        result = {
            "in_app": False,
            "sms": False,
            "whatsapp": False,
            "email": False
        }

        try:
            # 1. Create in-app notification
            notification = await self.notification_service.create_booking_notification(
                user_id=client.id,
                notification_type=NotificationType.BOOKING_CONFIRMED,
                booking_id=booking.id,
                message=f"Reserva confirmada por {provider.full_name or provider.email}"
            )
            result["in_app"] = True
            logger.info(f"✅ In-app notification created - ID: {notification.id}")

            # 2. Send SMS
            sms_result = await self.twilio_service.send_booking_accepted_sms(
                client=client,
                booking_id=booking.id,
                provider_name=provider.full_name or provider.email
            )
            result["sms"] = sms_result
            if sms_result:
                logger.info(f"✅ SMS sent to {client.phone_number}")
            else:
                logger.warning(f"⚠️ SMS failed for {client.phone_number}")

            # 3. Send WhatsApp
            whatsapp_result = await self.twilio_service.send_booking_accepted_whatsapp(
                client=client,
                booking_id=booking.id,
                provider_name=provider.full_name or provider.email
            )
            result["whatsapp"] = whatsapp_result
            if whatsapp_result:
                logger.info(f"✅ WhatsApp sent to {client.phone_number}")
            else:
                logger.warning(f"⚠️ WhatsApp failed for {client.phone_number}")

            # 4. Send Email
            email_result = await self.email_service.send_booking_accepted_email(
                client_email=client.email,
                client_name=client.full_name or client.email,
                provider_name=provider.full_name or provider.email,
                provider_rating=f"{provider.rating:.1f}" if hasattr(provider, 'rating') and provider.rating else "4.8",
                chat_link=f"https://bappsearch.com/client/chat/{booking.conversation_id}" if hasattr(booking, 'conversation_id') else f"https://bappsearch.com/client/bookings/{booking.id}"
            )
            result["email"] = email_result
            if email_result:
                logger.info(f"✅ Email sent to {client.email}")
            else:
                logger.warning(f"⚠️ Email failed for {client.email}")

            # 5. Broadcast via WebSocket
            await self._broadcast_notification_via_websocket(
                user_id=client.id,
                notification_type="booking_accepted",
                title="Reserva Confirmada",
                message=f"Tu reserva fue confirmada por {provider.full_name or provider.email}",
                data={
                    "booking_id": booking.id,
                    "provider_id": provider.id,
                    "provider_name": provider.full_name or provider.email
                }
            )

        except Exception as e:
            logger.error(f"❌ Error dispatching booking accepted notification: {str(e)}")

        logger.info(f"📊 Notification dispatch summary: {result}")
        return result

    async def dispatch_booking_rejected(
        self,
        booking: Booking,
        client: User,
        provider: User
    ) -> dict:
        """
        Dispatch notifications when booking is rejected by provider
        Sends to: Client (SMS + WhatsApp + In-app)
        
        Args:
            booking: Booking object
            client: Client user
            provider: Provider user
            
        Returns:
            dict: Delivery status for each channel
        """
        logger.info(f"📢 Dispatching booking rejected notification - Booking ID: {booking.id}")
        
        result = {
            "in_app": False,
            "sms": False,
            "whatsapp": False,
            "email": False
        }

        try:
            # 1. Create in-app notification
            notification = await self.notification_service.create_booking_notification(
                user_id=client.id,
                notification_type=NotificationType.BOOKING_REJECTED,
                booking_id=booking.id,
                message=f"Reserva rechazada por {provider.full_name or provider.email}"
            )
            result["in_app"] = True
            logger.info(f"✅ In-app notification created - ID: {notification.id}")

            # 2. Send SMS
            sms_result = await self.twilio_service.send_booking_rejected_sms(
                client=client,
                booking_id=booking.id,
                provider_name=provider.full_name or provider.email
            )
            result["sms"] = sms_result
            if sms_result:
                logger.info(f"✅ SMS sent to {client.phone_number}")
            else:
                logger.warning(f"⚠️ SMS failed for {client.phone_number}")

            # 3. Send WhatsApp
            whatsapp_result = await self.twilio_service.send_booking_rejected_whatsapp(
                client=client,
                booking_id=booking.id,
                provider_name=provider.full_name or provider.email
            )
            result["whatsapp"] = whatsapp_result
            if whatsapp_result:
                logger.info(f"✅ WhatsApp sent to {client.phone_number}")
            else:
                logger.warning(f"⚠️ WhatsApp failed for {client.phone_number}")

            # 4. Send Email
            email_result = await self.email_service.send_booking_rejected_email(
                client_email=client.email,
                client_name=client.full_name or client.email,
                provider_name=provider.full_name or provider.email,
                search_link="https://bappsearch.com/client/search"
            )
            result["email"] = email_result
            if email_result:
                logger.info(f"✅ Email sent to {client.email}")
            else:
                logger.warning(f"⚠️ Email failed for {client.email}")

            # 5. Broadcast via WebSocket
            await self._broadcast_notification_via_websocket(
                user_id=client.id,
                notification_type="booking_rejected",
                title="Reserva Rechazada",
                message=f"Tu reserva fue rechazada por {provider.full_name or provider.email}",
                data={
                    "booking_id": booking.id,
                    "provider_id": provider.id,
                    "provider_name": provider.full_name or provider.email
                }
            )

        except Exception as e:
            logger.error(f"❌ Error dispatching booking rejected notification: {str(e)}")

        logger.info(f"📊 Notification dispatch summary: {result}")
        return result

    # ==================== CHAT NOTIFICATIONS ====================

    async def dispatch_chat_message(
        self,
        message: ChatMessage,
        recipient: User,
        sender: User,
        conversation: Conversation
    ) -> dict:
        """
        Dispatch notifications for new chat message
        Sends to: Recipient (SMS + WhatsApp + In-app)
        
        Args:
            message: ChatMessage object
            recipient: Recipient user
            sender: Sender user
            conversation: Conversation object
            
        Returns:
            dict: Delivery status for each channel
        """
        logger.info(f"📢 Dispatching chat message notification - Message ID: {message.id}")
        
        result = {
            "in_app": False,
            "sms": False,
            "whatsapp": False
        }

        try:
            # 1. Create in-app notification
            notification = await self.notification_service.create_message_notification(
                user_id=recipient.id,
                sender_name=sender.full_name or sender.email,
                conversation_id=conversation.id
            )
            result["in_app"] = True
            logger.info(f"✅ In-app notification created - ID: {notification.id}")

            # 2. Send SMS (only if recipient not recently notified)
            sms_result = await self.twilio_service.send_chat_message_sms(
                recipient=recipient,
                sender_name=sender.full_name or sender.email,
                conversation_id=conversation.id
            )
            result["sms"] = sms_result

            # 3. Send WhatsApp
            whatsapp_result = await self.twilio_service.send_chat_message_whatsapp(
                recipient=recipient,
                sender_name=sender.full_name or sender.email,
                conversation_id=conversation.id
            )
            result["whatsapp"] = whatsapp_result

        except Exception as e:
            logger.error(f"❌ Error dispatching chat message notification: {str(e)}")

        logger.info(f"📊 Notification dispatch summary: {result}")
        return result

    # ==================== WebSocket Broadcasting ====================

    async def _broadcast_notification_via_websocket(
        self,
        user_id: int,
        notification_type: str,
        title: str,
        message: str,
        data: dict = None
    ):
        """
        Broadcast notification to user via WebSocket
        
        Args:
            user_id: User to notify
            notification_type: Type of notification (e.g., 'booking_created', 'booking_accepted')
            title: Notification title
            message: Notification message
            data: Additional data to send
        """
        try:
            ws_message = {
                "type": "notification",
                "notification_type": notification_type,
                "title": title,
                "message": message,
                "data": data or {},
                "timestamp": asyncio.get_event_loop().time()
            }
            
            await connection_manager.broadcast_to_user(user_id, ws_message)
            logger.info(f"📡 WebSocket notification sent to user {user_id}")
        except Exception as e:
            logger.warning(f"⚠️ WebSocket broadcast failed for user {user_id}: {str(e)}")


def get_notification_dispatcher(db: AsyncSession) -> NotificationDispatcher:
    """Factory function to get NotificationDispatcher instance"""
    return NotificationDispatcher(db)
