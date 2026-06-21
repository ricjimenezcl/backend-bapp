"""
Email Service - Sends emails via Amazon SES using Jinja2 templates
"""

import logging
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from app.core.config import settings

logger = logging.getLogger(__name__)

class EmailService:
    """
    Email service using Amazon SES for transactional emails
    """

    def __init__(self):
        """Initialize SES client and Jinja environment"""
        try:
            import boto3
            self._ses = boto3.client(
                "ses",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            self.from_email = settings.SES_FROM_EMAIL
            
            # Setup Jinja2 environment
            template_path = Path(__file__).resolve().parent.parent / "templates"
            self.jinja_env = Environment(
                loader=FileSystemLoader(str(template_path)),
                autoescape=select_autoescape(['html', 'xml'])
            )
            
            logger.info("✅ Amazon SES email client initialized with Jinja2 templates")
        except Exception as e:
            logger.error(f"⚠️ SES/Jinja initialization failed: {str(e)}")
            self._ses = None
            self.jinja_env = None

    def _send_raw(self, to: str, subject: str, html: str) -> bool:
        """Blocking SES send — run via executor to avoid blocking event loop"""
        if not self._ses:
            return False
        self._ses.send_email(
            Source=self.from_email,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
            },
        )
        return True

    async def _send(self, to: str, subject: str, html: str) -> bool:
        """Send email asynchronously using thread executor"""
        if not self._ses:
            logger.warning("⚠️ SES client not initialized, skipping email")
            return False
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_raw, to, subject, html)
            return True
        except Exception as e:
            logger.error(f"❌ SES send failed to {to}: {str(e)}")
            return False

    def _render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with context, including global variables"""
        if not self.jinja_env:
            return ""
        
        # Add global context
        full_context = {
            **context,
            "frontend_url": settings.FRONTEND_URL.rstrip('/'),
            "year": 2026
        }
        
        template = self.jinja_env.get_template(f"emails/{template_name}.html")
        return template.render(full_context)

    # ==================== PUBLIC METHODS ====================

    async def send_welcome_email(self, email: str, user_name: str, role: str) -> bool:
        """Envia correo de bienvenida según el rol (CLIENT/PROVIDER)"""
        template = "welcome_client" if role == "CLIENT" else "welcome_provider"
        subject = "¡Bienvenido a BAPP Search!" if role == "CLIENT" else "¡Bienvenido a la red de proveedores de BAPP!"
        
        html = self._render(template, {"user_name": user_name})
        return await self._send(email, subject, html)

    async def send_booking_created(self, client_email: str, provider_email: str, data: Dict[str, Any]) -> bool:
        """Envia correos de confirmación de reserva a ambos"""
        # Para el Cliente
        client_html = self._render("booking_status", {
            "title": "¡Tu solicitud ha sido enviada!",
            "message": "Hemos enviado tu solicitud al proveedor. Te notificaremos cuando la acepte.",
            "is_provider": False,
            "action_text": "Ver mis Reservas",
            "action_url": f"{settings.FRONTEND_URL}/client/bookings",
            **data
        })
        
        # Para el Proveedor
        provider_html = self._render("booking_status", {
            "title": "¡Nueva solicitud de servicio!",
            "message": "Tienes una nueva solicitud pendiente de aprobación.",
            "is_provider": True,
            "action_text": "Ver Solicitud",
            "action_url": f"{settings.FRONTEND_URL}/provider/bookings",
            **data
        })
        
        # Enviar ambos en paralelo
        tasks = [
            self._send(client_email, "Reserva Enviada - BAPP Search", client_html),
            self._send(provider_email, "Nueva Solicitud Recibida - BAPP Search", provider_html)
        ]
        results = await asyncio.gather(*tasks)
        return all(results)

    async def send_booking_reminder(self, email: str, user_name: str, is_provider: bool, data: Dict[str, Any]) -> bool:
        """Envia recordatorio del día de la reserva"""
        subject = "⏰ Recordatorio: Tienes una reserva hoy"
        html = self._render("booking_status", {
            "title": "Recuerda tu cita de hoy",
            "message": f"Hola {user_name}, te recordamos que tienes una reserva programada para hoy.",
            "is_provider": is_provider,
            "action_text": "Ver Detalles",
            "action_url": f"{settings.FRONTEND_URL}/{'provider' if is_provider else 'client'}/bookings",
            **data
        })
        return await self._send(email, subject, html)

    async def send_review_reminder(self, email: str, user_name: str, provider_name: str, booking_id: str) -> bool:
        """Envia correo al cliente para que califique el servicio"""
        subject = "⭐ ¿Qué te pareció el servicio?"
        html = self._render("booking_status", {
            "title": "¡Servicio Completado!",
            "message": f"Hola {user_name}, cuéntanos cómo fue tu experiencia con {provider_name}. Tu opinión ayuda a la comunidad.",
            "is_provider": False,
            "action_text": "Calificar Ahora",
            "action_url": f"{settings.FRONTEND_URL}/reviews/add/{booking_id}",
            "service_name": "", # Opcional: pasar si se tiene
            "booking_date": "", 
            "other_party_name": provider_name,
            "location": ""
        })
        return await self._send(email, subject, html)

    async def send_purchase_confirmation(self, email: str, data: Dict[str, Any]) -> bool:
        """Envia confirmación de compra de beneficios"""
        subject = "✅ Confirmación de Compra - BAPP Search"
        html = self._render("purchase_confirmation", data)
        return await self._send(email, subject, html)

# Singleton instance
_email_service = None

def get_email_service() -> EmailService:
    """Get or create email service singleton"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service

# Create singleton instance for direct import
email_service = get_email_service()
