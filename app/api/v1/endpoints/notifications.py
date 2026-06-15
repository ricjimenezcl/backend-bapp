from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from typing import List
import logging

from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User
from app.models.notification import Notification
from app.schemas.notification import NotificationSchema
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[NotificationSchema])
async def get_notifications(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener mis notificaciones (recientes)"""
    service = NotificationService(db)
    notifications, _ = await service.get_user_notifications(current_user.id, skip=0, limit=50)
    return notifications

@router.patch("/mark-all-read")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Marcar todas las notificaciones del usuario como leídas"""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read == False)
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


@router.patch("/{notification_id}/read", response_model=NotificationSchema)
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Marcar una notificación como leída
    """
    service = NotificationService(db)
    notification = await service.get_notification_by_id(notification_id)
    if not notification or notification.user_id != current_user.id:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Notification not found")
    await service.mark_notification_as_read(notification_id)
    return await service.get_notification_by_id(notification_id)
