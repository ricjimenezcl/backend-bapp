from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.notification import NotificationSchema
from app.services.notification_service import NotificationService
from app.infra.redis.cache import get_notifications_cache, set_notifications_cache

router = APIRouter()


@router.get("/", response_model=List[NotificationSchema])
async def get_notifications(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener mis notificaciones (recientes) con cache best-effort
    """
    cached = get_notifications_cache(current_user.id)
    if cached:
        print(f"✅ [CACHE] Notificaciones hit ({current_user.id})")
        return cached
    service = NotificationService(db)
    notifications = await service.get_my_notifications(current_user.id)
    set_notifications_cache(current_user.id, notifications)
    print(f"✅ [CACHE] Guardado notificaciones ({current_user.id})")
    return notifications

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
    return await service.mark_as_read(notification_id, current_user.id)
