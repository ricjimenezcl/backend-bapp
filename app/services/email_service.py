"""
Email Service - Sends emails via Resend API
Handles booking notifications, confirmations, and transactional emails
"""

import logging
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """
    Email service using Resend API for transactional emails
    """

    def __init__(self):
        """Initialize Resend client"""
        try:
            from resend import Resend
            self.client = Resend(api_key=settings.RESEND_API_KEY)
            self.from_email = settings.RESEND_FROM_EMAIL
            logger.info("✅ Resend email client initialized")
        except Exception as e:
            logger.error(f"⚠️ Resend initialization failed: {str(e)}")
            self.client = None

    def _build_html_template(self, template_name: str, context: dict) -> str:
        """Build HTML email template with context"""
        from jinja2 import Template
        
        templates = {
            "booking_created": """
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: #007AFF; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
                        .content { background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }
                        .button { background: #007AFF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin-top: 15px; }
                        .footer { margin-top: 20px; font-size: 12px; color: #666; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>Nueva Solicitud de Servicio</h2>
                        </div>
                        <div class="content">
                            <p>Hola {{ provider_name }},</p>
                            <p><strong>{{ client_name }}</strong> ha solicitado tu servicio.</p>
                            <h3>Detalles de la Solicitud:</h3>
                            <ul>
                                <li><strong>Servicio:</strong> {{ service_type }}</li>
                                <li><strong>Fecha Solicitada:</strong> {{ booking_date }}</li>
                                <li><strong>Ubicación:</strong> {{ location }}</li>
                                <li><strong>Descripción:</strong> {{ description }}</li>
                                <li><strong>Presupuesto:</strong> ${{ budget }}</li>
                            </ul>
                            <p>Accede a tu panel para aceptar o rechazar la solicitud.</p>
                            <a href="{{ action_link }}" class="button">Ver Solicitud</a>
                            <p style="color: #666; font-size: 14px; margin-top: 20px;">
                                Si tienes preguntas, contacta a nuestro equipo de soporte.
                            </p>
                        </div>
                        <div class="footer">
                            <p>&copy; 2026 BAPP Search. Todos los derechos reservados.</p>
                        </div>
                    </div>
                </body>
                </html>
            """,
            "booking_accepted": """
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: #34C759; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
                        .content { background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }
                        .button { background: #34C759; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin-top: 15px; }
                        .footer { margin-top: 20px; font-size: 12px; color: #666; }
                        .success-badge { color: #34C759; font-size: 24px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2><span class="success-badge">✓</span> ¡Tu Reserva Fue Confirmada!</h2>
                        </div>
                        <div class="content">
                            <p>Hola {{ client_name }},</p>
                            <p><strong>{{ provider_name }}</strong> ha confirmado tu solicitud de servicio.</p>
                            <h3>Próximos Pasos:</h3>
                            <ol>
                                <li>Ponte en contacto con {{ provider_name }} a través del chat</li>
                                <li>Confirma los detalles finales (hora, lugar, precio)</li>
                                <li>Completa el servicio</li>
                                <li>Deja una reseña</li>
                            </ol>
                            <p>Puedes comunicarte directamente con el proveedor:</p>
                            <ul>
                                <li><strong>Nombre:</strong> {{ provider_name }}</li>
                                <li><strong>Puntuación:</strong> {{ provider_rating }} ⭐</li>
                                <li><strong>Contacto:</strong> A través del chat en la app</li>
                            </ul>
                            <a href="{{ chat_link }}" class="button">Abrir Chat</a>
                            <p style="color: #666; font-size: 14px; margin-top: 20px;">
                                ¿Necesitas ayuda? Contacta a nuestro equipo de soporte.
                            </p>
                        </div>
                        <div class="footer">
                            <p>&copy; 2026 BAPP Search. Todos los derechos reservados.</p>
                        </div>
                    </div>
                </body>
                </html>
            """,
            "booking_rejected": """
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: #FF3B30; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
                        .content { background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }
                        .button { background: #007AFF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin-top: 15px; }
                        .footer { margin-top: 20px; font-size: 12px; color: #666; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>Actualización Sobre Tu Reserva</h2>
                        </div>
                        <div class="content">
                            <p>Hola {{ client_name }},</p>
                            <p>Lamentablemente, <strong>{{ provider_name }}</strong> no pudo aceptar tu solicitud de servicio en este momento.</p>
                            <p>Esto puede deberse a:</p>
                            <ul>
                                <li>Conflicto de horarios</li>
                                <li>Área geográfica fuera de servicio</li>
                                <li>Carga de trabajo actual</li>
                            </ul>
                            <h3>¿Qué hacer ahora?</h3>
                            <p>No te preocupes. Hay muchos otros proveedores disponibles que pueden ayudarte:</p>
                            <a href="{{ search_link }}" class="button">Ver Otros Proveedores</a>
                            <p style="color: #666; font-size: 14px; margin-top: 20px;">
                                Nuestra comunidad tiene cientos de proveedores calificados. Seguro encontrarás a alguien perfecto para tu necesidad.
                            </p>
                        </div>
                        <div class="footer">
                            <p>&copy; 2026 BAPP Search. Todos los derechos reservados.</p>
                        </div>
                    </div>
                </body>
                </html>
            """
        }
        
        template_html = templates.get(template_name, "")
        if not template_html:
            logger.error(f"⚠️ Template not found: {template_name}")
            return ""
        
        template = Template(template_html)
        return template.render(**context)

    async def send_booking_created_email(
        self,
        provider_email: str,
        provider_name: str,
        client_name: str,
        service_type: str,
        booking_date: str,
        location: str,
        description: str,
        budget: str,
        action_link: str
    ) -> bool:
        """Send email to provider when booking is created"""
        try:
            if not self.client:
                logger.warning("⚠️ Resend client not initialized, skipping email")
                return False

            html_body = self._build_html_template(
                "booking_created",
                {
                    "provider_name": provider_name,
                    "client_name": client_name,
                    "service_type": service_type,
                    "booking_date": booking_date,
                    "location": location,
                    "description": description,
                    "budget": budget,
                    "action_link": action_link
                }
            )

            response = self.client.emails.send({
                "from": self.from_email,
                "to": provider_email,
                "subject": f"🔔 Nueva Solicitud de Servicio de {client_name}",
                "html": html_body,
            })

            logger.info(f"✅ Booking created email sent to {provider_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send booking created email: {str(e)}")
            return False

    async def send_booking_accepted_email(
        self,
        client_email: str,
        client_name: str,
        provider_name: str,
        provider_rating: str,
        chat_link: str
    ) -> bool:
        """Send email to client when booking is accepted"""
        try:
            if not self.client:
                logger.warning("⚠️ Resend client not initialized, skipping email")
                return False

            html_body = self._build_html_template(
                "booking_accepted",
                {
                    "client_name": client_name,
                    "provider_name": provider_name,
                    "provider_rating": provider_rating,
                    "chat_link": chat_link
                }
            )

            response = self.client.emails.send({
                "from": self.from_email,
                "to": client_email,
                "subject": f"✅ {provider_name} Confirmó Tu Reserva",
                "html": html_body,
            })

            logger.info(f"✅ Booking accepted email sent to {client_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send booking accepted email: {str(e)}")
            return False

    async def send_booking_rejected_email(
        self,
        client_email: str,
        client_name: str,
        provider_name: str,
        search_link: str
    ) -> bool:
        """Send email to client when booking is rejected"""
        try:
            if not self.client:
                logger.warning("⚠️ Resend client not initialized, skipping email")
                return False

            html_body = self._build_html_template(
                "booking_rejected",
                {
                    "client_name": client_name,
                    "provider_name": provider_name,
                    "search_link": search_link
                }
            )

            response = self.client.emails.send({
                "from": self.from_email,
                "to": client_email,
                "subject": f"📢 Actualización Sobre Tu Reserva",
                "html": html_body,
            })

            logger.info(f"✅ Booking rejected email sent to {client_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send booking rejected email: {str(e)}")
            return False


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
