"""
Chat Service for BAPP Search FASE 2
Handles chat conversations and messages operations
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_, or_
from sqlalchemy.orm import selectinload
from sqlalchemy import func

from app.models.chat import ChatConversation, ChatMessage
from app.models.user import User


class ChatService:
    """Service for managing chat conversations and messages"""
    
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== Conversation Operations ====================

    async def get_or_create_conversation(
        self,
        client_id: int,
        provider_id: int
    ) -> ChatConversation:
        """Get existing conversation or create new one"""
        try:
            # Check if conversation exists
            result = await self.db.execute(
                select(ChatConversation).where(
                    and_(
                        ChatConversation.client_id == client_id,
                        ChatConversation.provider_id == provider_id
                    )
                )
            )
            conversation = result.scalars().first()
            
            if conversation:
                return conversation
            
            # Create new conversation
            new_conversation = ChatConversation(
                client_id=client_id,
                provider_id=provider_id
            )
            self.db.add(new_conversation)
            await self.db.commit()
            await self.db.refresh(new_conversation)
            
            return new_conversation
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error creating/getting conversation: {str(e)}")

    async def get_conversation_by_id(
        self,
        conversation_id: int,
        include_messages: bool = False
    ) -> Optional[ChatConversation]:
        """Get conversation by ID WITHOUT loading relationships (avoid async ORM issues)"""
        try:
            # Simple query without selectinload to avoid async ORM issues
            query = select(ChatConversation).where(
                ChatConversation.id == conversation_id
            )
            
            result = await self.db.execute(query)
            conversation = result.scalars().first()
            
            # Don't load relationships via ORM - let frontend fetch separately
            # This avoids SQLAlchemy async lazy-loading issues
            return conversation
            
        except Exception as e:
            raise Exception(f"Error retrieving conversation: {str(e)}")

    async def get_user_conversations(
        self,
        user_id: int,
        provider_id: int = None,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[list, int]:
        """Get all conversations for a user (as client o provider) with eager loading"""
        try:
            filters = [ChatConversation.client_id == user_id]
            if provider_id:
                filters.append(ChatConversation.provider_id == provider_id)
            
            # Base query structure for counting
            count_stmt = select(func.count()).select_from(ChatConversation).where(or_(*filters))
            
            # Main query with eager loading
            # We use selectinload for relationships to avoid N+1 problems
            # loading messages is tricky because we only want the LAST one, 
            # but standard ORM relationship loads ALL. 
            # For now, let's load client and provider efficiently.
            # We will fetch the last message separately or use a subquery if needed, 
            # but selectinload on client/provider is the biggest win.
            query = select(ChatConversation).where(
                or_(*filters)
            ).order_by(
                desc(ChatConversation.updated_at)
            ).options(
                selectinload(ChatConversation.client),
                selectinload(ChatConversation.provider)
            )

            # Total count
            count_result = await self.db.execute(count_stmt)
            total = count_result.scalar_one()

            # Paginado
            result = await self.db.execute(query.offset(skip).limit(limit))
            conversations = result.scalars().all()
            
            return conversations, total
        except Exception as e:
            raise Exception(f"Error retrieving user conversations: {str(e)}")

    async def end_conversation(
        self,
        conversation_id: int
    ) -> bool:
        """End a conversation"""
        try:
            conversation = await self.get_conversation_by_id(conversation_id)
            if not conversation:
                raise ValueError("Conversation not found")
            
            conversation.ended_at = datetime.utcnow()
            await self.db.commit()
            
            return True
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error ending conversation: {str(e)}")

    # ==================== Message Operations ====================

    async def send_message(
        self,
        conversation_id: int,
        sender_id: int,
        content: str
    ) -> ChatMessage:
        """Send a message in a conversation"""
        try:
            # Validate conversation exists and user is participant
            conversation = await self.get_conversation_by_id(conversation_id)
            if not conversation:
                raise ValueError("Conversation not found")

            # Validar correctamente para proveedores y clientes
            is_participant = False
            if sender_id == conversation.client_id:
                is_participant = True
            else:
                # Si es proveedor, buscar provider_id
                from app.models.provider import Provider
                provider = await self.db.execute(
                    select(Provider).where(Provider.user_id == sender_id)
                )
                provider = provider.scalar_one_or_none()
                if provider and provider.id == conversation.provider_id:
                    is_participant = True
            if not is_participant:
                raise ValueError("User is not a participant in this conversation")

            # Create message
            message = ChatMessage(
                conversation_id=conversation_id,
                sender_id=sender_id,
                message_content=content
            )

            self.db.add(message)

            # Update conversation timestamp
            conversation.updated_at = datetime.utcnow()

            await self.db.commit()
            await self.db.refresh(message)

            # Load relationships
            result = await self.db.execute(
                select(ChatMessage).where(ChatMessage.id == message.id).options(
                    selectinload(ChatMessage.sender),
                    selectinload(ChatMessage.conversation)
                )
            )
            message = result.scalars().first()

            return message
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error sending message: {str(e)}")

    async def get_conversation_messages(
        self,
        conversation_id: int,
        skip: int = 0,
        limit: int = 50
    ) -> tuple[List[ChatMessage], int]:
        """Get messages for a conversation (newest first by default) - NO relationships loaded"""
        try:
            # Get total count optimizado
            count_result = await self.db.execute(
                select(func.count()).select_from(ChatMessage).where(
                    ChatMessage.conversation_id == conversation_id
                )
            )
            total = count_result.scalar_one()
            
            # Get messages (ordered by creation date)
            # Don't load sender relationship to avoid async ORM issues
            result = await self.db.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation_id
                ).order_by(
                    ChatMessage.created_at.asc()
                ).offset(skip).limit(limit)
            )
            messages = result.scalars().all()
            
            return messages, total
            
        except Exception as e:
            raise Exception(f"Error retrieving messages: {str(e)}")

    async def mark_message_as_read(
        self,
        message_id: int
    ) -> bool:
        """Mark a message as read"""
        try:
            result = await self.db.execute(
                select(ChatMessage).where(ChatMessage.id == message_id)
            )
            message = result.scalars().first()
            
            if not message:
                raise ValueError("Message not found")
            
            message.mark_as_read()
            await self.db.commit()
            
            return True
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error marking message as read: {str(e)}")

    async def mark_conversation_messages_as_read(
        self,
        conversation_id: int,
        reader_id: int
    ) -> int:
        """Mark all messages in a conversation as read for a user (messages from other user)"""
        try:
            # Get all unread messages from other participant
            result = await self.db.execute(
                select(ChatMessage).where(
                    and_(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.is_read == False,
                        ChatMessage.sender_id != reader_id
                    )
                )
            )
            messages = result.scalars().all()
            
            for message in messages:
                message.mark_as_read()
            
            await self.db.commit()
            
            return len(messages)
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error marking messages as read: {str(e)}")

    async def get_unread_count(
        self,
        conversation_id: int,
        reader_id: int
    ) -> int:
        """Get count of unread messages in a conversation for a user.
        Usa SELECT COUNT(*) en lugar de cargar todos los mensajes — elimina N+1.
        """
        try:
            result = await self.db.execute(
                select(func.count()).select_from(ChatMessage).where(
                    and_(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.is_read == False,
                        ChatMessage.sender_id != reader_id
                    )
                )
            )
            return result.scalar_one()

        except Exception as e:
            raise Exception(f"Error getting unread count: {str(e)}")

    async def get_last_messages_bulk(self, conversation_ids: list) -> dict:
        """Get last message per conversation — 1 query instead of N"""
        if not conversation_ids:
            return {}
        result = await self.db.execute(
            select(ChatMessage).where(
                ChatMessage.conversation_id.in_(conversation_ids)
            ).order_by(
                ChatMessage.conversation_id,
                desc(ChatMessage.created_at)
            ).distinct(ChatMessage.conversation_id)
        )
        return {msg.conversation_id: msg for msg in result.scalars().all()}

    async def get_unread_counts_bulk(self, conversation_ids: list, reader_id: int) -> dict:
        """Get unread count per conversation — 1 query instead of N"""
        if not conversation_ids:
            return {}
        result = await self.db.execute(
            select(
                ChatMessage.conversation_id,
                func.count().label('unread_count')
            ).where(
                and_(
                    ChatMessage.conversation_id.in_(conversation_ids),
                    ChatMessage.is_read == False,
                    ChatMessage.sender_id != reader_id
                )
            ).group_by(ChatMessage.conversation_id)
        )
        return {row.conversation_id: row.unread_count for row in result.all()}

    async def delete_message(
        self,
        message_id: int,
        user_id: int
    ) -> bool:
        """Delete a message (only sender can delete)"""
        try:
            result = await self.db.execute(
                select(ChatMessage).where(ChatMessage.id == message_id)
            )
            message = result.scalars().first()
            
            if not message:
                raise ValueError("Message not found")
            
            if message.sender_id != user_id:
                raise ValueError("Only sender can delete this message")
            
            await self.db.delete(message)
            await self.db.commit()
            
            return True
            
        except Exception as e:
            await self.db.rollback()
            raise Exception(f"Error deleting message: {str(e)}")

    async def get_last_message_in_conversation(
        self,
        conversation_id: int
    ) -> Optional[ChatMessage]:
        """Get the last message in a conversation"""
        try:
            result = await self.db.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation_id
                ).order_by(
                    desc(ChatMessage.created_at)
                ).limit(1).options(
                    selectinload(ChatMessage.sender)
                )
            )
            return result.scalars().first()
            
        except Exception as e:
            raise Exception(f"Error retrieving last message: {str(e)}")
