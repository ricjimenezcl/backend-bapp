"""
WebSocket Endpoints for FASE 2 - Real-time Chat
Handles WebSocket connections for chat and notifications
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt
import json
import logging
import asyncio
import re

from app.core.database import get_db_async
from app.core.config import settings
from app.services.chat_service import ChatService
from app.services.notification_service import NotificationService
from app.api.websocket.connection_manager import connection_manager
from app.infra.pubsub import flush_offline_queue_async
from app.core.redis import rate_limit
from sqlalchemy.future import select
from app.models.user import User

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)

# Rooms activos en la conexión unificada: user_id → set of conversation_ids
# Esto permite que un cliente haga join/leave de rooms sin reconectarse.
_unified_rooms: dict[int, set[int]] = {}


# Helper function to verify JWT token
def verify_ws_token(token: str) -> int:
    """
    Verify WebSocket JWT token and return user_id
    Only validates JWT signature, user existence is checked separately if needed
    """
    try:
        if not token or token == "":
            logger.error("❌ WebSocket: Empty token")
            return None
        
        logger.info(f"🔑 WebSocket: Attempting to decode token...")
        
        # Decode JWT token
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        
        logger.info(f"✅ JWT decoded successfully. Payload: {payload}")
        
        user_id: int = payload.get("user_id")
        if user_id is None:
            logger.error("❌ WebSocket: No user_id in token payload")
            return None
        
        logger.info(f"✓ WebSocket token validated for user_id: {user_id}")
        return user_id
        
    except JWTError as e:
        # Check if it's an expiration error
        if "Signature has expired" in str(e):
             logger.warning(f"⚠️ WebSocket: Token expired for user. Error: {str(e)}")
        else:
             logger.error(f"❌ WebSocket: JWT decode error: {type(e).__name__}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"❌ WebSocket: Unexpected error: {type(e).__name__}: {str(e)}")
        # import traceback
        # logger.error(f"Traceback: {traceback.format_exc()}")
        return None


# ==================== Unified WebSocket ====================

@router.websocket("/unified")
async def websocket_unified_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db_async),
):
    """
    Endpoint WebSocket unificado: notificaciones + chat en una sola conexión.

    Protocolo de mensajes cliente→servidor:
      { "channel": "chat", "conversation_id": 123, "type": "join" }
      { "channel": "chat", "conversation_id": 123, "type": "leave" }
      { "channel": "chat", "conversation_id": 123, "type": "message",  "data": {"content": "..."} }
      { "channel": "chat", "conversation_id": 123, "type": "typing",   "data": {"is_typing": true} }
      { "channel": "chat", "conversation_id": 123, "type": "read",     "data": {"message_id": 456} }
      { "channel": "notification", "type": "ping" }
      { "type": "ping" }

    Protocolo servidor→cliente (mismo channel prefix):
      { "channel": "notification", "type": "notification", ... }
      { "channel": "chat",         "type": "message",      "conversation_id": 123, ... }
      { "type": "pong" }
      { "type": "ping" }
    """
    # 1. Verificar token
    user_id = verify_ws_token(token)
    if user_id is None:
        await websocket.accept()
        await websocket.close(code=4401, reason="Token expired or invalid")
        return

    # 2. Aceptar + registrar en ConnectionManager
    await websocket.accept()
    await connection_manager.connect(websocket, user_id)
    _unified_rooms[user_id] = set()
    logger.info(f"✅ WS /unified conectado para user_id={user_id}")

    # 3. Bienvenida
    try:
        await websocket.send_json({
            "channel": "notification",
            "type": "connected",
            "message": "Unified WebSocket activo",
            "user_id": user_id,
        })
    except Exception:
        pass

    # 4. Flush offline queue (igual que /notifications)
    try:
        pending_events = await flush_offline_queue_async(user_id)
        for event in pending_events:
            try:
                await websocket.send_json({**event, "channel": "notification"})
            except Exception:
                break
    except Exception as e:
        logger.error(f"WS /unified flush error: {e}")

    chat_service = ChatService(db)
    notification_service = NotificationService(db)

    # 5. Loop principal
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            channel = msg.get("channel", "notification")
            msg_type = msg.get("type", "ping")

            # ── ping/pong genérico ─────────────────────────────────────
            if msg_type in ("ping", "pong"):
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    break
                continue

            # ── canal chat ─────────────────────────────────────────────
            if channel == "chat":
                conversation_id = msg.get("conversation_id")
                if not conversation_id:
                    continue

                if msg_type == "join":
                    try:
                        conv = await chat_service.get_conversation_by_id(conversation_id)
                        if conv and user_id in [conv.client_id, conv.provider_id]:
                            await connection_manager.connect_to_chat_room(websocket, user_id, conversation_id)
                            _unified_rooms[user_id].add(conversation_id)
                            await websocket.send_json({
                                "channel": "chat",
                                "type": "joined",
                                "conversation_id": conversation_id,
                            })
                    except Exception as e:
                        logger.error(f"WS /unified join error: {e}")

                elif msg_type == "leave":
                    connection_manager.disconnect_from_chat_room(websocket, user_id, conversation_id)
                    _unified_rooms[user_id].discard(conversation_id)

                elif msg_type == "message":
                    try:
                        content = (msg.get("data") or {}).get("content", "").strip()
                        content = re.sub(r"<[^>]+>", "", content).strip()
                        if not content or len(content) > 2000:
                            continue

                        allowed = await asyncio.get_event_loop().run_in_executor(
                            None, rate_limit, f"rate:chat:msg:{user_id}", 30, 60
                        )
                        if not allowed:
                            await websocket.send_json({
                                "channel": "chat",
                                "type": "error",
                                "message": "Rate limit exceeded",
                            })
                            continue

                        saved_msg = await chat_service.send_message(
                            conversation_id=conversation_id,
                            sender_id=user_id,
                            content=content,
                        )
                        response = {
                            **connection_manager.format_chat_message(
                                message_id=saved_msg.id,
                                sender_id=user_id,
                                sender_name=f"{saved_msg.sender.first_name} {saved_msg.sender.last_name}",
                                content=content,
                                timestamp=saved_msg.created_at,
                            ),
                            "channel": "chat",
                            "conversation_id": conversation_id,
                        }
                        await connection_manager.broadcast_to_chat_room(conversation_id, response)

                        # Notificar al otro participante
                        conv = await chat_service.get_conversation_by_id(conversation_id)
                        if conv:
                            other_id = conv.provider_id if user_id == conv.client_id else conv.client_id
                            await notification_service.create_message_notification(
                                user_id=other_id,
                                sender_name=f"{saved_msg.sender.first_name} {saved_msg.sender.last_name}",
                                conversation_id=conversation_id,
                            )
                            await connection_manager.broadcast_to_user(
                                other_id,
                                {
                                    **connection_manager.format_notification(
                                        notification_id=saved_msg.id,
                                        notification_type="message",
                                        title="Nuevo mensaje",
                                        content=f"Tienes un nuevo mensaje de {saved_msg.sender.first_name}",
                                        related_entity_id=conversation_id,
                                    ),
                                    "channel": "notification",
                                },
                            )
                    except Exception as e:
                        logger.error(f"WS /unified message error: {e}")

                elif msg_type == "typing":
                    try:
                        payload = msg.get("data") or {}
                        response = {
                            **connection_manager.format_typing_indicator(
                                user_id=user_id,
                                user_name=payload.get("user_name", "Usuario"),
                                is_typing=payload.get("is_typing", False),
                            ),
                            "channel": "chat",
                            "conversation_id": conversation_id,
                        }
                        await connection_manager.broadcast_to_chat_room(
                            conversation_id, response, exclude_user_id=user_id
                        )
                    except Exception as e:
                        logger.error(f"WS /unified typing error: {e}")

                elif msg_type == "read":
                    try:
                        message_id = (msg.get("data") or {}).get("message_id")
                        if message_id:
                            await chat_service.mark_message_as_read(message_id)
                            await connection_manager.broadcast_to_chat_room(
                                conversation_id,
                                {
                                    "channel": "chat",
                                    "conversation_id": conversation_id,
                                    "type": "read_confirmation",
                                    "message_id": message_id,
                                },
                            )
                    except Exception as e:
                        logger.error(f"WS /unified read error: {e}")

    except WebSocketDisconnect:
        logger.info(f"WS /unified desconectado — user_id={user_id}")
    except asyncio.CancelledError:
        logger.info(f"WS /unified cancelado — user_id={user_id}")
    except Exception as e:
        logger.error(f"WS /unified error — user_id={user_id}: {e}")
    finally:
        # Limpiar rooms activos
        for conv_id in list(_unified_rooms.get(user_id, [])):
            connection_manager.disconnect_from_chat_room(websocket, user_id, conv_id)
        _unified_rooms.pop(user_id, None)
        connection_manager.disconnect(websocket, user_id)
        logger.info(f"🔌 WS /unified finalizado para user_id={user_id}")


# ==================== Chat WebSocket ====================

@router.websocket("/chat/{conversation_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    conversation_id: int,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db_async)
):
    """
    WebSocket endpoint for real-time chat
    
    Expected message format:
    {
        "type": "message" | "typing" | "read",
        "data": {...}
    }
    
    Message types:
    - "message": Send a chat message
    - "typing": Indicate user is typing
    - "read": Mark message(s) as read
    - "presence": Update presence status
    """
    
    # Verify token and get user
    user_id = verify_ws_token(token)

    if user_id is None:
        logger.error(f"WebSocket chat: Invalid token for conversation {conversation_id}")
        await websocket.accept()
        await websocket.close(code=4401, reason="Token expired or invalid")
        return
    
    # Accept the connection FIRST
    await websocket.accept()
    logger.info(f"✓ User {user_id} accepted to chat room {conversation_id}")
    
    # Verify conversation exists and user is participant
    try:
        chat_service = ChatService(db)
        conversation = await chat_service.get_conversation_by_id(conversation_id)
        
        if not conversation:
            logger.error(f"WebSocket chat: Conversation {conversation_id} not found for user {user_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Conversation not found")
            return
        
        if user_id not in [conversation.client_id, conversation.provider_id]:
            logger.error(f"WebSocket chat: User {user_id} not participant in conversation {conversation_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User not participant")
            return
        
    except Exception as e:
        logger.error(f"Error verifying conversation: {str(e)}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Verification error")
        return
    
    # Connect to websocket
    await connection_manager.connect(websocket, user_id)
    await connection_manager.connect_to_chat_room(websocket, user_id, conversation_id)
    
    # Notify other participants that user joined
    other_user_id = conversation.provider_id if user_id == conversation.client_id else conversation.client_id
    presence_message = connection_manager.format_presence_update(user_id, "online")
    await connection_manager.broadcast_to_chat_room(
        conversation_id,
        presence_message,
        exclude_user_id=user_id
    )
    
    logger.info(f"✓ User {user_id} connected to chat room {conversation_id}")
    
    try:
        while True:
            # Receive message with timeout — si no hay actividad en 30s, enviar server ping
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    logger.info(f"WS /chat: ping failed, cliente desconectado — user:{user_id} room:{conversation_id}")
                    break
                continue

            message_data = json.loads(data)

            message_type = message_data.get('type', 'message')
            payload = message_data.get('data', {})
            
            if message_type == 'message':
                # Handle chat message
                try:
                    content = payload.get('content', '').strip()

                    if not content:
                        continue

                    # Rate limit: 30 mensajes/minuto por usuario
                    allowed = await asyncio.get_event_loop().run_in_executor(
                        None, rate_limit, f"rate:chat:msg:{user_id}", 30, 60
                    )
                    if not allowed:
                        await websocket.send_json({
                            'type': 'error',
                            'message': 'Rate limit exceeded. Max 30 messages per minute.'
                        })
                        continue

                    # Validar tamaño del mensaje
                    if len(content) > 2000:
                        await websocket.send_json({
                            'type': 'error',
                            'message': 'Message too long. Maximum 2000 characters.'
                        })
                        continue

                    # Sanitizar HTML/script para prevenir XSS
                    content = re.sub(r'<[^>]+>', '', content).strip()
                    if not content:
                        continue

                    # Save message to database
                    msg = await chat_service.send_message(
                        conversation_id=conversation_id,
                        sender_id=user_id,
                        content=content
                    )
                    
                    # Create response message
                    response = connection_manager.format_chat_message(
                        message_id=msg.id,
                        sender_id=user_id,
                        sender_name=f"{msg.sender.first_name} {msg.sender.last_name}",
                        content=content,
                        timestamp=msg.created_at
                    )
                    
                    # Broadcast to chat room
                    await connection_manager.broadcast_to_chat_room(
                        conversation_id,
                        response
                    )
                    
                    # Create notification for recipient
                    notification_service = NotificationService(db)
                    await notification_service.create_message_notification(
                        user_id=other_user_id,
                        sender_name=f"{msg.sender.first_name} {msg.sender.last_name}",
                        conversation_id=conversation_id
                    )
                    
                    # Send notification to recipient
                    await connection_manager.broadcast_to_user(
                        other_user_id,
                        connection_manager.format_notification(
                            notification_id=msg.id,
                            notification_type="message",
                            title=f"Nuevo mensaje",
                            content=f"Tienes un nuevo mensaje de {msg.sender.first_name}",
                            related_entity_id=conversation_id
                        )
                    )
                    
                    logger.info(f"✓ Message sent in room {conversation_id}: {msg.id}")
                    
                except Exception as e:
                    logger.error(f"Error sending message: {str(e)}")
                    error_response = {
                        'type': 'error',
                        'message': f"Error sending message: {str(e)}"
                    }
                    await websocket.send_json(error_response)
            
            elif message_type == 'typing':
                # Handle typing indicator
                try:
                    is_typing = payload.get('is_typing', False)
                    
                    response = connection_manager.format_typing_indicator(
                        user_id=user_id,
                        user_name=payload.get('user_name', 'Usuario'),
                        is_typing=is_typing
                    )
                    
                    # Broadcast to other participants
                    await connection_manager.broadcast_to_chat_room(
                        conversation_id,
                        response,
                        exclude_user_id=user_id
                    )
                    
                except Exception as e:
                    logger.error(f"Error handling typing indicator: {str(e)}")
            
            elif message_type == 'read':
                # Handle mark as read
                try:
                    message_id = payload.get('message_id')
                    
                    if message_id:
                        await chat_service.mark_message_as_read(message_id)
                        
                        response = {
                            'type': 'read_confirmation',
                            'message_id': message_id
                        }
                        
                        await connection_manager.broadcast_to_chat_room(
                            conversation_id,
                            response
                        )
                    
                except Exception as e:
                    logger.error(f"Error marking message as read: {str(e)}")
            
            elif message_type == 'presence':
                # Handle presence update
                try:
                    presence_status = payload.get('status', 'online')
                    
                    response = connection_manager.format_presence_update(
                        user_id=user_id,
                        presence_status=presence_status
                    )
                    
                    await connection_manager.broadcast_to_chat_room(
                        conversation_id,
                        response,
                        exclude_user_id=user_id
                    )
                    
                except Exception as e:
                    logger.error(f"Error handling presence update: {str(e)}")
    
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket, user_id)
        connection_manager.disconnect_from_chat_room(websocket, user_id, conversation_id)
        
        # Notify other participants that user left
        presence_message = connection_manager.format_presence_update(user_id, "offline")
        await connection_manager.broadcast_to_chat_room(
            conversation_id,
            presence_message
        )
        
        logger.info(f"✓ User {user_id} disconnected from chat room {conversation_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error in chat room {conversation_id}: {str(e)}")
        connection_manager.disconnect(websocket, user_id)
        connection_manager.disconnect_from_chat_room(websocket, user_id, conversation_id)


# ==================== Notifications WebSocket ====================

@router.websocket("/notifications")
async def websocket_notifications_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    WebSocket endpoint para notificaciones en tiempo real.

    Arquitectura PUSH (sin polling Redis):
    - Usuarios online reciben eventos directamente via connection_manager.broadcast_to_user()
    - Al conectar, se entregan mensajes pendientes offline (flush único, no loop)
    - El loop principal solo mantiene la conexión viva (ping/pong)
    - Cero comandos Redis periódicos — 96% reducción de consumo Redis
    """
    logger.info(f"🔵 WS /notifications REACHED token={token[:20]}...")

    # 1. Verificar token
    user_id = verify_ws_token(token)
    if user_id is None:
        logger.error("WS /notifications: token inválido")
        # Aceptar el handshake HTTP primero para poder enviar un código WS aplicativo.
        # Sin accept(), el browser recibe HTTP 403 y event.code=1006 (no distinguible).
        # Con accept() + close(4401), el browser recibe event.code=4401 → detiene el loop.
        await websocket.accept()
        await websocket.close(code=4401, reason="Token expired or invalid")
        return

    # 2. Aceptar conexión y registrar en ConnectionManager
    await websocket.accept()
    await connection_manager.connect(websocket, user_id)
    logger.info(f"✅ WS /notifications conectado para user_id={user_id}")

    # 3. Mensaje de bienvenida
    try:
        await websocket.send_json({"type": "connected", "message": "Notificaciones activas", "user_id": user_id})
    except Exception:
        pass

    # 4. Flush de mensajes offline pendientes (UNA SOLA VEZ — no es un loop)
    try:
        pending_events = await flush_offline_queue_async(user_id)
        if pending_events:
            logger.info(f"📬 WS /notifications: entregando {len(pending_events)} eventos offline a user:{user_id}")
            for event in pending_events:
                try:
                    await websocket.send_json(event)
                except Exception as send_err:
                    logger.error(f"WS /notifications offline flush error: {send_err}")
                    break
    except Exception as e:
        logger.error(f"WS /notifications flush error: {type(e).__name__}: {e}")

    # 5. Loop principal: mantener conexión viva (keepalive ping/pong)
    # Los eventos push llegan automáticamente via connection_manager.broadcast_to_user()
    # cuando ocurren booking/chat/notification events — sin necesidad de polling Redis.
    try:
        while True:
            try:
                # Timeout de 30s — si el cliente no envía nada, mandamos ping servidor
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except (json.JSONDecodeError, AttributeError):
                    pass
            except asyncio.TimeoutError:
                # Sin actividad del cliente — enviar server-side keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    logger.info(f"WS /notifications: ping failed, cliente desconectado — user_id={user_id}")
                    break
            except WebSocketDisconnect:
                logger.info(f"WS /notifications desconectado — user_id={user_id}")
                break
            except asyncio.CancelledError:
                logger.info(f"WS /notifications cancelado — user_id={user_id}")
                break
            except Exception as e:
                logger.error(f"WS /notifications receive error: {type(e).__name__}: {e}")
                break
    finally:
        connection_manager.disconnect(websocket, user_id)
        logger.info(f"🔌 WS /notifications finalizado para user_id={user_id}")
