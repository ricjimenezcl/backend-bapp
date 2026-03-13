# app/models/conversation.py
"""
Chat Models - Conversations, Messages, Status tracking
SQLAlchemy 2.0 async models for chat system
"""

from sqlalchemy import Column, String, Text, DateTime, Boolean, Enum, ForeignKey, JSON, Integer, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from datetime import datetime
from enum import Enum as PyEnum
import uuid


class ConversationType(str, PyEnum):
    """Conversation type enumeration"""
    DIRECT = "direct"
    GROUP = "group"


class MessageContentType(str, PyEnum):
    """Message content type"""
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    VIDEO = "video"
    AUDIO = "audio"


class MessageStatus(str, PyEnum):
    """Message delivery status"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"


class InvitationStatus(str, PyEnum):
    """Conversation invitation status"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class Conversation(Base):
    """Conversation model - represents a chat (direct or group)"""
    __tablename__ = "conversations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_type = Column(Enum(ConversationType, name="conversation_type_enum"), nullable=False, default=ConversationType.DIRECT)
    title = Column(String(255), nullable=True, comment="Name for group conversations")
    description = Column(Text, nullable=True, comment="Group description")
    
    # Creator
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Last message tracking
    last_message_id = Column(String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    last_message_at = Column(DateTime, nullable=True)
    last_message_preview = Column(String(500), nullable=True)
    
    # Archive
    is_archived = Column(Boolean, default=False)
    archived_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    participants = relationship(
        "ConversationParticipant",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="Message.conversation_id"
    )
    invitations = relationship(
        "ConversationInvitation",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )
    blocks = relationship(
        "ConversationBlock",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )
    created_by = relationship("User", foreign_keys=[created_by_id])
    
    def __repr__(self):
        return f"<Conversation {self.id} ({self.conversation_type})>"


class ConversationParticipant(Base):
    """Junction table linking users to conversations"""
    __tablename__ = "conversation_participants"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Participation status
    joined_at = Column(DateTime, server_default=func.now())
    left_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # Reading tracking
    last_read_message_id = Column(String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    last_read_at = Column(DateTime, nullable=True)
    
    # User preferences
    muted = Column(Boolean, default=False, comment="Mute notifications")
    pinned = Column(Boolean, default=False, comment="Pin to top")
    
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    conversation = relationship("Conversation", back_populates="participants")
    user = relationship("User")
    
    def __repr__(self):
        return f"<ConversationParticipant user={self.user_id} conv={self.conversation_id}>"


class Message(Base):
    """Message model - stores individual messages"""
    __tablename__ = "messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Content
    content = Column(Text, nullable=False)
    content_type = Column(Enum(MessageContentType, name="message_content_type_enum"), default=MessageContentType.TEXT)
    
    # Attachments
    attachment_url = Column(String(500), nullable=True, comment="URL to file/image/video")
    attachment_cloudinary_id = Column(String(255), nullable=True, comment="Cloudinary public_id")
    attachment_size = Column(Integer, nullable=True, comment="Size in bytes")
    attachment_mimetype = Column(String(100), nullable=True, comment="e.g., image/jpeg")
    attachment_metadata = Column(JSON, nullable=True, comment="e.g., {width, height, duration}")
    
    # Editing
    is_edited = Column(Boolean, default=False)
    edited_at = Column(DateTime, nullable=True)
    
    # Deletion
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    
    # Message status
    status = Column(Enum(MessageStatus, name="message_status_enum"), default=MessageStatus.PENDING)
    
    # Threading (reply to message)
    reply_to_message_id = Column(String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    
    # Reactions: [{"emoji": "👍", "user_ids": ["uid1", "uid2"]}, ...]
    reactions = Column(JSON, nullable=True, comment="Array of reactions with user_ids")
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    conversation = relationship("Conversation", back_populates="messages", foreign_keys=[conversation_id])
    sender = relationship("User")
    message_status = relationship(
        "MessageStatus",
        back_populates="message",
        cascade="all, delete-orphan"
    )
    replied_to_message = relationship(
        "Message",
        remote_side=[id],
        foreign_keys=[reply_to_message_id],
        backref="replies"
    )
    
    def __repr__(self):
        return f"<Message {self.id} by {self.sender_id}>"
    
    def add_reaction(self, emoji: str, user_id: str) -> None:
        """Add reaction from user"""
        if not self.reactions:
            self.reactions = []
        
        # Check if emoji already exists
        for reaction in self.reactions:
            if reaction["emoji"] == emoji:
                if user_id not in reaction["user_ids"]:
                    reaction["user_ids"].append(user_id)
                return
        
        # Add new reaction
        self.reactions.append({"emoji": emoji, "user_ids": [user_id]})
    
    def remove_reaction(self, emoji: str, user_id: str) -> None:
        """Remove reaction from user"""
        if not self.reactions:
            return
        
        for reaction in self.reactions:
            if reaction["emoji"] == emoji and user_id in reaction["user_ids"]:
                reaction["user_ids"].remove(user_id)
                # Remove emoji if no users left
                if not reaction["user_ids"]:
                    self.reactions.remove(reaction)


class MessageStatus(Base):
    """Per-user message status tracking"""
    __tablename__ = "message_status"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Status tracking
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    status = Column(Enum(MessageStatus, name="message_status_enum"), default=MessageStatus.SENT)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    message = relationship("Message", back_populates="message_status")
    user = relationship("User")
    
    def __repr__(self):
        return f"<MessageStatus msg={self.message_id} user={self.user_id} status={self.status}>"


class ConversationInvitation(Base):
    """Group conversation invitations"""
    __tablename__ = "conversation_invitations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    invited_by_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    invited_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Invitation status
    status = Column(Enum(InvitationStatus, name="invitation_status_enum"), default=InvitationStatus.PENDING)
    accepted_at = Column(DateTime, nullable=True)
    declined_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    conversation = relationship("Conversation", back_populates="invitations")
    invited_by = relationship("User", foreign_keys=[invited_by_id])
    invited_user = relationship("User", foreign_keys=[invited_user_id])
    
    def __repr__(self):
        return f"<ConversationInvitation {self.status}>"


class ConversationBlock(Base):
    """Block users in conversations"""
    __tablename__ = "conversation_blocks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True)
    blocked_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    blocker_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    conversation = relationship("Conversation", back_populates="blocks")
    blocked_user = relationship("User", foreign_keys=[blocked_user_id])
    blocker_user = relationship("User", foreign_keys=[blocker_user_id])
    
    def __repr__(self):
        return f"<ConversationBlock {self.blocked_user_id}>"
