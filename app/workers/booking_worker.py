"""
Booking Worker - Processes booking-related tasks
Handles reminders, completion, and status updates
"""

import logging
from datetime import datetime
from sqlalchemy import select, update
from app.infra.queue.job import Job, JobType
from app.workers.base_worker import BaseWorker
from app.services.email_service import email_service
from app.models.user import User
from app.models.provider import Provider
from app.core.database import AsyncSessionLocal

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
            return False
        except Exception as e:
            logger.error(f"❌ Booking worker error: {str(e)}")
            return False
    
    async def _send_reminder(self, job: Job) -> bool:
        """Send booking reminder notification to both client and provider"""
        try:
            payload = job.payload
            booking_id = payload.get("booking_id")
            
            async with AsyncSessionLocal() as db:
                # Obtener info necesaria
                client_id = payload.get("client_id")
                provider_id = payload.get("provider_id")
                
                # Fetch users
                res = await db.execute(select(User).where(User.id == client_id))
                client = res.scalars().first()
                res = await db.execute(select(User).where(User.id == provider_id))
                provider = res.scalars().first()
                
                if not client or not provider:
                    return False

                data = {
                    "service_name": payload.get("service_name", "Servicio BAPP"),
                    "booking_date": payload.get("scheduled_time", "Hoy"),
                    "location": payload.get("location", "Ver en la app")
                }

                # Email al cliente
                await email_service.send_booking_reminder(
                    client.email, client.full_name or client.email, False, 
                    {**data, "other_party_name": provider.full_name or "Proveedor"}
                )
                
                # Email al proveedor
                await email_service.send_booking_reminder(
                    provider.email, provider.full_name or provider.email, True,
                    {**data, "other_party_name": client.full_name or "Cliente"}
                )
            
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

            async with AsyncSessionLocal() as db:
                from app.models.booking import Booking, BookingStatus
                # 1. Marcar como COMPLETED en BD
                now = datetime.utcnow()
                await db.execute(
                    update(Booking)
                    .where(Booking.id == booking_id)
                    .values(status=BookingStatus.COMPLETED, completed_at=now)
                )
                await db.commit()
                
                # 2. Obtener nombres para el correo
                res = await db.execute(select(User).where(User.id == client_id))
                client = res.scalars().first()
                res = await db.execute(select(User).where(User.id == provider_id))
                provider = res.scalars().first()

                if client and provider:
                    await email_service.send_review_reminder(
                        email=client.email,
                        user_name=client.full_name or client.email,
                        provider_name=provider.full_name or provider.email,
                        booking_id=str(booking_id)
                    )

            logger.info(f"✅ Completion processed for booking {booking_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Completion processed failed: {str(e)}")
            return False
