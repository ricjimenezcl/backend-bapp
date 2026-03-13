# app/infra/redis/__init__.py
"""Redis infrastructure module - connection, caching, and pub/sub"""

from app.infra.redis.client import RedisClient, redis_client
from app.infra.redis.cache import (
    get_notifications_cache, set_notifications_cache,
    get_chat_messages_cache, set_chat_messages_cache,
    get_chat_conversations_cache, set_chat_conversations_cache,
    get_nearby_providers_cache, set_nearby_providers_cache,
    get_provider_profile_cache, set_provider_profile_cache, invalidate_provider_cache,
    get_provider_detailed_cache, set_provider_detailed_cache, invalidate_provider_detailed_cache,
    invalidate_client_bookings_cache, invalidate_provider_bookings_cache,
    get_slots_cache, set_slots_cache, invalidate_slots_cache,
)

__all__ = [
    "RedisClient",
    "redis_client",
    "get_notifications_cache", "set_notifications_cache",
    "get_chat_messages_cache", "set_chat_messages_cache",
    "get_chat_conversations_cache", "set_chat_conversations_cache",
    "get_nearby_providers_cache", "set_nearby_providers_cache",
    "get_provider_profile_cache", "set_provider_profile_cache", "invalidate_provider_cache",
    "get_provider_detailed_cache", "set_provider_detailed_cache", "invalidate_provider_detailed_cache",
    "invalidate_client_bookings_cache", "invalidate_provider_bookings_cache",
    "get_slots_cache", "set_slots_cache", "invalidate_slots_cache",
]
