
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional
from datetime import datetime
import json



# ...existing code...

class EventType(str, Enum):
    """System event types"""
    
    # Chat Events
    MESSAGE_CREATED = "message.created"
    MESSAGE_UPDATED = "message.updated"
    MESSAGE_DELETED = "message.deleted"
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_ARCHIVED = "conversation.archived"
    
    # Notification Events
    NOTIFICATION_CREATED = "notification.created"
    NOTIFICATION_READ = "notification.read"
    NOTIFICATION_SENT = "notification.sent"
    
    # User Events
    USER_REGISTERED = "user.registered"
    USER_VERIFIED = "user.verified"
    PROFILE_UPDATED = "profile.updated"
    
    # Booking Events
    BOOKING_CREATED = "booking.created"
    BOOKING_UPDATED = "booking.updated"
    BOOKING_ACCEPTED = "booking.accepted"
    BOOKING_REJECTED = "booking.rejected"
    BOOKING_CANCELLED = "booking.cancelled"
    BOOKING_COMPLETED = "booking.completed"
    
    # Payment Events
    PAYMENT_CREATED = "payment.created"
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    
    # Review Events
    REVIEW_CREATED = "review.created"
    REVIEW_UPDATED = "review.updated"
    
    # Provider Events
    PROVIDER_VERIFIED = "provider.verified"
    PROVIDER_VERIFICATION_REJECTED = "provider.verification.rejected"
    SERVICE_CREATED = "service.created"
    SERVICE_UPDATED = "service.updated"


@dataclass
class DomainEvent:
    """Base domain event with metadata"""
    event_type: EventType
    aggregate_id: str  # User ID, Booking ID, etc.
    aggregate_type: str  # "user", "booking", "message", etc.
    payload: Dict[str, Any]
    timestamp: Optional[datetime] = None
    correlation_id: Optional[str] = None  # For tracing
    source: str = "api"  # "api", "worker", "external"
    
    def __post_init__(self):
        from datetime import timezone
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
    
    def to_json(self) -> str:
        """Convert event to JSON for Redis pub/sub"""
        data = asdict(self)
        data['event_type'] = self.event_type.value
        data['timestamp'] = self.timestamp.isoformat()
        return json.dumps(data)
    
    @staticmethod
    def from_json(json_str: str) -> 'DomainEvent':
        """Create event from JSON"""
        data = json.loads(json_str)
        data['event_type'] = EventType(data['event_type'])
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return DomainEvent(**data)


@dataclass
class MessageCreatedEvent(DomainEvent):
    """Message created event"""
    
    def __init__(self, message_id: str, conversation_id: str, sender_id: str, 
                 content: str, **kwargs):
        super().__init__(
            event_type=EventType.MESSAGE_CREATED,
            aggregate_id=message_id,
            aggregate_type="message",
            payload={
                "message_id": message_id,
                "conversation_id": conversation_id,
                "sender_id": sender_id,
                "content": content,
            },
            **kwargs
        )


@dataclass
class ConversationCreatedEvent(DomainEvent):
    """Conversation created event"""
    
    def __init__(self, conversation_id: str, participant_ids: list, **kwargs):
        super().__init__(
            event_type=EventType.CONVERSATION_CREATED,
            aggregate_id=conversation_id,
            aggregate_type="conversation",
            payload={
                "conversation_id": conversation_id,
                "participant_ids": participant_ids,
            },
            **kwargs
        )


@dataclass
class NotificationCreatedEvent(DomainEvent):
    """Notification created event"""
    
    def __init__(self, notification_id: str, user_id: str, title: str, 
                 body: str, action_url: Optional[str] = None, **kwargs):
        super().__init__(
            event_type=EventType.NOTIFICATION_CREATED,
            aggregate_id=notification_id,
            aggregate_type="notification",
            payload={
                "notification_id": notification_id,
                "user_id": user_id,
                "title": title,
                "body": body,
                "action_url": action_url,
            },
            **kwargs
        )


@dataclass
class BookingCreatedEvent(DomainEvent):
    """Booking created event"""
    
    def __init__(self, booking_id: str, client_id: str, provider_id: str, 
                 service_id: str, scheduled_time: str, **kwargs):
        super().__init__(
            event_type=EventType.BOOKING_CREATED,
            aggregate_id=booking_id,
            aggregate_type="booking",
            payload={
                "booking_id": booking_id,
                "client_id": client_id,
                "provider_id": provider_id,
                "service_id": service_id,
                "scheduled_time": scheduled_time,
            },
            **kwargs
        )


# NUEVO: Evento para cambio de estado de reserva
@dataclass
class BookingStatusChangedEvent(DomainEvent):
    """Booking status changed event"""
    def __init__(self, booking_id: str, previous_status: str, new_status: str, changed_by_id: str, **kwargs):
        super().__init__(
            event_type=EventType.BOOKING_UPDATED,
            aggregate_id=booking_id,
            aggregate_type="booking",
            payload={
                "booking_id": booking_id,
                "previous_status": previous_status,
                "new_status": new_status,
                "changed_by_id": changed_by_id,
            },
            **kwargs
        )


@dataclass
class PaymentCompletedEvent(DomainEvent):
    """Payment completed event"""
    
    def __init__(self, payment_id: str, booking_id: str, amount: float, 
                 currency: str, **kwargs):
        super().__init__(
            event_type=EventType.PAYMENT_COMPLETED,
            aggregate_id=payment_id,
            aggregate_type="payment",
            payload={
                "payment_id": payment_id,
                "booking_id": booking_id,
                "amount": amount,
                "currency": currency,
            },
            **kwargs
        )


@dataclass
class ProviderVerifiedEvent(DomainEvent):
    """Provider verified event"""
    
    def __init__(self, provider_id: str, verified_by_admin_id: str, **kwargs):
        super().__init__(
            event_type=EventType.PROVIDER_VERIFIED,
            aggregate_id=provider_id,
            aggregate_type="provider",
            payload={
                "provider_id": provider_id,
                "verified_by_admin_id": verified_by_admin_id,
            },
            **kwargs
        )
