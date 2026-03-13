"""
app/infra/ws_redis_backend.py

Redis Pub/Sub backend para WebSockets distribuidos.

Problema que resuelve:
  ConnectionManager guarda conexiones en memoria → si hay 2 instancias FastAPI,
  usuario A en instancia-1 no puede enviar mensajes a usuario B en instancia-2.

Solución:
  broadcast_to_user() publica en Redis canal ws:broadcast:{user_id}.
  Cada instancia tiene un subscriber loop que recibe los mensajes
  y los entrega a los WebSockets locales.

Flujo:
  Instancia-1: broadcast_to_user(B, msg)
    → B no está en conexiones locales
    → publish Redis: ws:broadcast:B → msg
  Instancia-2: subscriber loop recibe pmessage
    → B sí está en conexiones locales de instancia-2
    → websocket.send_json(msg) ✅

Modo graceful degradation:
  Si el cliente Redis async no está disponible (REDIS_URL no configurado o error),
  el sistema continúa en modo single-instance sin error.
"""

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "ws:broadcast:"

_subscriber_task: Optional[asyncio.Task] = None
_enabled = False


async def start_ws_redis_subscriber() -> bool:
    """
    Inicia el subscriber de Redis Pub/Sub para entrega cross-instance.
    Llamar desde el lifespan de FastAPI (startup).
    Retorna True si el subscriber se inició correctamente, False si no.
    """
    global _subscriber_task, _enabled

    try:
        from app.infra.redis.client import redis_client

        if not redis_client._client:
            logger.warning(
                "⚠️ WS Redis backend: async client no conectado — "
                "WebSockets distribuidos deshabilitados (single-instance mode)"
            )
            return False

        _enabled = True
        _subscriber_task = asyncio.create_task(_subscriber_loop())
        logger.info(
            f"✅ WS Redis subscriber iniciado — "
            f"WebSockets distribuidos habilitados (canal: {CHANNEL_PREFIX}*)"
        )
        return True

    except Exception as e:
        logger.warning(f"⚠️ WS Redis backend no disponible: {type(e).__name__}: {e}")
        logger.warning("   → Continuando en single-instance mode")
        return False


async def _subscriber_loop():
    """
    Loop de background: suscribe a ws:broadcast:* y entrega mensajes localmente.

    Usa PSUBSCRIBE (pattern subscribe) para recibir mensajes de todos los usuarios
    en un solo canal de control, sin crear una suscripción por usuario.
    """
    from app.infra.redis.client import redis_client
    from app.api.websocket.connection_manager import connection_manager

    pubsub = None
    try:
        pubsub = redis_client._client.pubsub()
        await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
        logger.info(f"✅ WS Redis subscriber: escuchando {CHANNEL_PREFIX}*")

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue

            try:
                channel: str = message["channel"]
                # Extraer user_id del canal: "ws:broadcast:123" → 123
                user_id = int(channel[len(CHANNEL_PREFIX):])
                data = json.loads(message["data"])

                # Entregar solo a conexiones locales de esta instancia
                if user_id in connection_manager.active_connections:
                    dead_sockets = []
                    for ws in list(connection_manager.active_connections[user_id]):
                        try:
                            await ws.send_json(data)
                        except Exception:
                            dead_sockets.append(ws)
                    for ws in dead_sockets:
                        connection_manager.disconnect(ws, user_id)

            except (ValueError, KeyError, json.JSONDecodeError) as e:
                logger.debug(f"WS Redis subscriber: mensaje ignorado — {e}")
            except Exception as e:
                logger.error(f"WS Redis subscriber: error entregando mensaje — {e}")

    except asyncio.CancelledError:
        logger.info("WS Redis subscriber: cancelado (shutdown normal)")
    except Exception as e:
        logger.error(f"WS Redis subscriber: error fatal — {type(e).__name__}: {e}")
    finally:
        if pubsub:
            try:
                await pubsub.punsubscribe()
                await pubsub.aclose()
            except Exception:
                pass
        logger.info("WS Redis subscriber: finalizado")


async def publish_to_user_via_redis(user_id: int, message: dict) -> bool:
    """
    Publica un mensaje en Redis para que otras instancias lo entreguen al usuario.
    Solo llamar cuando el usuario NO está en las conexiones locales.
    """
    if not _enabled:
        return False

    try:
        from app.infra.redis.client import redis_client

        channel = f"{CHANNEL_PREFIX}{user_id}"
        payload = json.dumps(message, default=str)
        await redis_client.publish(channel, payload)
        logger.debug(f"📡 WS Redis: publicado para user:{user_id} en {channel}")
        return True

    except Exception as e:
        logger.error(f"WS Redis publish error para user:{user_id} — {e}")
        return False


async def stop_ws_redis_subscriber():
    """
    Detiene el subscriber de Redis Pub/Sub.
    Llamar desde el lifespan de FastAPI (shutdown).
    """
    global _subscriber_task, _enabled

    _enabled = False

    if _subscriber_task and not _subscriber_task.done():
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass

    logger.info("WS Redis subscriber detenido")


def is_distributed_ws_enabled() -> bool:
    """Retorna True si el backend distribuido está activo."""
    return _enabled
