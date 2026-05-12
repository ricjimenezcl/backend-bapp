# app/modules/chat/endpoints.py
"""
Chat Endpoints - REST API for chat operations
"""

import logging
import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_async
from app.dependencies import get_current_user
from app.models.user import User
from app.modules.chat.service import ChatService
from app.schemas.conversation import (
    ConversationCreate, ConversationCreateDirect, ConversationResponse,
    ConversationUpdate, MessageCreate, MessageResponse, MessageUpdate,
    ReactionAdd, MessageSearchRequest, MarkAsReadRequest,
    ConversationListResponse
)

# Redis client (caching + pub/sub)
from app.infra.redis import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# ========== Conversation Endpoints ==========

@router.post("/conversations/direct", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_direct_conversation(
    data: ConversationCreateDirect,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Create or get direct conversation with another user
    
    Returns existing conversation if found, creates new otherwise
    """
    try:
        service = ChatService(db)
        conversation = await service.create_direct_conversation(current_user.id, data.recipient_id)
        return conversation
    
    except Exception as e:
        logger.error(f"Error creating conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/conversations/group", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_group_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Create group conversation
    """
    try:
        service = ChatService(db)
        conversation = await service.create_group_conversation(current_user.id, data)
        return conversation
    
    except Exception as e:
        logger.error(f"Error creating group: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/conversations", response_model=List[ConversationListResponse])
async def list_conversations(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Get all conversations for current user (cached short-term in Redis)
    """
    cache_key = f"chat:conversations:{current_user.id}:{offset}:{limit}"
    try:
        # Try cache
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            # Redis must be best-effort — ignore on failure
            logger.debug("Redis cache read failed for conversations; falling back to DB")

        service = ChatService(db)
        conversations, total = await service.get_user_conversations(current_user.id, limit, offset)

        # Map to plain serializable dicts matching ConversationListResponse
        payload = []
        for c in conversations:
            # Try read unread count from Redis first
            unread_key = f"chat:unread:{current_user.id}:{c.id}"
            try:
                cached_unread = await redis_client.get(unread_key)
                if cached_unread is not None:
                    unread_count = int(cached_unread)
                else:
                    # Fallback: count unread MessageStatus for this conversation
                    from app.models.conversation import MessageStatus, Message
                    count_stmt = select(func.count(MessageStatus.id)).join(Message).where(
                        MessageStatus.user_id == current_user.id,
                        MessageStatus.status != MessageStatus.READ,
                        Message.conversation_id == c.id
                    )
                    cnt_res = await db.execute(count_stmt)
                    unread_count = cnt_res.scalar() or 0
                    # cache the unread count for a short time
                    try:
                        await redis_client.set(unread_key, str(unread_count), ex=60)
                    except Exception:
                        pass
            except Exception:
                # If Redis fails, fall back to DB count
                from app.models.conversation import MessageStatus, Message
                count_stmt = select(func.count(MessageStatus.id)).join(Message).where(
                    MessageStatus.user_id == current_user.id,
                    MessageStatus.status != MessageStatus.READ,
                    Message.conversation_id == c.id
                )
                cnt_res = await db.execute(count_stmt)
                unread_count = cnt_res.scalar() or 0

            payload.append({
                "id": c.id,
                "conversation_type": c.conversation_type,
                "title": c.title,
                "last_message_preview": c.last_message_preview,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
                "unread_count": int(unread_count),
                "is_muted": False,
                "is_pinned": False,
                "other_participant_id": None,
                "other_participant_name": None,
                "other_participant_avatar": None
            })

        # Cache short-term (best-effort)
        try:
            await redis_client.set(cache_key, json.dumps(payload, default=str), ex=10)
        except Exception:
            logger.debug("Redis cache write failed for conversations; continuing")

        return payload
    
    except Exception as e:
        logger.error(f"Error listing conversations: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list conversations"
        )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Get specific conversation (if user is participant)
    """
    try:
        service = ChatService(db)
        conversation = await service.get_conversation(conversation_id, current_user.id)
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        return conversation
    
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this conversation"
        )
    except Exception as e:
        logger.error(f"Error getting conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get conversation"
        )


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Update conversation (title, archive, etc)
    """
    try:
        service = ChatService(db)
        conversation = await service.get_conversation(conversation_id, current_user.id)
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # TODO: Update conversation fields
        
        return conversation
    
    except Exception as e:
        logger.error(f"Error updating conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ========== Message Endpoints ==========

@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: str,
    data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Send message to conversation
    """
    try:
        service = ChatService(db)
        message = await service.send_message(conversation_id, current_user.id, data)
        return message
    
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this conversation"
        )
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Get messages from conversation (paginated, newest first)
    """
    try:
        service = ChatService(db)
        messages, total = await service.get_messages(conversation_id, current_user.id, limit, offset)
        return messages
    
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this conversation"
        )
    except Exception as e:
        logger.error(f"Error getting messages: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get messages"
        )


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def update_message(
    message_id: str,
    data: MessageUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Edit message (only sender can edit)
    """
    try:
        service = ChatService(db)
        message = await service.edit_message(message_id, current_user.id, data)
        return message
    
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the message sender can edit it"
        )
    except Exception as e:
        logger.error(f"Error updating message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Delete message (soft-delete)
    """
    try:
        service = ChatService(db)
        await service.delete_message(message_id, current_user.id)
        return None
    
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the message sender can delete it"
        )
    except Exception as e:
        logger.error(f"Error deleting message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/messages/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_as_read(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Mark message as read
    """
    try:
        service = ChatService(db)
        await service.mark_as_read(message_id, current_user.id)
        return None
    
    except Exception as e:
        logger.error(f"Error marking as read: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/messages/{message_id}/reactions", response_model=MessageResponse)
async def add_reaction(
    message_id: str,
    data: ReactionAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Add reaction (emoji) to message
    """
    try:
        service = ChatService(db)
        message = await service.add_reaction(message_id, current_user.id, data.emoji)
        return message
    
    except Exception as e:
        logger.error(f"Error adding reaction: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ========== Search Endpoints ==========

@router.post("/messages/search")
async def search_messages(
    data: MessageSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Search messages (full-text search)
    """
    try:
        service = ChatService(db)
        messages = await service.search_messages(current_user.id, data)
        return messages
    
    except Exception as e:
        logger.error(f"Error searching messages: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed"
        )
