import os
import json
import logging
from typing import Any, Optional

import redis

# --------------------------------------------------
# Configuración básica
# --------------------------------------------------

from app.core.config import settings

REDIS_URL = settings.REDIS_URL if hasattr(settings, 'REDIS_URL') else 'redis://localhost:6379/0'

# --------------------------------------------------
# Logger
# --------------------------------------------------

logger = logging.getLogger("redis")
logger.setLevel(logging.INFO)

# --------------------------------------------------
# Cliente Redis (singleton)
# --------------------------------------------------

redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# --------------------------------------------------
# Helpers generales
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
    """
    Guarda un valor en cache con TTL (segundos)
    """
    try:
        redis.set(key, _serialize(value), ex=ttl)
        return True
    except Exception as e:
        logger.error(f"Redis SET error [{key}]: {e}")
        return False


def cache_get(key: str) -> Optional[Any]:
    """
    Obtiene un valor desde cache
    """
    try:
        value = redis.get(key)
        return _deserialize(value)
    except Exception as e:
        logger.error(f"Redis GET error [{key}]: {e}")
        return None

def cache_delete(key: str) -> bool:
    """
    Elimina un valor del cache
    """
    try:
        redis.delete(key)
        return True
    except Exception as e:
        logger.error(f"Redis DEL error [{key}]: {e}")
        return False

def cache_publish(channel: str, payload: Any) -> bool:
    """
    Publica un mensaje en un canal
    """
    try:
        redis.publish(channel, _serialize(payload))
        return True
    except Exception as e:
        logger.error(f"Redis PUBLISH error [{channel}]: {e}")
        return False

def rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Retorna True si está permitido, False si excede el límite
    """
    try:
        current = redis.incr(key)
        if current == 1:
            redis.expire(key, window_seconds)
        return current <= limit
    except Exception as e:
        logger.error(f"Redis RATE LIMIT error [{key}]: {e}")
        return True  # fail-open


# --------------------------------------------------
# Locks (evitar doble reserva)
# --------------------------------------------------

def acquire_lock(key: str, ttl: int = 30) -> bool:
    """
    Intenta adquirir un lock distribuido
    """
    try:
        return redis.set(key, "1", nx=True, ex=ttl) is True
    except Exception as e:
        logger.error(f"Redis LOCK error [{key}]: {e}")
        return False


def release_lock(key: str) -> None:
    """
    Libera un lock
    """
    try:
        redis.delete(key)
    except Exception as e:
        logger.error(f"Redis UNLOCK error [{key}]: {e}")


# --------------------------------------------------
# Healthcheck
# --------------------------------------------------

def redis_healthcheck() -> bool:
    """
    Verifica si Redis está operativo
    """
    try:
        redis.set("healthcheck", "ok", ex=5)
        return redis.get("healthcheck") == "ok"
    except Exception:
        return False
