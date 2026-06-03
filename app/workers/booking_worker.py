# app/workers/booking_worker.py
"""
Booking Worker - Processes booking-related tasks
Handles reminders, completion, and status updates
"""

import logging
from datetime import datetime, timezone
from sqlalchemy import select, update
from app.infra.queue.job import Job, JobType
from app.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class BookingWorker(BaseWorker):
    """Worker for booking-related background tasks"""
    
    def __init__(self):
        super().__init__(job_types=[
            JobType.SEND_BOOKING_REMINDER,
            JobType.PROCESS_BOOKING_COMPLETION,
        ])
    
    async def handle_job(self, job: Job) -> bool:
        """Process booking job"""
        
        try:
            if job.job_type == JobType.SEND_BOOKING_REMINDER:
                return await self._send_reminder(job)
            
            elif job.job_type == JobType.PROCESS_BOOKING_COMPLETION:
                return await self._process_completion(job)
            
            else:
                logger.warning(f"Unknown job type: {job.job_type}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Booking worker error: {str(e)}")
            return False
    
    async def _send_reminder(self, job: Job) -> bool:
        """Send booking reminder notification"""
        try:
            payload = job.payload
            booking_id = payload.get("booking_id")
            client_id = payload.get("client_id")
            provider_id = payload.get("provider_id")
            scheduled_time = payload.get("scheduled_time")
            
            logger.info(f"⏰ Sending reminder for booking {booking_id}")
            
            # TODO: Send notification to both client and provider
            # await enqueue_notification(
            #     user_id=client_id,
            #     title="Recordatorio de cita",
            #     body=f"Tu cita está programada para {scheduled_time}",
            #     action_url=f"/bookings/{booking_id}"
            # )
            
            logger.info(f"✅ Reminder sent for booking {booking_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Reminder send failed: {str(e)}")
            return False
    
    async def _process_completion(self, job: Job) -> bool:
        """Process booking completion — update DB + send review request to client"""
        try:
            payload = job.payload
            booking_id = payload.get("booking_id")
            client_id = payload.get("client_id")
            provider_id = payload.get("provider_id")

            logger.info(f"✅ Processing completion for booking {booking_id}")

            from app.core.database import get_db_async
            from app.models.booking import Booking, BookingStatus
            from app.models.notification import NotificationType
            from app.services.notification_service import NotificationService
            from app.api.websocket.connection_manager import connection_manager

            async for db in get_db_async():
                # 1. Marcar como COMPLETED en BD
                now = datetime.now(timezone.utc)
                await db.execute(
                    update(Booking)
                    .where(Booking.id == booking_id)
                    .values(status=BookingStatus.COMPLETED, completed_at=now)
                )
                await db.commit()
                logger.info(f"📌 Booking {booking_id} marked as COMPLETED in DB")

                notification_svc = NotificationService(db)

                # 2. Notificar al cliente: reserva completada
                await notification_svc.create_booking_notification(
                    user_id=client_id,
                    notification_type=NotificationType.BOOKING_COMPLETED,
                    booking_id=booking_id,
                    message="Tu servicio ha sido completado. ¿Qué te pareció?"
                )

                # 3. Enviar evento WS al cliente (completada + solicitud de reseña)
                await connection_manager.broadcast_to_user(client_id, {
                    "type": "notification",
                    "notification_type": "booking_completed",
                    "related_entity_id": booking_id,
                    "message": "Tu servicio ha sido completado."
                })
                await connection_manager.broadcast_to_user(client_id, {
                    "type": "notification",
                    "notification_type": "booking_review_request",
                    "related_entity_id": booking_id,
                    "message": "¿Cómo fue tu experiencia? Califica el servicio."
                })

                # 4. Guardar notificación de review-request en BD
                await notification_svc.create_booking_notification(
                    user_id=client_id,
                    notification_type=NotificationType.BOOKING_REVIEW_REQUEST,
                    booking_id=booking_id,
                    message="¿Cómo fue tu experiencia? Califica el servicio recibido."
                )

                # 5. Pub/Sub offline (si el cliente no está conectado)
                from app.infra.pubsub import publish_to_user
                publish_to_user(client_id, "booking_review_request", {
                    "booking_id": booking_id,
                    "related_entity_id": booking_id,
                })

                logger.info(f"✅ Booking {booking_id} completion processed — review request sent to client {client_id}")
                return True

        except Exception as e:
            logger.error(f"❌ Booking completion processing failed: {str(e)}")
            return False


# Worker instance
booking_worker = BookingWorker()
