"""
Infra Redis cache helpers
Moved from app/infra/redis.py to avoid package conflict
"""

from typing import Optional, List
from app.core.redis import cache_get, cache_set, cache_delete

# ===========================
# Cache: Notificaciones de usuario
# ===========================

NOTIFICATIONS_TTL = 60  # segundos

def _notifications_key(user_id: int) -> str:
    return f"cache:notifications:{user_id}"

def get_notifications_cache(user_id: int):
    return cache_get(_notifications_key(user_id))

def set_notifications_cache(user_id: int, data):
    cache_set(_notifications_key(user_id), data, ttl=NOTIFICATIONS_TTL)

# ===========================
# Cache: Mensajes de chat
# ===========================

CHAT_MESSAGES_TTL = 300  # segundos — mensajes son inmutables

def _chat_messages_key(conversation_id: int, skip: int, limit: int) -> str:
    return f"cache:chat:messages:{conversation_id}:{skip}:{limit}"

def get_chat_messages_cache(conversation_id: int, skip: int, limit: int):
    return cache_get(_chat_messages_key(conversation_id, skip, limit))

def set_chat_messages_cache(conversation_id: int, skip: int, limit: int, data):
    cache_set(_chat_messages_key(conversation_id, skip, limit), data, ttl=CHAT_MESSAGES_TTL)

# ===========================
# Cache: Conversaciones de chat
# ===========================

CHAT_CONVERSATIONS_TTL = 180  # segundos

def _chat_conversations_key(user_id: int, provider_id: int, skip: int, limit: int) -> str:
    return f"cache:chat:conversations:{user_id}:{provider_id}:{skip}:{limit}"

def get_chat_conversations_cache(user_id: int, provider_id: int, skip: int, limit: int):
    return cache_get(_chat_conversations_key(user_id, provider_id, skip, limit))

def set_chat_conversations_cache(user_id: int, provider_id: int, skip: int, limit: int, data):
    cache_set(_chat_conversations_key(user_id, provider_id, skip, limit), data, ttl=CHAT_CONVERSATIONS_TTL)

# ===========================
# Configuración
# ===========================

NEARBY_PROVIDERS_TTL = 120  # segundos
PROVIDER_PROFILE_TTL = 120

# ===========================
# Utils
# ===========================

def _geo_grid(value: float, precision: int = 2) -> float:
    """
    Redondea coordenadas para cache geográfico
    precision=2 ≈ 1km
    """
    return round(value, precision)

# ===========================
# Cache: Proveedores cercanos
# ===========================

def _nearby_key(category_id: int, lat: float, lng: float) -> str:
    lat_g = _geo_grid(lat)
    lng_g = _geo_grid(lng)
    return f"cache:providers:nearby:{category_id}:{lat_g}:{lng_g}"


def get_nearby_providers_cache(
    category_id: int,
    lat: float,
    lng: float
) -> Optional[List[dict]]:
    return cache_get(_nearby_key(category_id, lat, lng))


def set_nearby_providers_cache(
    category_id: int,
    lat: float,
    lng: float,
    providers: List[dict]
) -> None:
    cache_set(
        _nearby_key(category_id, lat, lng),
        providers,
        ttl=NEARBY_PROVIDERS_TTL
    )

# ===========================
# Cache: Perfil proveedor
# ===========================

def _provider_profile_key(provider_id: int) -> str:
    return f"cache:provider:profile:{provider_id}"


def get_provider_profile_cache(provider_id: int) -> Optional[dict]:
    return cache_get(_provider_profile_key(provider_id))


def set_provider_profile_cache(provider_id: int, profile: dict) -> None:
    cache_set(
        _provider_profile_key(provider_id),
        profile,
        ttl=PROVIDER_PROFILE_TTL
    )


def invalidate_provider_cache(provider_id: int) -> None:
    cache_delete(_provider_profile_key(provider_id))


# ===========================
# Cache: Perfil proveedor detallado (con servicios y reviews)
# ===========================

PROVIDER_DETAILED_TTL = 60  # segundos

def _provider_detailed_key(provider_id: int) -> str:
    return f"cache:provider:detailed:{provider_id}"


def get_provider_detailed_cache(provider_id: int) -> Optional[dict]:
    return cache_get(_provider_detailed_key(provider_id))


def set_provider_detailed_cache(provider_id: int, data: dict) -> None:
    cache_set(_provider_detailed_key(provider_id), data, ttl=PROVIDER_DETAILED_TTL)


def invalidate_provider_detailed_cache(provider_id: int) -> None:
    cache_delete(_provider_detailed_key(provider_id))


# ===========================
# Cache: Reservas — invalidación
# ===========================

def invalidate_client_bookings_cache(client_id: int) -> None:
    cache_delete(f"bookings:client:{client_id}")


def invalidate_provider_bookings_cache(provider_id: int) -> None:
    cache_delete(f"bookings:provider:{provider_id}")


# ===========================
# Cache: Slots disponibles
# TTL corto (60s) — datos cambian con cada reserva nueva/cancelada
# ===========================

SLOTS_TTL = 60  # segundos


def _slots_key(provider_id: int, service_id: int, date: str) -> str:
    return f"cache:slots:{provider_id}:{service_id}:{date}"


def get_slots_cache(provider_id: int, service_id: int, date: str) -> Optional[dict]:
    return cache_get(_slots_key(provider_id, service_id, date))


def set_slots_cache(provider_id: int, service_id: int, date: str, data: dict) -> None:
    cache_set(_slots_key(provider_id, service_id, date), data, ttl=SLOTS_TTL)


# ===========================
# Contadores: Vistas de perfil y servicios
# Claves: counter:profile_views:{provider_id}
#         counter:service_views:{provider_id}
# TTL: 30 días (se resetean mensualmente)
# ===========================

VIEWS_TTL = 30 * 24 * 3600  # 30 días


def _profile_views_key(provider_id: int) -> str:
    return f"counter:profile_views:{provider_id}"


def _service_views_key(provider_id: int) -> str:
    return f"counter:service_views:{provider_id}"


def incr_profile_views(provider_id: int) -> None:
    """Incrementa el contador de vistas al perfil del proveedor (fail-open)."""
    try:
        from app.core.redis import redis as _r
        key = _profile_views_key(provider_id)
        count = _r.incr(key)
        if count == 1:
            _r.expire(key, VIEWS_TTL)
    except Exception:
        pass


def incr_service_views(provider_id: int) -> None:
    """Incrementa el contador de vistas a los servicios del proveedor (fail-open)."""
    try:
        from app.core.redis import redis as _r
        key = _service_views_key(provider_id)
        count = _r.incr(key)
        if count == 1:
            _r.expire(key, VIEWS_TTL)
    except Exception:
        pass


def get_profile_views(provider_id: int) -> int:
    """Retorna el contador de vistas al perfil (0 si no existe o error)."""
    try:
        from app.core.redis import redis as _r
        val = _r.get(_profile_views_key(provider_id))
        return int(val) if val else 0
    except Exception:
        return 0


def get_service_views(provider_id: int) -> int:
    """Retorna el contador de vistas a servicios (0 si no existe o error)."""
    try:
        from app.core.redis import redis as _r
        val = _r.get(_service_views_key(provider_id))
        return int(val) if val else 0
    except Exception:
        return 0


def invalidate_slots_cache(provider_id: int) -> None:
    """Invalida TODAS las fechas de slots para un proveedor.
    Estrategia simple: cache_delete con wildcard no disponible en este cliente
    → usamos una convención de key con patrón conocido.
    El cliente sync llama KEYS pattern; preferimos borrar por key exacta
    cuando sea posible, o dejar expirar (TTL=60s) si no tenemos la fecha.
    """
    # Intentar invalidar con el cliente sync redis disponible
    try:
        from app.core.redis import redis as _r
        pattern = f"cache:slots:{provider_id}:*"
        keys = _r.keys(pattern)
        if keys:
            _r.delete(*keys)
    except Exception:
        pass  # fail-open: slots expirarán en 60s por TTL
