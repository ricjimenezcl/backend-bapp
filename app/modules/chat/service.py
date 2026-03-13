# app/modules/chat/service.py
"""
Chat Service - Business logic for conversations and messages
Handles creation, retrieval, messaging, and real-time updates
"""

import logging
import json
from typing import Optional, List, Tuple
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# Redis client (for cache invalidation / pubsub)
from app.infra.redis import redis_client

from app.models.conversation import (
    Conversation, ConversationParticipant, Message, MessageStatus,
    ConversationInvitation, ConversationBlock,
    ConversationType, MessageStatus as MessageStatusEnum, InvitationStatus,
    MessageContentType
)
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate, ConversationUpdate, MessageCreate, MessageUpdate,
    ConversationParticipantCreate, ConversationInvitationCreate,
    MessageSearchRequest, BlockUserRequest
)
from app.infra.event_bus import (
    event_bus, EventType, MessageCreatedEvent,
    ConversationCreatedEvent, NotificationCreatedEvent
)
from app.infra.queue import JobType, job_queue
from app.workers import BaseWorker

logger = logging.getLogger(__name__)


class ChatService:
    """Service for chat operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ========== Conversation Management ==========
    
    async def create_direct_conversation(self, user_id: str, recipient_id: str) -> Conversation:
        """
        Create or get direct conversation between two users
        
        Returns existing conversation if found, creates new otherwise
        """
        try:
            # Check if conversation already exists
            stmt = select(Conversation).join(ConversationParticipant).filter(
                Conversation.conversation_type == ConversationType.DIRECT,
                ConversationParticipant.user_id.in_([user_id, recipient_id])
            ).group_by(Conversation.id).having(
                func.count(ConversationParticipant.id) == 2
            )
            
            result = await self.db.execute(stmt)
            existing = result.scalars().first()
            
            if existing:
                return existing
            
            # Create new conversation
            conversation = Conversation(
                id=str(uuid4()),
                conversation_type=ConversationType.DIRECT,
                created_by_id=user_id
            )
            
            # Add both participants
            for participant_id in [user_id, recipient_id]:
                participant = ConversationParticipant(
                    id=str(uuid4()),
                    conversation_id=conversation.id,
                    user_id=participant_id
                )
                self.db.add(participant)
            
            self.db.add(conversation)
            await self.db.commit()
            await self.db.refresh(conversation)
            
            # Publish event
            await event_bus.publish(ConversationCreatedEvent(
                conversation_id=conversation.id,
                participant_ids=[user_id, recipient_id],
                correlation_id=None
            ))
            
            logger.info(f"✅ Direct conversation created: {conversation.id}")
            return conversation
        
        except Exception as e:
            logger.error(f"❌ Create conversation failed: {str(e)}")
            raise
    
    async def create_group_conversation(self, creator_id: str, data: ConversationCreate) -> Conversation:
        """Create group conversation"""
        try:
            conversation = Conversation(
                id=str(uuid4()),
                conversation_type=ConversationType.GROUP,
                title=data.title,
                description=data.description,
                created_by_id=creator_id
            )
            
            # Add creator first
            self.db.add(conversation)
            
            creator_participant = ConversationParticipant(
                id=str(uuid4()),
                conversation_id=conversation.id,
                user_id=creator_id
            )
            self.db.add(creator_participant)
            
            # Add other participants
            for participant_id in data.participant_ids:
                if participant_id != creator_id:
                    participant = ConversationParticipant(
                        id=str(uuid4()),
                        conversation_id=conversation.id,
                        user_id=participant_id
                    )
                    self.db.add(participant)
            
            await self.db.commit()
            await self.db.refresh(conversation)
            
            # Publish event
            await event_bus.publish(ConversationCreatedEvent(
                conversation_id=conversation.id,
                participant_ids=data.participant_ids + [creator_id],
                correlation_id=None
            ))
            
            logger.info(f"✅ Group conversation created: {conversation.id}")
            return conversation
        
        except Exception as e:
            logger.error(f"❌ Create group conversation failed: {str(e)}")
            raise
    
    async def get_conversation(self, conversation_id: str, user_id: str) -> Optional[Conversation]:
        """Get conversation if user is participant"""
        try:
            stmt = select(Conversation).options(
                selectinload(Conversation.participants),
                selectinload(Conversation.messages)
            ).where(Conversation.id == conversation_id)
            
            result = await self.db.execute(stmt)
            conversation = result.scalars().first()
            
            if not conversation:
                return None
            
            # Check if user is participant
            is_participant = any(p.user_id == user_id for p in conversation.participants)
            if not is_participant:
                raise PermissionError("User is not participant of this conversation")
            
            return conversation
        
        except Exception as e:
            logger.error(f"❌ Get conversation failed: {str(e)}")
            raise
    
    async def get_user_conversations(self, user_id: str, limit: int = 50, offset: int = 0) -> Tuple[List[Conversation], int]:
        """Get all conversations for user (ordered by last message)"""
        try:
            # Count total
            count_stmt = select(func.count(Conversation.id)).join(ConversationParticipant).filter(
                ConversationParticipant.user_id == user_id,
                ConversationParticipant.is_active == True
            )
            count_result = await self.db.execute(count_stmt)
            total = count_result.scalar()
            
            # Get paginated
            # Avoid eager-loading full message lists when returning conversation summaries.
            # Use Conversation.last_message_at / last_message_preview instead (much cheaper).
            stmt = select(Conversation).join(ConversationParticipant).options(
                selectinload(Conversation.participants)
            ).filter(
                ConversationParticipant.user_id == user_id,
                ConversationParticipant.is_active == True
            ).order_by(
                desc(Conversation.last_message_at),
                desc(Conversation.created_at)
            ).limit(limit).offset(offset)
            
            result = await self.db.execute(stmt)
            conversations = result.unique().scalars().all()
            
            return conversations, total
        
        except Exception as e:
            logger.error(f"❌ Get conversations failed: {str(e)}")
            raise
    
    # ========== Message Operations ==========
    
    async def send_message(self, conversation_id: str, sender_id: str, data: MessageCreate) -> Message:
        """Send message to conversation"""
        try:
            # Verify sender is participant
            await self.get_conversation(conversation_id, sender_id)
            
            # Create message
            message = Message(
                id=str(uuid4()),
                conversation_id=conversation_id,
                sender_id=sender_id,
                content=data.content,
                content_type=data.content_type,
                attachment_url=data.attachment_url,
                attachment_cloudinary_id=data.attachment_cloudinary_id,
                attachment_size=data.attachment_size,
                attachment_mimetype=data.attachment_mimetype,
                reply_to_message_id=data.reply_to_message_id,
                status=MessageStatusEnum.SENT
            )
            
            self.db.add(message)
            
            # Update conversation last message
            conversation = await self.get_conversation(conversation_id, sender_id)
            conversation.last_message_id = message.id
            conversation.last_message_at = datetime.utcnow()
            conversation.last_message_preview = data.content[:100]
            
            # Create message status for all other participants
            stmt = select(ConversationParticipant.user_id).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id != sender_id
            )
            result = await self.db.execute(stmt)
            recipient_ids = result.scalars().all()
            
            for recipient_id in recipient_ids:
                status = MessageStatus(
                    id=str(uuid4()),
                    message_id=message.id,
                    user_id=recipient_id,
                    status=MessageStatusEnum.SENT
                )
                self.db.add(status)
            
            await self.db.commit()
            await self.db.refresh(message)
            
            # Publish event
            await event_bus.publish(MessageCreatedEvent(
                message_id=message.id,
                conversation_id=conversation_id,
                sender_id=sender_id,
                content=data.content,
                correlation_id=None
            ))
            
            # Enqueue notification job
            await BaseWorker.enqueue_job(
                job_type=JobType.NOTIFY_NEW_MESSAGE,
                payload={
                    "message_id": message.id,
                    "conversation_id": conversation_id,
                    "sender_id": sender_id,
                    "recipient_ids": recipient_ids
                },
                priority=8
            )

            # Invalidate cached conversation lists for affected users (best-effort)
            # Usa DEL explícito en lugar de KEYS scan (O(1) vs O(N) bloqueante)
            try:
                affected_user_ids = list(set(list(recipient_ids) + [sender_id]))
                keys_to_delete = []
                for uid in affected_user_ids:
                    # Cache keys explícitas sin scan — patrón de cache.py
                    keys_to_delete.append(f"cache:chat:conversations:{uid}")
                keys_to_delete.append(f"cache:chat:messages:{conversation_id}")
                await redis_client.delete(*keys_to_delete)
            except Exception as e:
                logger.warning(f"Redis cache invalidation failed: {e}")

            logger.info(f"✅ Message sent: {message.id}")
            return message
        
        except Exception as e:
            logger.error(f"❌ Send message failed: {str(e)}")
            await self.db.rollback()
            raise
    
    async def get_messages(self, conversation_id: str, user_id: str, 
                          limit: int = 50, offset: int = 0) -> Tuple[List[Message], int]:
        """Get messages from conversation (newest first)"""
        try:
            # Verify access
            await self.get_conversation(conversation_id, user_id)
            
            # Count total
            count_stmt = select(func.count(Message.id)).filter(
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            )
            count_result = await self.db.execute(count_stmt)
            total = count_result.scalar()
            
            # Get paginated (newest first)
            stmt = select(Message).options(
                selectinload(Message.message_status)
            ).filter(
                Message.conversation_id == conversation_id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).limit(limit).offset(offset)
            
            result = await self.db.execute(stmt)
            messages = result.scalars().all()
            
            return list(reversed(messages)), total
        
        except Exception as e:
            logger.error(f"❌ Get messages failed: {str(e)}")
            raise
    
    async def edit_message(self, message_id: str, user_id: str, data: MessageUpdate) -> Message:
        """Edit message (only sender can edit)"""
        try:
            stmt = select(Message).where(Message.id == message_id)
            result = await self.db.execute(stmt)
            message = result.scalars().first()
            
            if not message:
                raise ValueError("Message not found")
            
            if message.sender_id != user_id:
                raise PermissionError("Only sender can edit message")
            
            message.content = data.content
            message.is_edited = True
            message.edited_at = datetime.utcnow()
            
            await self.db.commit()
            await self.db.refresh(message)
            
            logger.info(f"✅ Message edited: {message.id}")
            return message
        
        except Exception as e:
            logger.error(f"❌ Edit message failed: {str(e)}")
            await self.db.rollback()
            raise
    
    async def delete_message(self, message_id: str, user_id: str) -> bool:
        """Soft-delete message"""
        try:
            stmt = select(Message).where(Message.id == message_id)
            result = await self.db.execute(stmt)
            message = result.scalars().first()
            
            if not message:
                raise ValueError("Message not found")
            
            if message.sender_id != user_id:
                raise PermissionError("Only sender can delete message")
            
            message.is_deleted = True
            message.deleted_at = datetime.utcnow()
            
            await self.db.commit()
            logger.info(f"✅ Message deleted: {message.id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Delete message failed: {str(e)}")
            await self.db.rollback()
            raise
    
    async def mark_as_read(self, message_id: str, user_id: str) -> bool:
        """Mark message as read and update Redis unread counters"""
        try:
            stmt = select(MessageStatus).where(
                and_(
                    MessageStatus.message_id == message_id,
                    MessageStatus.user_id == user_id
                )
            )
            result = await self.db.execute(stmt)
            msg_status = result.scalars().first()
            
            if msg_status:
                msg_status.status = MessageStatusEnum.READ
                msg_status.read_at = datetime.utcnow()
                await self.db.commit()

                # Attempt to decrement unread counter in Redis (best-effort)
                try:
                    # find message conversation id
                    msg_stmt = select(Message).where(Message.id == message_id)
                    msg_res = await self.db.execute(msg_stmt)
                    msg = msg_res.scalars().first()
                    if msg:
                        key = f"chat:unread:{user_id}:{msg.conversation_id}"
                        try:
                            # Use DECR but ensure non-negative
                            val = await redis_client.get(key)
                            if val is not None:
                                new_val = max(0, int(val) - 1)
                                await redis_client.set(key, str(new_val), ex=60)
                        except Exception:
                            pass

                    # Invalidar cache de lista de conversaciones del usuario (DEL explícito)
                    try:
                        await redis_client.delete(f"cache:chat:conversations:{user_id}")
                    except Exception:
                        pass
                except Exception:
                    pass

                logger.info(f"✅ Message marked as read: {message_id}")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Mark as read failed: {str(e)}")
            await self.db.rollback()
            raise
    
    async def add_reaction(self, message_id: str, user_id: str, emoji: str) -> Message:
        """Add reaction to message"""
        try:
            stmt = select(Message).where(Message.id == message_id)
            result = await self.db.execute(stmt)
            message = result.scalars().first()
            
            if not message:
                raise ValueError("Message not found")
            
            message.add_reaction(emoji, user_id)
            await self.db.commit()
            await self.db.refresh(message)
            
            logger.info(f"✅ Reaction added: {message.id}")
            return message
        
        except Exception as e:
            logger.error(f"❌ Add reaction failed: {str(e)}")
            await self.db.rollback()
            raise
    
    # ========== Search ==========
    
    async def search_messages(self, user_id: str, data: MessageSearchRequest) -> List[Message]:
        """Full-text search messages"""
        try:
            # TODO: Implement full-text search using message_search_index table
            # For now, simple LIKE search
            
            query = data.query.lower()
            
            stmt = select(Message).filter(
                Message.content.ilike(f"%{query}%"),
                Message.is_deleted == False
            )
            
            if data.conversation_id:
                stmt = stmt.filter(Message.conversation_id == data.conversation_id)
            
            if data.sender_id:
                stmt = stmt.filter(Message.sender_id == data.sender_id)
            
            if data.from_date:
                stmt = stmt.filter(Message.created_at >= data.from_date)
            
            if data.to_date:
                stmt = stmt.filter(Message.created_at <= data.to_date)
            
            stmt = stmt.order_by(desc(Message.created_at)).limit(data.limit).offset(data.offset)
            
            result = await self.db.execute(stmt)
            messages = result.scalars().all()
            
            return messages
        
        except Exception as e:
            logger.error(f"❌ Search failed: {str(e)}")
            raise


# Service instance
chat_service = ChatService
