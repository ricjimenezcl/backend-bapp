"""
Sync Redis helpers — thin wrappers used by endpoints that predate the async client.

Design:
- Lazy initialization: the connection is not opened at import time.
- Respects REDIS_ENABLED: if False, all operations are no-ops that return safe defaults.
- Builds URL from REDIS_URL env var; falls back to REDIS_HOST/PORT/DB.
- All errors are caught and logged — callers never see a Redis exception.
"""

import json
import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------
# Internal state
# --------------------------------------------------

_redis = None  # lazily initialized


class _LazyRedis:
    """Proxy that forwards all attribute access to the lazily-initialized sync client."""
    def __getattr__(self, name):
        client = _get_client()
        if client is None:
            raise RuntimeError("Redis is not available (REDIS_ENABLED=False or connection failed)")
        return getattr(client, name)


redis = _LazyRedis()


def _get_client():
    """Return the sync Redis client, initializing it on first call."""
    global _redis

    if not settings.REDIS_ENABLED:
        return None

    if _redis is not None:
        return _redis

    try:
        import redis as _redis_lib

        url = settings.REDIS_URL
        if not url:
            pwd = f":{settings.REDIS_PASSWORD}@" if settings.REDIS_PASSWORD else ""
            url = f"redis://{pwd}{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"

        _redis = _redis_lib.Redis.from_url(url, decode_responses=True, socket_connect_timeout=3)
        logger.info("Sync Redis client initialized")
    except Exception as exc:
        logger.error(f"Sync Redis init failed: {exc}")
        _redis = None

    return _redis


# --------------------------------------------------
# Serialization
# --------------------------------------------------

def _serialize(value: Any) -> str:
    return json.dumps(value, default=str)


def _deserialize(value: Optional[str]) -> Optional[Any]:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


# --------------------------------------------------
# Cache
# --------------------------------------------------

def cache_set(key: str, value: Any, ttl: int = 60) -> bool:
    """Store a value in cache with TTL (seconds). Returns False on error."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.set(key, _serialize(value), ex=ttl)
        return True
    except Exception as exc:
        logger.error(f"Redis SET error [{key}]: {exc}")
        return False


def cache_get(key: str) -> Optional[Any]:
    """Retrieve a value from cache. Returns None on miss or error."""
    client = _get_client()
    if client is None:
        return None
    try:
        return _deserialize(client.get(key))
    except Exception as exc:
        logger.error(f"Redis GET error [{key}]: {exc}")
        return None


def cache_delete(key: str) -> bool:
    """Delete a key from cache."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.delete(key)
        return True
    except Exception as exc:
        logger.error(f"Redis DEL error [{key}]: {exc}")
        return False


def cache_publish(channel: str, payload: Any) -> bool:
    """Publish a message to a channel."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.publish(channel, _serialize(payload))
        return True
    except Exception as exc:
        logger.error(f"Redis PUBLISH error [{channel}]: {exc}")
        return False


# --------------------------------------------------
# Rate limiting
# --------------------------------------------------

def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Sliding-window rate limiter.
    Returns True if the request is allowed, False if the limit is exceeded.
    Fails open (returns True) on Redis errors.
    """
    client = _get_client()
    if client is None:
        return True  # Redis disabled → allow all
    try:
        current = client.incr(key)
        if current == 1:
            client.expire(key, window_seconds)
        return current <= limit
    except Exception as exc:
        logger.error(f"Redis RATE LIMIT error [{key}]: {exc}")
        return True  # fail-open


# --------------------------------------------------
# Distributed locks
# --------------------------------------------------

def acquire_lock(key: str, ttl: int = 30) -> bool:
    """Acquire a distributed lock. Returns False on error or if already held."""
    client = _get_client()
    if client is None:
        return True  # Redis disabled → allow operation
    try:
        return client.set(key, "1", nx=True, ex=ttl) is True
    except Exception as exc:
        logger.error(f"Redis LOCK error [{key}]: {exc}")
        return False


def release_lock(key: str) -> None:
    """Release a distributed lock."""
    client = _get_client()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as exc:
        logger.error(f"Redis UNLOCK error [{key}]: {exc}")


# --------------------------------------------------
# Health check
# --------------------------------------------------

def redis_healthcheck() -> bool:
    """Return True if Redis is reachable."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.set("healthcheck", "ok", ex=5)
        return client.get("healthcheck") == "ok"
    except Exception:
        return False
