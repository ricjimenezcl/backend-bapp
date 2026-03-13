"""
Chat models for BAPP Search FASE 2
Handles conversations and messages
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ChatConversation(Base):
    """Chat conversation between client and provider"""
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False, index=True)  # ✅ OPCIÓN B: provider_id = providers.id
    
    # Conversation metadata
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")
    client = relationship("User", foreign_keys=[client_id], backref="client_conversations")
    provider = relationship("Provider", foreign_keys=[provider_id], backref="provider_conversations")

    def __repr__(self):
        return f"<ChatConversation(id={self.id}, client_id={self.client_id}, provider_id={self.provider_id})>"

    class Config:
        orm_mode = True


class ChatMessage(Base):
    """Individual message in a chat conversation"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Message content
    message_content = Column(Text, nullable=False)
    
    # Message status
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    conversation = relationship("ChatConversation", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id], backref="sent_messages")

    def __repr__(self):
        return f"<ChatMessage(id={self.id}, conversation_id={self.conversation_id}, is_read={self.is_read})>"

    def mark_as_read(self):
        """Mark message as read"""
        self.is_read = True
        self.read_at = datetime.utcnow()

    class Config:
        orm_mode = True
