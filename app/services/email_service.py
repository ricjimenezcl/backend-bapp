"""
Email Service - Sends emails via Amazon SES
Handles booking notifications, confirmations, and transactional emails
"""

import logging
import asyncio
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """
    Email service using Amazon SES for transactional emails
    """

    def __init__(self):
        """Initialize SES client"""
        try:
            import boto3
            self._ses = boto3.client(
                "ses",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            self.from_email = settings.SES_FROM_EMAIL
            logger.info("✅ Amazon SES email client initialized")
        except Exception as e:
            logger.error(f"⚠️ SES initialization failed: {str(e)}")
            self._ses = None

    def _send_raw(self, to: str, subject: str, html: str) -> bool:
        """Blocking SES send — run via executor to avoid blocking event loop"""
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
            "email_verification": """
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: #007AFF; color: white; padding: 30px 20px; border-radius: 8px 8px 0 0; text-align: center; }
                        .content { background: #f9f9f9; padding: 30px 20px; border-radius: 0 0 8px 8px; }
                        .button { background: #007AFF; color: white !important; padding: 14px 32px; text-decoration: none; border-radius: 6px; display: inline-block; margin-top: 20px; font-weight: bold; font-size: 16px; }
                        .footer { margin-top: 20px; font-size: 12px; color: #666; text-align: center; }
                        .note { font-size: 13px; color: #888; margin-top: 16px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>Verifica tu correo electrónico</h2>
                        </div>
                        <div class="content">
                            <p>Hola {{ user_name }},</p>
                            <p>Gracias por registrarte en <strong>BAPP Search</strong>. Para activar tu cuenta, haz clic en el botón de abajo:</p>
                            <div style="text-align: center;">
                                <a href="{{ verification_link }}" class="button">Verificar mi cuenta</a>
                            </div>
                            <p class="note">Este enlace expira en 24 horas. Si no creaste esta cuenta, puedes ignorar este correo.</p>
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
            """,
            "booking_completed": """
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: #34C759; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
                        .content { background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }
                        .review-box { background: #fff8e1; border: 1px solid #FFD60A; border-radius: 8px; padding: 16px; margin: 16px 0; text-align: center; }
                        .stars { font-size: 28px; letter-spacing: 4px; }
                        .button { background: #FFD60A; color: #333 !important; font-weight: bold; padding: 14px 28px; text-decoration: none; border-radius: 6px; display: inline-block; margin-top: 10px; }
                        .footer { margin-top: 20px; font-size: 12px; color: #666; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>✅ Tu Servicio Fue Completado</h2>
                        </div>
                        <div class="content">
                            <p>Hola {{ client_name }},</p>
                            <p>Tu servicio con <strong>{{ provider_name }}</strong> ha sido marcado como completado.</p>
                            <div class="review-box">
                                <div class="stars">⭐⭐⭐⭐⭐</div>
                                <p><strong>¿Cómo fue tu experiencia?</strong></p>
                                <p style="color:#555; font-size:14px;">Tu opinión ayuda a otros usuarios a encontrar los mejores proveedores.</p>
                                <a href="{{ review_url }}" class="button">Dejar mi reseña ahora</a>
                            </div>
                            <p style="color:#888; font-size:13px; margin-top:16px;">
                                También puedes calificar el servicio directamente desde la app en la sección <em>Mis Reservas → Historial</em>.
                            </p>
                        </div>
                        <div class="footer">
                            <p>&copy; 2026 BAPP Search. Todos los derechos reservados.</p>
                        </div>
                    </div>
                </body>
                </html>
            """,
            "booking_expired": """
                <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background: #FF9500; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
                        .content { background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }
                        .button { background: #007AFF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; margin-top: 15px; }
                        .footer { margin-top: 20px; font-size: 12px; color: #666; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>⏰ Tu Solicitud Expiró</h2>
                        </div>
                        <div class="content">
                            <p>Hola {{ client_name }},</p>
                            <p>Tu solicitud de <strong>{{ service_name }}</strong> programada para el <strong>{{ scheduled_date }}</strong> expiró sin ser confirmada por el proveedor.</p>
                            <p>Esto puede pasar cuando el proveedor no está disponible en ese horario. ¡No te desanimes!</p>
                            <h3>¿Qué puedes hacer?</h3>
                            <ul>
                                <li>Buscar otro proveedor disponible para el mismo servicio</li>
                                <li>Solicitar el mismo servicio para una fecha diferente</li>
                            </ul>
                            <a href="{{ search_url }}" class="button">Buscar Proveedores Disponibles</a>
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

    async def send_verification_email(
        self,
        user_email: str,
        user_name: str,
        verification_link: str,
    ) -> bool:
        """Send email verification link after registration"""
        html_body = self._build_html_template(
            "email_verification",
            {
                "user_name": user_name,
                "verification_link": verification_link,
            },
        )
        result = await self._send(
            user_email,
            "Verifica tu cuenta en BAPP Search",
            html_body,
        )
        if result:
            logger.info(f"✅ Verification email sent to {user_email}")
        return result

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
                "action_link": action_link,
            },
        )
        result = await self._send(
            provider_email,
            f"🔔 Nueva Solicitud de Servicio de {client_name}",
            html_body,
        )
        if result:
            logger.info(f"✅ Booking created email sent to {provider_email}")
        return result

    async def send_booking_accepted_email(
        self,
        client_email: str,
        client_name: str,
        provider_name: str,
        provider_rating: str,
        chat_link: str
    ) -> bool:
        """Send email to client when booking is accepted"""
        html_body = self._build_html_template(
            "booking_accepted",
            {
                "client_name": client_name,
                "provider_name": provider_name,
                "provider_rating": provider_rating,
                "chat_link": chat_link,
            },
        )
        result = await self._send(
            client_email,
            f"✅ {provider_name} Confirmó Tu Reserva",
            html_body,
        )
        if result:
            logger.info(f"✅ Booking accepted email sent to {client_email}")
        return result

    async def send_booking_rejected_email(
        self,
        client_email: str,
        client_name: str,
        provider_name: str,
        search_link: str
    ) -> bool:
        """Send email to client when booking is rejected"""
        html_body = self._build_html_template(
            "booking_rejected",
            {
                "client_name": client_name,
                "provider_name": provider_name,
                "search_link": search_link,
            },
        )
        result = await self._send(
            client_email,
            "📢 Actualización Sobre Tu Reserva",
            html_body,
        )
        if result:
            logger.info(f"✅ Booking rejected email sent to {client_email}")
        return result

    async def send_booking_completed_email(
        self,
        client_email: str,
        client_name: str,
        provider_name: str,
        review_url: str,
    ) -> bool:
        """Send email to client when booking is completed, with link to leave review."""
        html_body = self._build_html_template(
            "booking_completed",
            {
                "client_name": client_name,
                "provider_name": provider_name,
                "review_url": review_url,
            },
        )
        result = await self._send(
            client_email,
            f"⭐ ¿Cómo fue tu experiencia con {provider_name}?",
            html_body,
        )
        if result:
            logger.info(f"✅ Booking completed email sent to {client_email}")
        return result

    async def send_booking_expired_email(
        self,
        client_email: str,
        client_name: str,
        service_name: str,
        scheduled_date: str,
        search_url: str,
    ) -> bool:
        """Send email to client when a PENDING booking expires without provider action."""
        html_body = self._build_html_template(
            "booking_expired",
            {
                "client_name": client_name,
                "service_name": service_name,
                "scheduled_date": scheduled_date,
                "search_url": search_url,
            },
        )
        result = await self._send(
            client_email,
            "Tu solicitud de servicio expiró — Encuentra otro proveedor",
            html_body,
        )
        if result:
            logger.info(f"✅ Booking expired email sent to {client_email}")
        return result


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
