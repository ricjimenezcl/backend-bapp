"""
Notification Helpers - Integration with booking creation flow
These helpers trigger notification dispatch from booking service
"""

import logging
import asyncio
from app.models.booking import Booking
from app.models.user import User
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def notify_booking_created(
    booking: Booking,
    provider: User,
    client: User,
    db: AsyncSession
) -> None:
    """
    Trigger notifications when booking is created
    This is called asynchronously to avoid blocking the create response
    """
    try:
        from app.services.notification_dispatcher import NotificationDispatcher
        
        dispatcher = NotificationDispatcher(db)
        result = await dispatcher.dispatch_booking_created(booking, provider, client)
        logger.info(f"✅ Booking created notifications dispatched: {result}")
        
    except Exception as e:
        logger.error(f"⚠️ Error notifying booking created: {str(e)}")
        # Don't re-raise, just log


def create_task_notify_booking_created(
    booking: Booking,
    provider: User,
    client: User,
    db: AsyncSession
) -> None:
    """
    Create async task for notification dispatch (non-blocking)
    """
    try:
        asyncio.create_task(
            notify_booking_created(booking, provider, client, db)
        )
        logger.info(f"📢 Notification task created for booking {booking.id}")
    except Exception as e:
        logger.error(f"⚠️ Error creating notification task: {str(e)}")
