"""
Notification Helpers - Integration with booking creation flow
These helpers trigger notification dispatch from booking service
"""

import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def _notify_booking_created_data(
    booking_data: Dict[str, Any],
    provider_data: Dict[str, Any],
    client_data: Dict[str, Any],
) -> None:
    """
    Envía emails de nueva reserva usando dicts simples (sin ORM objects)
    para evitar DetachedInstanceError tras el cierre del DB session.
    """
    try:
        from app.services.email_service import EmailService
        email_service = EmailService()

        scheduled_date = booking_data.get("scheduled_date") or "A Coordinar"
        scheduled_time = booking_data.get("scheduled_time") or ""
        booking_date = f"{scheduled_date} {scheduled_time}".strip()

        result = await email_service.send_booking_created(
            client_email=client_data["email"],
            provider_email=provider_data["email"],
            data={
                "client_name": client_data.get("full_name") or client_data["email"],
                "provider_name": provider_data.get("full_name") or provider_data["email"],
                "service_name": booking_data.get("service_category") or "Servicio Solicitado",
                "booking_date": booking_date,
                "location": booking_data.get("location_address") or "A Definir",
                "description": booking_data.get("description") or "Sin descripción",
                "total_price": booking_data.get("total_price", "0"),
                "booking_id": booking_data["id"],
            }
        )
        if result:
            logger.info(f"✅ Emails de reserva enviados a {client_data['email']} y {provider_data['email']}")
        else:
            logger.warning(f"⚠️ Email de reserva falló para {client_data['email']} / {provider_data['email']}")
    except Exception as e:
        logger.error(f"❌ Error en _notify_booking_created_data: {str(e)}", exc_info=True)


def create_task_notify_booking_created_data(
    booking_data: Dict[str, Any],
    provider_data: Dict[str, Any],
    client_data: Dict[str, Any],
) -> None:
    """
    Crea un asyncio task para enviar emails de reserva (non-blocking).
    Recibe dicts con datos ya extraídos del ORM mientras el session estaba activo.
    """
    try:
        asyncio.create_task(
            _notify_booking_created_data(booking_data, provider_data, client_data)
        )
        logger.info(f"📢 Email task creado para reserva {booking_data.get('id')}")
    except Exception as e:
        logger.error(f"⚠️ Error creando email task: {str(e)}")
