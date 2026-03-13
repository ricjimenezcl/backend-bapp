"""
WebSocket Handler for FASE 2 - Chat & Notifications
Manages real-time connections and message broadcasting
"""

import json
import asyncio
from typing import Dict, List, Set
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for chat and notifications"""
    
    def __init__(self):
        # Store active connections per user: {user_id: [websocket, ...]}
        self.active_connections: Dict[int, List[WebSocket]] = {}
        # Store active chat room connections: {conversation_id: {user_id: [websocket, ...]}}
        self.chat_rooms: Dict[int, Dict[int, List[WebSocket]]] = {}
        # Connection metadata: {user_id: {'last_seen': datetime, 'presence_status': str}}
        self.connection_metadata: Dict[int, Dict] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        """Register a new WebSocket connection"""
        # await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        
        self.active_connections[user_id].append(websocket)
        
        # Initialize metadata
        if user_id not in self.connection_metadata:
            self.connection_metadata[user_id] = {
                'last_seen': datetime.utcnow(),
                'presence_status': 'online'
            }
        else:
            self.connection_metadata[user_id]['presence_status'] = 'online'
            self.connection_metadata[user_id]['last_seen'] = datetime.utcnow()
        
        logger.info(f"✓ User {user_id} connected. Total connections: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        """Unregister a WebSocket connection"""
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
                    if user_id in self.connection_metadata:
                        self.connection_metadata[user_id]['presence_status'] = 'offline'
                        self.connection_metadata[user_id]['last_seen'] = datetime.utcnow()
            except ValueError:
                pass
        
        logger.info(f"✓ User {user_id} disconnected")

    async def connect_to_chat_room(
        self,
        websocket: WebSocket,
        user_id: int,
        conversation_id: int
    ):
        """Add user to a specific chat room"""
        if conversation_id not in self.chat_rooms:
            self.chat_rooms[conversation_id] = {}
        
        if user_id not in self.chat_rooms[conversation_id]:
            self.chat_rooms[conversation_id][user_id] = []
        
        self.chat_rooms[conversation_id][user_id].append(websocket)
        logger.info(f"✓ User {user_id} joined chat room {conversation_id}")

    def disconnect_from_chat_room(
        self,
        websocket: WebSocket,
        user_id: int,
        conversation_id: int
    ):
        """Remove user from a specific chat room"""
        if conversation_id in self.chat_rooms:
            if user_id in self.chat_rooms[conversation_id]:
                try:
                    self.chat_rooms[conversation_id][user_id].remove(websocket)
                    if not self.chat_rooms[conversation_id][user_id]:
                        del self.chat_rooms[conversation_id][user_id]
                    if not self.chat_rooms[conversation_id]:
                        del self.chat_rooms[conversation_id]
                except ValueError:
                    pass
        
        logger.info(f"✓ User {user_id} left chat room {conversation_id}")

    # ==================== Broadcasting ====================

    async def broadcast_to_user(
        self,
        user_id: int,
        message: dict
    ):
        """
        Send message to user.
        - Si el usuario está conectado a ESTA instancia: entrega directa por WebSocket.
        - Si no está aquí: publica en Redis para que otra instancia lo entregue.
        """
        if user_id in self.active_connections:
            # Entrega local — no publicar en Redis para evitar doble entrega
            disconnected = []
            for websocket in self.active_connections[user_id]:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending to user {user_id}: {str(e)}")
                    disconnected.append(websocket)

            for ws in disconnected:
                self.disconnect(ws, user_id)

            return  # Entregado localmente — fin

        # Usuario no está en esta instancia → publicar vía Redis (graceful no-op si no está habilitado)
        try:
            from app.infra.ws_redis_backend import publish_to_user_via_redis
            await publish_to_user_via_redis(user_id, message)
        except Exception as e:
            logger.debug(f"Cross-instance publish skipped for user {user_id}: {e}")

    async def broadcast_to_chat_room(
        self,
        conversation_id: int,
        message: dict,
        exclude_user_id: int = None
    ):
        """Send message to all users in a chat room"""
        if conversation_id in self.chat_rooms:
            disconnected = []
            
            for user_id, websockets in self.chat_rooms[conversation_id].items():
                if exclude_user_id and user_id == exclude_user_id:
                    continue
                
                for websocket in websockets:
                    try:
                        await websocket.send_json(message)
                    except Exception as e:
                        logger.error(f"Error broadcasting to user {user_id}: {str(e)}")
                        disconnected.append((websocket, user_id, conversation_id))
            
            # Clean up disconnected websockets
            for ws, uid, cid in disconnected:
                self.disconnect_from_chat_room(ws, uid, cid)

    async def send_to_both_participants(
        self,
        conversation_id: int,
        sender_id: int,
        recipient_id: int,
        message: dict
    ):
        """Send message to both participants in a conversation"""
        if conversation_id in self.chat_rooms:
            # Send to sender
            if sender_id in self.chat_rooms[conversation_id]:
                for websocket in self.chat_rooms[conversation_id][sender_id]:
                    try:
                        await websocket.send_json(message)
                    except Exception as e:
                        logger.error(f"Error sending to sender {sender_id}: {str(e)}")
            
            # Send to recipient
            if recipient_id in self.chat_rooms[conversation_id]:
                for websocket in self.chat_rooms[conversation_id][recipient_id]:
                    try:
                        await websocket.send_json(message)
                    except Exception as e:
                        logger.error(f"Error sending to recipient {recipient_id}: {str(e)}")

    # ==================== Presence Management ====================

    def get_user_presence(self, user_id: int) -> dict:
        """Get presence status of a user"""
        if user_id in self.connection_metadata:
            return self.connection_metadata[user_id]
        return {'presence_status': 'offline', 'last_seen': None}

    def is_user_online(self, user_id: int) -> bool:
        """Check if user is online"""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0

    def get_active_users(self) -> List[int]:
        """Get list of online users"""
        return list(self.active_connections.keys())

    def get_chat_room_participants(self, conversation_id: int) -> List[int]:
        """Get list of users in a chat room"""
        if conversation_id in self.chat_rooms:
            return list(self.chat_rooms[conversation_id].keys())
        return []

    # ==================== Message Formatting ====================

    @staticmethod
    def format_message(
        message_type: str,
        data: dict,
        sender_id: int = None,
        timestamp: datetime = None
    ) -> dict:
        """Format a message for WebSocket transmission"""
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        return {
            'type': message_type,
            'sender_id': sender_id,
            'timestamp': timestamp.isoformat(),
            'data': data
        }

    @staticmethod
    def format_chat_message(
        message_id: int,
        sender_id: int,
        sender_name: str,
        content: str,
        timestamp: datetime = None
    ) -> dict:
        """Format a chat message"""
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        return {
            'type': 'message',
            'message_id': message_id,
            'sender_id': sender_id,
            'sender_name': sender_name,
            'content': content,
            'timestamp': timestamp.isoformat(),
            'is_read': False
        }

    @staticmethod
    def format_notification(
        notification_id: int,
        notification_type: str,
        title: str,
        content: str,
        related_entity_id: int = None
    ) -> dict:
        """Format a notification"""
        return {
            'type': 'notification',
            'notification_id': notification_id,
            'notification_type': notification_type,
            'title': title,
            'content': content,
            'related_entity_id': related_entity_id,
            'timestamp': datetime.utcnow().isoformat(),
            'is_read': False
        }

    @staticmethod
    def format_presence_update(
        user_id: int,
        presence_status: str
    ) -> dict:
        """Format a presence update"""
        return {
            'type': 'presence_update',
            'user_id': user_id,
            'presence_status': presence_status,
            'timestamp': datetime.utcnow().isoformat()
        }

    @staticmethod
    def format_typing_indicator(
        user_id: int,
        user_name: str,
        is_typing: bool
    ) -> dict:
        """Format a typing indicator"""
        return {
            'type': 'typing',
            'user_id': user_id,
            'user_name': user_name,
            'is_typing': is_typing,
            'timestamp': datetime.utcnow().isoformat()
        }


# Global connection manager instance
connection_manager = ConnectionManager()
