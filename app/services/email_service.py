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
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_raw, to, subject, html)
            logger.info(f"✅ Email enviado a {to}")
            return True
        except Exception as e:
            logger.error(f"❌ Resend send failed to {to}: {str(e)}", exc_info=True)
            return False

    def _render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with context, including global variables"""
        if not self.jinja_env:
            logger.error(f"❌ Jinja2 env not initialized — cannot render '{template_name}'")
            return ""
        
        # Add global context
        full_context = {
            **context,
            "frontend_url": settings.FRONTEND_URL.rstrip('/'),
            "year": 2026
        }
        
        try:
            template = self.jinja_env.get_template(f"emails/{template_name}.html")
            return template.render(full_context)
        except Exception as e:
            logger.error(f"❌ Template render failed for '{template_name}': {e}", exc_info=True)
            return ""

    # ==================== PUBLIC METHODS ====================

    async def send_welcome_email(self, email: str, user_name: str, role: str) -> bool:
        """Envia correo de bienvenida según el rol (CLIENT/PROVIDER)"""
        try:
            template = "welcome_client" if role == "CLIENT" else "welcome_provider"
            subject = "¡Bienvenido a BAPP Search!" if role == "CLIENT" else "¡Bienvenido a la red de proveedores de BAPP!"

            html = self._render(template, {"user_name": user_name})
            if not html:
                logger.error(f"❌ Welcome email rendered empty for {email} (role={role}, template={template})")
                return False

            logger.info(f"📧 Enviando welcome email a {email} (role={role})")
            return await self._send(email, subject, html)
        except Exception as e:
            logger.error(f"❌ send_welcome_email failed for {email} (role={role}): {e}", exc_info=True)
            return False

    async def send_verification_email(self, email: str, user_name: str, verification_link: str) -> bool:
        """Envía correo de verificación de cuenta al registrarse"""
        subject = "Verifica tu correo - BAPP Search"
        html = self._render("email_verification", {
            "user_name": user_name,
            "verification_url": verification_link,
        })
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

    async def send_booking_accepted_email(
        self, client_email: str, client_name: str, provider_name: str,
        provider_rating: str = "5.0", chat_link: str = ""
    ) -> bool:
        """Notifica al cliente que su reserva fue aceptada por el proveedor"""
        html = self._render("booking_status", {
            "title": "¡Tu reserva fue aceptada! ✅",
            "message": f"<strong>{provider_name}</strong> ha aceptado tu solicitud de servicio. Ya puedes coordinar los detalles.",
            "is_provider": False,
            "other_party_name": provider_name,
            "action_text": "Ver mi Reserva",
            "action_url": chat_link or f"{settings.FRONTEND_URL}/client/bookings",
        })
        return await self._send(client_email, "¡Tu reserva fue confirmada! - BAPP", html)

    async def send_booking_rejected_email(
        self, client_email: str, client_name: str, provider_name: str, search_link: str = ""
    ) -> bool:
        """Notifica al cliente que su reserva fue rechazada por el proveedor"""
        html = self._render("booking_status", {
            "title": "Solicitud no disponible",
            "message": f"Lamentablemente <strong>{provider_name}</strong> no puede atender tu solicitud en este momento.",
            "is_provider": False,
            "other_party_name": provider_name,
            "action_text": "Buscar otro proveedor",
            "action_url": search_link or f"{settings.FRONTEND_URL}/client/search",
        })
        return await self._send(client_email, "Actualización de tu Reserva - BAPP", html)

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

    async def send_booking_reminder(
        self, email: str, user_name: str, is_provider: bool = False, data: Dict[str, Any] = None
    ) -> bool:
        """Aviso de reserva aceptada / recordatorio al cliente o proveedor"""
        d = data or {}
        html = self._render("booking_status", {
            "title": d.get("title", "Actualización de tu Reserva"),
            "message": d.get("message", "Tienes una actualización en tu reserva."),
            "is_provider": is_provider,
            "service_name": d.get("service_name", ""),
            "booking_date": d.get("booking_date", ""),
            "other_party_name": d.get("other_party_name", ""),
            "location": d.get("location", ""),
            "action_text": d.get("action_text", "Ver Reserva"),
            "action_url": d.get("action_url", f"{settings.FRONTEND_URL}/{'provider' if is_provider else 'client'}/bookings"),
        })
        subject = d.get("title", "Actualización de tu Reserva") + " - BAPP"
        return await self._send(email, subject, html)

    async def send_review_reminder(
        self, email: str, user_name: str, provider_name: str, booking_id: str
    ) -> bool:
        """Invitación a calificar al proveedor tras completar el servicio"""
        review_url = f"{settings.FRONTEND_URL}/client/bookings?review={booking_id}"
        html = self._render("booking_status", {
            "title": "¿Cómo estuvo el servicio? ⭐",
            "message": f"Tu servicio con <strong>{provider_name}</strong> ha finalizado. Tu opinión ayuda a otros usuarios.",
            "is_provider": False,
            "service_name": "",
            "booking_date": "",
            "other_party_name": provider_name,
            "location": "",
            "action_text": "Dejar Reseña",
            "action_url": review_url,
        })
        return await self._send(email, "Califica tu experiencia - BAPP Search", html)

    async def send_booking_completed_email(
        self, client_email: str, client_name: str, provider_name: str, review_url: str
    ) -> bool:
        """Aviso de servicio completado automáticamente — incluye link de reseña"""
        html = self._render("booking_status", {
            "title": "Tu servicio ha finalizado ✅",
            "message": f"El servicio con <strong>{provider_name}</strong> ha sido completado. ¿Qué tal fue tu experiencia?",
            "is_provider": False,
            "service_name": "",
            "booking_date": "",
            "other_party_name": provider_name,
            "location": "",
            "action_text": "Dejar mi Reseña",
            "action_url": review_url,
        })
        return await self._send(client_email, "Servicio completado — Deja tu reseña - BAPP", html)

    async def send_booking_expired_email(
        self, client_email: str, client_name: str, service_name: str,
        scheduled_date: str, search_url: str
    ) -> bool:
        """Aviso de reserva PENDING expirada sin confirmar"""
        html = self._render("booking_status", {
            "title": "Tu solicitud de reserva venció",
            "message": (
                f"La solicitud para <strong>{service_name}</strong> programada para el "
                f"{scheduled_date} no fue confirmada a tiempo y fue cancelada automáticamente."
            ),
            "is_provider": False,
            "service_name": service_name,
            "booking_date": scheduled_date,
            "other_party_name": "",
            "location": "",
            "action_text": "Buscar otro proveedor",
            "action_url": search_url,
        })
        return await self._send(client_email, "Solicitud de reserva expirada - BAPP Search", html)

    async def send_purchase_confirmation(
        self, user_email: str, user_name: str, transaction: Any, product: Any
    ) -> bool:
        """Confirmación de pago de plan premium (Google Play, Apple IAP, Transbank)"""
        from datetime import datetime as _dt
        amount_val = getattr(transaction, "amount", 0) or 0
        currency = getattr(transaction, "currency", "CLP") or "CLP"
        amount_str = f"${int(amount_val):,} {currency}"
        created = getattr(transaction, "created_at", None)
        date_str = created.strftime("%d/%m/%Y %H:%M") if created else _dt.now().strftime("%d/%m/%Y %H:%M")
        product_name = getattr(product, "name", "Plan Premium BAPP") or "Plan Premium BAPP"
        ref = str(getattr(transaction, "transaction_id", None) or getattr(transaction, "id", ""))

        html = self._render("purchase_confirmation", {
            "user_name": user_name,
            "item_name": product_name,
            "amount": amount_str,
            "date": date_str,
            "reference_id": ref,
        })
        return await self._send(user_email, "Confirmación de compra - BAPP Search", html)

    async def send_service_slot_activated_email(
        self, email: str, business_name: str, expires_at: Any
    ) -> bool:
        """Notifica al proveedor que su nuevo servicio (slot pagado) ya está
        publicado, indicando la fecha en que dejará de estarlo si no renueva."""
        expires_str = expires_at.strftime("%d/%m/%Y") if expires_at else "sin definir"
        html = self._render("service_slot_status", {
            "title": "¡Tu nuevo servicio fue publicado! 🎉",
            "message": (
                f"Tu servicio <strong>{business_name}</strong> ya está visible para clientes. "
                f"Esta publicación estará activa hasta el <strong>{expires_str}</strong>, fecha en "
                "la que deberás renovar el plan para mantenerlo publicado."
            ),
            "business_name": business_name,
            "expires_str": expires_str,
            "action_text": "Ver mis servicios",
            "action_url": f"{settings.FRONTEND_URL}/provider/tabs/my-services",
        })
        return await self._send(email, "Nuevo servicio publicado - BAPP Search", html)

    async def send_service_slot_expiring_soon_email(
        self, email: str, business_name: str, expires_at: Any
    ) -> bool:
        """Recordatorio enviado ~5 días antes de que expire un slot de servicio pagado."""
        expires_str = expires_at.strftime("%d/%m/%Y") if expires_at else "próximamente"
        html = self._render("service_slot_status", {
            "title": "Tu publicación está por vencer ⏳",
            "message": (
                f"Tu servicio <strong>{business_name}</strong> dejará de estar publicado el "
                f"<strong>{expires_str}</strong>. Renueva tu plan para que tus clientes sigan "
                "encontrándote."
            ),
            "business_name": business_name,
            "expires_str": expires_str,
            "action_text": "Renovar plan",
            "action_url": f"{settings.FRONTEND_URL}/provider/tabs/my-services",
        })
        return await self._send(email, "Tu publicación vence pronto - BAPP Search", html)

# Export singleton instance
email_service = EmailService()

def get_email_service() -> EmailService:
    """Helper for dependency injection or standalone use"""
    return email_service
