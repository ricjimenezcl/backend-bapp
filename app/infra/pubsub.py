"""
app/infra/pubsub.py
Pub/Sub via Redis Lists (Upstash REST compatible)
Usa LPUSH para publicar — solo para usuarios OFFLINE.
Usuarios online reciben eventos directamente via WebSocket (connection_manager).
No requiere TCP ni subscripción bloqueante. Cero polling.
"""
import json
import logging
import asyncio
from typing import Any, Optional

from app.core.redis import redis, _serialize, _deserialize

logger = logging.getLogger(__name__)

# --------------------------------------------------
# Prefijos de canales
# --------------------------------------------------
CHANNEL_NOTIFICATION = "pubsub:notification:{user_id}"
CHANNEL_BOOKING       = "pubsub:booking:{booking_id}"
CHANNEL_CHAT          = "pubsub:chat:{conversation_id}"

# TTL para mensajes de usuarios offline (24 horas)
MESSAGE_TTL = 86400  # 24 horas — permite entrega tras períodos de desconexión


# --------------------------------------------------
# Publicar evento a una cola de usuario
# --------------------------------------------------

def publish_to_user(user_id: int, event_type: str, payload: dict) -> bool:
    """
    Publica un evento en la cola offline del usuario.

    OPTIMIZACIÓN: Si el usuario está online (registrado en ConnectionManager),
    el evento ya fue entregado via broadcast_to_user() — no se necesita LPUSH.
    Solo hace LPUSH si el usuario está offline, para entrega al reconectar.
    """
    # Importación lazy para evitar circular imports
    from app.api.websocket.connection_manager import connection_manager

    if connection_manager.is_user_online(user_id):
        # Usuario online: el WebSocket ya entrega el evento via broadcast_to_user().
        # Saltar LPUSH elimina el comando Redis redundante.
        logger.debug(f"📤 [PUBSUB] User:{user_id} online — skipping Redis queue for {event_type}")
        return True

    # Usuario offline: encolar para entrega al reconectar
    channel = CHANNEL_NOTIFICATION.format(user_id=user_id)
    message = _serialize({
        "type": event_type,
        "data": payload
    })
    try:
        redis.lpush(channel, message)
        redis.expire(channel, MESSAGE_TTL)
        logger.info(f"📤 [PUBSUB] Offline queue → user:{user_id} event:{event_type}")
        return True
    except Exception as e:
        logger.error(f"[PUBSUB] publish_to_user error: {e}")
        return False


def publish_booking_event(client_id: int, provider_id: int, event_type: str, payload: dict) -> bool:
    """
    Publica un evento de booking a ambos participantes.
    Solo encola en Redis si el usuario está offline.
    """
    ok_client   = publish_to_user(client_id, event_type, payload)
    ok_provider = publish_to_user(provider_id, event_type, payload)
    return ok_client or ok_provider


def publish_chat_event(user_id: int, event_type: str, payload: dict) -> bool:
    """
    Publica un evento de chat al destinatario.
    Solo encola en Redis si el usuario está offline.
    """
    return publish_to_user(user_id, event_type, payload)


# --------------------------------------------------
# Flush de mensajes offline al reconectar (reemplaza polling)
# --------------------------------------------------

def flush_offline_queue(user_id: int) -> list:
    """
    Recupera y elimina TODOS los mensajes pendientes del usuario en un solo ciclo.
    Llamar UNA SOLA VEZ al conectar el WebSocket — no hay polling.

    Usa LRANGE + DEL en lugar de RPOP en loop para eficiencia.
    Retorna lista de eventos en orden cronológico (más antiguo primero).
    """
    channel = CHANNEL_NOTIFICATION.format(user_id=user_id)
    messages = []
    try:
        # LRANGE obtiene todos los mensajes (HEAD=nuevo, TAIL=antiguo por LPUSH)
        raw_messages = redis.lrange(channel, 0, -1)
        if raw_messages:
            redis.delete(channel)  # Eliminar toda la cola de una vez
            # reversed() para orden cronológico: más antiguo (tail) primero
            for raw in reversed(raw_messages):
                data = _deserialize(raw)
                if data:
                    messages.append(data)
            logger.info(f"📬 [PUBSUB] Flushed {len(messages)} offline messages for user:{user_id}")
    except Exception as e:
        logger.error(f"[PUBSUB] flush_offline_queue error: {e}")
    return messages


def drain_user_queue(user_id: int, max_messages: int = 20) -> list:
    """
    Consume hasta max_messages mensajes pendientes via RPOP.
    Mantenido por compatibilidad. Preferir flush_offline_queue() para el WS.
    """
    channel = CHANNEL_NOTIFICATION.format(user_id=user_id)
    messages = []
    try:
        for _ in range(max_messages):
            raw = redis.rpop(channel)
            if raw is None:
                break
            data = _deserialize(raw)
            if data:
                messages.append(data)
    except Exception as e:
        logger.error(f"[PUBSUB] drain_user_queue error: {e}")
    return messages


# --------------------------------------------------
# Async wrappers (run_in_executor — no bloquean el event loop)
# --------------------------------------------------

async def flush_offline_queue_async(user_id: int) -> list:
    """
    Async wrapper para flush_offline_queue.
    Usa run_in_executor para que las llamadas HTTP síncronas a Upstash REST
    no bloqueen el event loop de asyncio.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, flush_offline_queue, user_id)


async def publish_to_user_async(user_id: int, event_type: str, payload: dict) -> bool:
    """
    Async wrapper para publish_to_user.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, publish_to_user, user_id, event_type, payload)


async def publish_booking_event_async(client_id: int, provider_id: int, event_type: str, payload: dict) -> bool:
    """
    Async wrapper para publish_booking_event.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, publish_booking_event, client_id, provider_id, event_type, payload)
