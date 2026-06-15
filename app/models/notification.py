"""
Notification model for BAPP Search
Handles user notifications for various events
"""

from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class NotificationType(str, PyEnum):
    """Notification type enumeration"""
    MESSAGE = "message"
    BOOKING_RECEIVED = "booking_received"
    BOOKING_CONFIRMED = "booking_confirmed"
    BOOKING_REJECTED = "booking_rejected"
    BOOKING_COMPLETED = "booking_completed"
    BOOKING_REVIEW_REQUEST = "booking_review_request"
    REVIEW_RECEIVED = "review_received"
    SERVICE_APPROVED = "service_approved"
    SERVICE_REJECTED = "service_rejected"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_FAILED = "payment_failed"


class Notification(Base):
    """User notifications for various events"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Notification type and content
    notification_type = Column(
        SQLEnum(NotificationType, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=NotificationType.MESSAGE,
        index=True
    )
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    
    # Related entity (optional)
    related_entity_type = Column(String(50), nullable=True)  # e.g., "booking", "service", "review"
    related_entity_id = Column(Integer, nullable=True)
    
    # Notification status
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="notifications")

    def __repr__(self):
        return f"<Notification(id={self.id}, user_id={self.user_id}, type={self.notification_type})>"

    def mark_as_read(self):
        """Mark notification as read"""
        self.is_read = True
        self.read_at = datetime.utcnow()
