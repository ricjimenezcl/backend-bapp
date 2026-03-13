"""
Event Dispatcher Service for BAPP Search FASE 2
Handles event-driven notifications and broadcasting
"""

from typing import Callable, Dict, List, Any
from datetime import datetime
import asyncio
from enum import Enum


class EventType(str, Enum):
    """Available event types in the system"""
    # Booking events
    BOOKING_CREATED = "booking.created"
    BOOKING_ACCEPTED = "booking.accepted"
    BOOKING_REJECTED = "booking.rejected"
    BOOKING_COMPLETED = "booking.completed"
    BOOKING_CANCELLED = "booking.cancelled"
    
    # Chat events
    CONVERSATION_STARTED = "conversation.started"
    MESSAGE_SENT = "message.sent"
    
    # Notification events
    NOTIFICATION_CREATED = "notification.created"
    NOTIFICATION_READ = "notification.read"


class EventPayload:
    """Base class for event payloads"""
    
    def __init__(self, event_type: EventType, data: Dict[str, Any]):
        self.event_type = event_type
        self.data = data
        self.timestamp = datetime.utcnow()
        self.id = f"{event_type}_{int(datetime.utcnow().timestamp() * 1000)}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }


class EventDispatcher:
    """
    Event dispatcher for handling system-wide events.
    Uses a simple in-memory event bus (can be extended to Redis/RabbitMQ).
    """
    
    def __init__(self):
        # Dict mapping event types to list of handlers
        self._handlers: Dict[EventType, List[Callable]] = {}
        # Event history for debugging
        self._event_history: List[EventPayload] = []
        # Max history size
        self._max_history = 1000
    
    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """
        Subscribe a handler to an event type.
        Handler should be async: async def handler(payload: EventPayload)
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        print(f"✅ Handler subscribed to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        """Unsubscribe a handler from an event type"""
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
            print(f"✅ Handler unsubscribed from {event_type.value}")
    
    async def emit(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """
        Emit an event and trigger all registered handlers.
        Handlers run concurrently with asyncio.gather.
        """
        payload = EventPayload(event_type, data)
        
        # Add to history
        self._event_history.append(payload)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        print(f"📤 Event emitted: {event_type.value} (ID: {payload.id})")
        
        # Get handlers for this event type
        handlers = self._handlers.get(event_type, [])
        
        if not handlers:
            print(f"   ⚠️  No handlers registered for {event_type.value}")
            return
        
        # Execute all handlers concurrently
        try:
            await asyncio.gather(
                *[handler(payload) for handler in handlers],
                return_exceptions=True
            )
            print(f"   ✅ Executed {len(handlers)} handler(s)")
        except Exception as e:
            print(f"   ❌ Error executing handlers: {str(e)}")
    
    def get_event_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent events for debugging"""
        return [event.to_dict() for event in self._event_history[-limit:]]
    
    def clear_history(self) -> None:
        """Clear event history"""
        self._event_history.clear()
        print("✅ Event history cleared")


# Global dispatcher instance
_dispatcher: EventDispatcher = None


def get_dispatcher() -> EventDispatcher:
    """Get or create the global event dispatcher"""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = EventDispatcher()
    return _dispatcher


def reset_dispatcher() -> None:
    """Reset dispatcher (for testing)"""
    global _dispatcher
    _dispatcher = None
