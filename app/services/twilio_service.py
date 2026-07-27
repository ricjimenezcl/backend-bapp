"""
Twilio Service - SMS and WhatsApp notifications
Handles sending SMS and WhatsApp messages via Twilio API
"""

import logging
from typing import Optional, Literal
from twilio.rest import Client
from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)


class TwilioService:
    """Service for sending SMS and WhatsApp messages via Twilio"""
    
    def __init__(self):
        """Initialize Twilio client"""
        try:
            self.client = Client(
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN
            )
            self.from_phone = settings.TWILIO_PHONE_NUMBER
            self.whatsapp_from = settings.TWILIO_WHATSAPP_NUMBER or settings.TWILIO_PHONE_NUMBER
            logger.info("✅ Twilio client initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Twilio: {str(e)}")
            self.client = None

    def _format_phone(self, phone: str) -> str:
        """Format phone number to E.164 format"""
        if not phone:
            return None
        # Remove all non-digits
        clean = ''.join(filter(str.isdigit, phone))
        # Add country code if not present
        if not phone.startswith('+'):
            if len(clean) == 9 and clean.startswith('9'):
                # Chilean format: 9XXXXXXXX -> +569XXXXXXXX
                clean = f"56{clean}"
            if not clean.startswith('56'):
                clean = f"56{clean}"
        return f"+{clean}" if not clean.startswith('+') else clean

    # ==================== SMS Methods ====================

    async def send_sms(
        self,
        phone_number: str,
        message: str
    ) -> bool:
        """
        Send SMS via Twilio
        
        Args:
            phone_number: Recipient phone number
            message: SMS message content
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            if not self.client:
                logger.error("❌ Twilio client not initialized")
                return False

            formatted_phone = self._format_phone(phone_number)
            if not formatted_phone:
                logger.error(f"❌ Invalid phone number: {phone_number}")
                return False

            message_obj = self.client.messages.create(
                body=message,
                from_=self.from_phone,
                to=formatted_phone
            )

            logger.info(f"✅ SMS sent successfully to {formatted_phone}")
            logger.info(f"   Message SID: {message_obj.sid}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send SMS: {str(e)}")
            return False

    async def send_booking_created_sms(
        self,
        provider: User,
        booking_id: int,
        client_name: str
    ) -> bool:
        """
        Send SMS to provider when new booking is created
        
        Args:
            provider: Provider user object
            booking_id: Booking ID
            client_name: Client name
            
        Returns:
            bool: Success status
        """
        if not provider.phone_number:
            logger.warning(f"⚠️ Provider {provider.id} has no phone number")
            return False

        message = (
            f"🔔 Nueva solicitud de reserva\n"
            f"Cliente: {client_name}\n"
            f"ID: #{booking_id}\n"
            f"Abre la app para aceptar o rechazar"
        )

        return await self.send_sms(provider.phone_number, message)

    async def send_booking_accepted_sms(
        self,
        client: User,
        booking_id: int,
        provider_name: str
    ) -> bool:
        """
        Send SMS to client when provider accepts booking
        
        Args:
            client: Client user object
            booking_id: Booking ID
            provider_name: Provider name
            
        Returns:
            bool: Success status
        """
        if not client.phone_number:
            logger.warning(f"⚠️ Client {client.id} has no phone number")
            return False

        message = (
            f"✅ Reserva confirmada\n"
            f"Proveedor: {provider_name}\n"
            f"ID: #{booking_id}\n"
            f"Abre la app para más detalles"
        )

        return await self.send_sms(client.phone_number, message)

    async def send_booking_rejected_sms(
        self,
        client: User,
        booking_id: int,
        provider_name: str
    ) -> bool:
        """
        Send SMS to client when provider rejects booking
        
        Args:
            client: Client user object
            booking_id: Booking ID
            provider_name: Provider name
            
        Returns:
            bool: Success status
        """
        if not client.phone_number:
            logger.warning(f"⚠️ Client {client.id} has no phone number")
            return False

        message = (
            f"❌ Reserva rechazada\n"
            f"Proveedor: {provider_name}\n"
            f"ID: #{booking_id}\n"
            f"Intenta con otro proveedor"
        )

        return await self.send_sms(client.phone_number, message)

    # ==================== WhatsApp Methods ====================

    async def send_whatsapp(
        self,
        phone_number: str,
        message: str
    ) -> bool:
        """
        Send WhatsApp message via Twilio
        
        Args:
            phone_number: Recipient phone number
            message: Message content
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            if not self.client:
                logger.error("❌ Twilio client not initialized")
                return False

            formatted_phone = self._format_phone(phone_number)
            if not formatted_phone:
                logger.error(f"❌ Invalid phone number: {phone_number}")
                return False

            # WhatsApp uses 'whatsapp:' prefix
            from_whatsapp = f"whatsapp:{self.whatsapp_from}"
            to_whatsapp = f"whatsapp:{formatted_phone}"

            message_obj = self.client.messages.create(
                body=message,
                from_=from_whatsapp,
                to=to_whatsapp
            )

            logger.info(f"✅ WhatsApp sent successfully to {formatted_phone}")
            logger.info(f"   Message SID: {message_obj.sid}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send WhatsApp: {str(e)}")
            return False

    async def send_booking_created_whatsapp(
        self,
        provider: User,
        booking_id: int,
        client_name: str
    ) -> bool:
        """
        Send WhatsApp to provider when new booking is created
        
        Args:
            provider: Provider user object
            booking_id: Booking ID
            client_name: Client name
            
        Returns:
            bool: Success status
        """
        if not provider.phone_number:
            logger.warning(f"⚠️ Provider {provider.id} has no phone number")
            return False

        message = (
            f"🔔 *Nueva solicitud de reserva*\n\n"
            f"👤 Cliente: {client_name}\n"
            f"🆔 ID: #{booking_id}\n\n"
            f"Abre la app para aceptar o rechazar"
        )

        return await self.send_whatsapp(provider.phone_number, message)

    async def send_booking_accepted_whatsapp(
        self,
        client: User,
        booking_id: int,
        provider_name: str
    ) -> bool:
        """
        Send WhatsApp to client when provider accepts booking
        
        Args:
            client: Client user object
            booking_id: Booking ID
            provider_name: Provider name
            
        Returns:
            bool: Success status
        """
        if not client.phone_number:
            logger.warning(f"⚠️ Client {client.id} has no phone number")
            return False

        message = (
            f"✅ *Reserva confirmada*\n\n"
            f"👤 Proveedor: {provider_name}\n"
            f"🆔 ID: #{booking_id}\n\n"
            f"Abre la app para más detalles y contactar al proveedor"
        )

        return await self.send_whatsapp(client.phone_number, message)

    async def send_booking_rejected_whatsapp(
        self,
        client: User,
        booking_id: int,
        provider_name: str
    ) -> bool:
        """
        Send WhatsApp to client when provider rejects booking
        
        Args:
            client: Client user object
            booking_id: Booking ID
            provider_name: Provider name
            
        Returns:
            bool: Success status
        """
        if not client.phone_number:
            logger.warning(f"⚠️ Client {client.id} has no phone number")
            return False

        message = (
            f"❌ *Reserva rechazada*\n\n"
            f"👤 Proveedor: {provider_name}\n"
            f"🆔 ID: #{booking_id}\n\n"
            f"Intenta con otro proveedor"
        )

        return await self.send_whatsapp(client.phone_number, message)

    async def send_chat_message_sms(
        self,
        recipient: User,
        sender_name: str,
        conversation_id: int
    ) -> bool:
        """
        Send SMS notification for new chat message
        
        Args:
            recipient: Recipient user object
            sender_name: Name of message sender
            conversation_id: Conversation ID
            
        Returns:
            bool: Success status
        """
        if not recipient.phone_number:
            logger.warning(f"⚠️ User {recipient.id} has no phone number")
            return False

        message = (
            f"💬 Nuevo mensaje de {sender_name}\n"
            f"Abre la app para leer"
        )

        return await self.send_sms(recipient.phone_number, message)

    async def send_chat_message_whatsapp(
        self,
        recipient: User,
        sender_name: str,
        conversation_id: int
    ) -> bool:
        """
        Send WhatsApp notification for new chat message
        
        Args:
            recipient: Recipient user object
            sender_name: Name of message sender
            conversation_id: Conversation ID
            
        Returns:
            bool: Success status
        """
        if not recipient.phone_number:
            logger.warning(f"⚠️ User {recipient.id} has no phone number")
            return False

        message = (
            f"💬 *Nuevo mensaje de {sender_name}*\n\n"
            f"Abre la app para leer y responder"
        )

        return await self.send_whatsapp(recipient.phone_number, message)


# Singleton instance
_twilio_service: Optional[TwilioService] = None


def get_twilio_service() -> TwilioService:
    """Get or create Twilio service singleton"""
    global _twilio_service
    if _twilio_service is None:
        _twilio_service = TwilioService()
    return _twilio_service
