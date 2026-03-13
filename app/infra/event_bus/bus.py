# app/infra/event_bus/bus.py
"""
Event Bus - Publish/Subscribe pattern using Redis
Enables loose coupling between components via domain events
"""

import json
import logging
from typing import Callable, Dict, List, Optional, Any
from app.infra.redis.client import redis_client
from app.infra.event_bus.event import DomainEvent, EventType

logger = logging.getLogger(__name__)


class EventBus:
    """
    Central event bus for publishing and subscribing to domain events.
    Uses Redis Pub/Sub for real-time event distribution.
    """
    
    def __init__(self):
        self._handlers: Dict[EventType, List[Callable]] = {}
        self._pubsub = None
    
    async def publish(self, event: DomainEvent) -> int:
        """
        Publish event to all subscribers
        
        Args:
            event: DomainEvent instance
            
        Returns:
            Number of subscribers that received the message
        """
        try:
            channel = event.event_type.value
            message = event.to_json()
            
            subscribers = await redis_client.publish(channel, message)
            logger.info(f"📤 Event published: {channel} (subscribers: {subscribers})")
            
            return subscribers
            
        except Exception as e:
            logger.error(f"❌ Event publish failed: {str(e)}")
            return 0
    
    async def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """
        Subscribe to event type with handler function
        
        Args:
            event_type: EventType to subscribe to
            handler: Async callback function(event: DomainEvent)
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        self._handlers[event_type].append(handler)
        logger.info(f"📥 Handler subscribed to {event_type.value}")
    
    async def listen(self) -> None:
        """
        Start listening to all subscribed event types
        Runs indefinitely, processes incoming events
        """
        try:
            # Subscribe to all registered event types
            channels = [et.value for et in self._handlers.keys()]
            
            if not channels:
                logger.warning("No event handlers registered")
                return
            
            self._pubsub = await redis_client.subscribe(*channels)
            
            logger.info(f"🎧 Event listener started, listening to {len(channels)} channels")
            
            # Listen for events
            async for message in self._pubsub.listen():
                if message['type'] == 'message':
                    try:
                        event = DomainEvent.from_json(message['data'])
                        
                        # Execute all handlers for this event type
                        if event.event_type in self._handlers:
                            for handler in self._handlers[event.event_type]:
                                try:
                                    await handler(event)
                                except Exception as e:
                                    logger.error(f"Handler error for {event.event_type.value}: {str(e)}")
                    
                    except Exception as e:
                        logger.error(f"Event parsing error: {str(e)}")
        
        except Exception as e:
            logger.error(f"❌ Event listener error: {str(e)}")
            raise
    
    async def stop_listening(self) -> None:
        """Stop event listener"""
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
            self._pubsub = None
            logger.info("Event listener stopped")
    
    def get_subscriptions(self) -> Dict[str, int]:
        """Get current subscription counts"""
        return {
            event_type.value: len(handlers)
            for event_type, handlers in self._handlers.items()
        }
    
    async def clear_subscriptions(self) -> None:
        """Clear all subscriptions"""
        await self.stop_listening()
        self._handlers.clear()
        logger.info("All subscriptions cleared")


# Singleton instance
event_bus = EventBus()
