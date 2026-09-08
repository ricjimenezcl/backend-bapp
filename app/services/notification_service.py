"""
Notification Service for BAPP Search FASE 2
Handles notification creation, retrieval, and management
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_

from app.models.notification import Notification, NotificationType


class NotificationService:
    """Service for managing user notifications"""
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== Notification Creation ====================

    async def create_notification(
        self,
        user_id: int,
        notification_type: NotificationType,
        title: str,
        content: str,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[int] = None
    ) -> Notification:
        """Create a new notification"""
        try:
            notification = Notification(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                content=content,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id
            )
            
            self.db.add(notification)
            await self.db.commit()
            await self.db.refresh(notification)
            
            return notification
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error creating notification: {str(e)}")

    async def create_message_notification(
        self,
        user_id: int,
        sender_name: str,
        conversation_id: int
    ) -> Notification:
        """Create a notification for new message"""
        return await self.create_notification(
            user_id=user_id,
            notification_type=NotificationType.MESSAGE,
            title=f"Nuevo mensaje de {sender_name}",
            content=f"Tienes un nuevo mensaje de {sender_name}",
            related_entity_type="conversation",
            related_entity_id=conversation_id
        )

    async def create_booking_notification(
        self,
        user_id: int,
        notification_type: NotificationType,
        booking_id: int,
        message: str
    ) -> Notification:
        """Create a notification for booking events"""
        type_messages = {
            NotificationType.BOOKING_RECEIVED: "Nueva Solicitud de Reserva",
            NotificationType.BOOKING_REQUEST_SENT: "Solicitud Enviada",
            NotificationType.BOOKING_CONFIRMED: "Reserva Confirmada",
            NotificationType.BOOKING_REJECTED: "Reserva Rechazada",
            NotificationType.BOOKING_REMINDER_24H: "Reserva en menos de 24 horas",
            NotificationType.BOOKING_COMPLETED: "Reserva Completada",
            NotificationType.BOOKING_REVIEW_REQUEST: "Califica tu servicio",
        }
        
        title = type_messages.get(notification_type, "Notificación de Reserva")
        
        return await self.create_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            content=message,
            related_entity_type="booking",
            related_entity_id=booking_id
        )

    # ==================== Notification Retrieval ====================

    async def get_notification_by_id(
        self,
        notification_id: int
    ) -> Optional[Notification]:
        """Get a notification by ID"""
        try:
            result = await self.db.execute(
                select(Notification).where(Notification.id == notification_id)
            )
            return result.scalars().first()
            
        except Exception as e:
            raise Exception(f"Error retrieving notification: {str(e)}")

    async def get_user_notifications(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
        unread_only: bool = False
    ) -> tuple[List[Notification], int]:
        """Get notifications for a user"""
        try:
            query = select(Notification).where(
                Notification.user_id == user_id
            )
            
            if unread_only:
                query = query.where(Notification.is_read == False)
            
            query = query.order_by(desc(Notification.created_at))
            
            # Get total count
            count_result = await self.db.execute(
                select(Notification).where(
                    Notification.user_id == user_id
                )
            )
            total = len(count_result.scalars().all())
            
            # Get paginated results
            result = await self.db.execute(
                query.offset(skip).limit(limit)
            )
            notifications = result.scalars().all()
            
            return notifications, total
            
        except Exception as e:
            raise Exception(f"Error retrieving notifications: {str(e)}")

    async def get_unread_notification_count(
        self,
        user_id: int
    ) -> int:
        """Get count of unread notifications for a user"""
        try:
            result = await self.db.execute(
                select(Notification).where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.is_read == False
                    )
                )
            )
            notifications = result.scalars().all()
            
            return len(notifications)
            
        except Exception as e:
            raise Exception(f"Error getting unread count: {str(e)}")

    async def get_notifications_by_type(
        self,
        user_id: int,
        notification_type: NotificationType,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[List[Notification], int]:
        """Get notifications filtered by type"""
        try:
            query = select(Notification).where(
                and_(
                    Notification.user_id == user_id,
                    Notification.notification_type == notification_type.value
                )
            ).order_by(desc(Notification.created_at))
            
            # Get total count
            count_result = await self.db.execute(
                select(Notification).where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.notification_type == notification_type.value
                    )
                )
            )
            total = len(count_result.scalars().all())
            
            # Get paginated results
            result = await self.db.execute(
                query.offset(skip).limit(limit)
            )
            notifications = result.scalars().all()
            
            return notifications, total
            
        except Exception as e:
            raise Exception(f"Error retrieving notifications by type: {str(e)}")

    # ==================== Notification Status ====================

    async def mark_notification_as_read(
        self,
        notification_id: int
    ) -> bool:
        """Mark a notification as read"""
        try:
            result = await self.db.execute(
                select(Notification).where(Notification.id == notification_id)
            )
            notification = result.scalars().first()
            
            if not notification:
                raise ValueError("Notification not found")
            
            notification.mark_as_read()
            await self.db.commit()
            
            return True
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error marking notification as read: {str(e)}")

    async def mark_all_user_notifications_as_read(
        self,
        user_id: int
    ) -> int:
        """Mark all unread notifications as read for a user"""
        try:
            result = await self.db.execute(
                select(Notification).where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.is_read == False
                    )
                )
            )
            notifications = result.scalars().all()
            
            for notification in notifications:
                notification.mark_as_read()
            
            await self.db.commit()
            
            return len(notifications)
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error marking notifications as read: {str(e)}")

    # ==================== Notification Deletion ====================

    async def delete_notification(
        self,
        notification_id: int
    ) -> bool:
        """Delete a notification"""
        try:
            result = await self.db.execute(
                select(Notification).where(Notification.id == notification_id)
            )
            notification = result.scalars().first()
            
            if not notification:
                raise ValueError("Notification not found")
            
            await self.db.delete(notification)
            await self.db.commit()
            
            return True
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error deleting notification: {str(e)}")

    async def delete_old_notifications(
        self,
        days: int = 30
    ) -> int:
        """Delete notifications older than specified days"""
        try:
            from datetime import timedelta
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            result = await self.db.execute(
                select(Notification).where(
                    Notification.created_at < cutoff_date
                )
            )
            old_notifications = result.scalars().all()
            
            for notification in old_notifications:
                await self.db.delete(notification)
            
            await self.db.commit()
            
            return len(old_notifications)
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error deleting old notifications: {str(e)}")

    # ==================== Bulk Operations ====================

    async def create_bulk_notifications(
        self,
        user_ids: List[int],
        notification_type: NotificationType,
        title: str,
        content: str
    ) -> int:
        """Create the same notification for multiple users"""
        try:
            notifications = [
                Notification(
                    user_id=user_id,
                    notification_type=notification_type,
                    title=title,
                    content=content
                )
                for user_id in user_ids
            ]
            
            self.db.add_all(notifications)
            await self.db.commit()
            
            return len(notifications)
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error creating bulk notifications: {str(e)}")
