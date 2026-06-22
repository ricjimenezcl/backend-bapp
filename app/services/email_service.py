"""
Email Service - Sends emails via Resend using Jinja2 templates
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
    Email service using Resend for transactional emails
    """

    def __init__(self):
        """Initialize Resend client and Jinja environment"""
        try:
            import resend
            if not settings.RESEND_API_KEY:
                logger.warning("⚠️ RESEND_API_KEY not found in settings")
                self._resend = None
            else:
                resend.api_key = settings.RESEND_API_KEY
                self._resend = resend
                
            # Sender email from settings
            self.from_email = settings.RESEND_FROM_EMAIL
            
            # Setup Jinja2 environment
            template_path = Path(__file__).resolve().parent.parent / "templates"
            self.jinja_env = Environment(
                loader=FileSystemLoader(str(template_path)),
                autoescape=select_autoescape(['html', 'xml'])
            )
            
            logger.info("✅ Resend email client initialized with Jinja2 templates")
        except Exception as e:
            logger.error(f"⚠️ Resend/Jinja initialization failed: {str(e)}")
            self._resend = None
            self.jinja_env = None

    def _send_raw(self, to: str, subject: str, html: str) -> bool:
        """Blocking Resend send — run via executor to avoid blocking event loop"""
        if not self._resend:
            return False
            
        params = {
            "from": self.from_email,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        
        self._resend.Emails.send(params)
        return True

    async def _send(self, to: str, subject: str, html: str) -> bool:
        """Send email asynchronously using thread executor"""
        if not self._resend:
            logger.warning("⚠️ Resend client not initialized, skipping email")
            return False
        try:
            # Importante: Resend SDK es síncrona, usamos executor
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_raw, to, subject, html)
            return True
        except Exception as e:
            logger.error(f"❌ Resend send failed to {to}: {str(e)}")
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

    async def send_password_reset_email(self, email: str, user_name: str, token: str) -> bool:
        """Envia correo para restablecer contraseña"""
        subject = "Recuperar contraseña - BAPP Search"
        reset_url = f"{settings.FRONTEND_URL}/auth/set-new-password?token={token}"
        
        html = self._render("password_reset", {
            "user_name": user_name,
            "reset_url": reset_url
        })
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
            "message": "Has recibido una nueva solicitud de servicio. Por favor, revísala y acéptala si estás disponible.",
            "is_provider": True,
            "action_text": "Ver Solicitudes",
            "action_url": f"{settings.FRONTEND_URL}/provider/bookings",
            **data
        })
        
        # Enviar ambos (en paralelo para no esperar uno al otro)
        tasks = [
            self._send(client_email, "Reserva Solicitada - BAPP", client_html),
            self._send(provider_email, "Nueva Solicitud de Servicio - BAPP", provider_html)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(r is True for r in results)

    async def send_booking_update(self, email: str, status: str, data: Dict[str, Any]) -> bool:
        """Notifica cambios de estado en una reserva"""
        status_map = {
            "CONFIRMED": ("¡Tu reserva ha sido confirmada!", "El proveedor ha aceptado tu solicitud."),
            "CANCELLED": ("Reserva Cancelada", "Lamentablemente la reserva no podrá llevarse a cabo."),
            "COMPLETED": ("¿Cómo estuvo el servicio?", "Tu servicio ha finalizado. Califícanos.")
        }
        
        title, msg = status_map.get(status, ("Actualización de Reserva", "Tu reserva tiene un nuevo estado."))
        
        html = self._render("booking_status", {
            "title": title,
            "message": msg,
            "is_provider": False,
            "action_text": "Ver Detalles",
            "action_url": f"{settings.FRONTEND_URL}/client/bookings",
            **data
        })
        
        return await self._send(email, f"Actualización de Reserva: {title}", html)

# Export singleton instance
email_service = EmailService()

def get_email_service() -> EmailService:
    """Helper for dependency injection or standalone use"""
    return email_service
