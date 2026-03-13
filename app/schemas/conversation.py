# app/schemas/conversation.py
"""
Chat Schemas - Pydantic models for chat operations
Type-safe request/response validation
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from uuid import UUID


class ConversationType(str, Enum):
    """Conversation type"""
    DIRECT = "direct"
    GROUP = "group"


class MessageContentType(str, Enum):
    """Message content type"""
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    VIDEO = "video"
    AUDIO = "audio"


class MessageStatus(str, Enum):
    """Message status"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"


class InvitationStatus(str, Enum):
    """Invitation status"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


# ========== Message Schemas ==========

class MessageBase(BaseModel):
    """Base message schema"""
    content: str = Field(..., min_length=1, max_length=5000)
    content_type: MessageContentType = MessageContentType.TEXT
    reply_to_message_id: Optional[str] = None
    
    @validator('content')
    def content_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Content cannot be empty or whitespace only')
        return v.strip()


class MessageCreate(MessageBase):
    """Create message request"""
    conversation_id: str
    attachment_url: Optional[str] = None
    attachment_cloudinary_id: Optional[str] = None
    attachment_size: Optional[int] = None
    attachment_mimetype: Optional[str] = None


class MessageUpdate(BaseModel):
    """Update message"""
    content: str = Field(..., min_length=1, max_length=5000)
    
    @validator('content')
    def content_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Content cannot be empty')
        return v.strip()


class ReactionAdd(BaseModel):
    """Add reaction to message"""
    emoji: str = Field(..., min_length=1, max_length=10)


class MessageStatusSchema(BaseModel):
    """Message status for a user"""
    id: str
    user_id: str
    delivered_at: Optional[datetime]
    read_at: Optional[datetime]
    status: MessageStatus
    
    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    """Message response"""
    id: str
    conversation_id: str
    sender_id: Optional[str]
    content: str
    content_type: MessageContentType
    is_edited: bool
    edited_at: Optional[datetime]
    is_deleted: bool
    deleted_at: Optional[datetime]
    status: MessageStatus
    reply_to_message_id: Optional[str]
    reactions: Optional[List[Dict[str, Any]]] = None
    
    # Attachments
    attachment_url: Optional[str]
    attachment_cloudinary_id: Optional[str]
    attachment_size: Optional[int]
    attachment_mimetype: Optional[str]
    
    created_at: datetime
    updated_at: datetime
    
    # Include message statuses per user
    message_status: List[MessageStatusSchema] = []
    
    class Config:
        from_attributes = True


# ========== Conversation Schemas ==========

class ConversationParticipantCreate(BaseModel):
    """Add participant to conversation"""
    user_id: str


class ConversationParticipantResponse(BaseModel):
    """Conversation participant response"""
    id: str
    user_id: str
    joined_at: datetime
    left_at: Optional[datetime]
    is_active: bool
    last_read_at: Optional[datetime]
    muted: bool
    pinned: bool
    
    class Config:
        from_attributes = True


class ConversationBase(BaseModel):
    """Base conversation schema"""
    conversation_type: ConversationType = ConversationType.DIRECT
    title: Optional[str] = None
    description: Optional[str] = None


class ConversationCreate(ConversationBase):
    """Create conversation request"""
    participant_ids: List[str] = Field(..., min_items=2, max_items=100)
    
    @validator('participant_ids')
    def unique_participants(cls, v):
        if len(v) != len(set(v)):
            raise ValueError('Duplicate participant IDs')
        return v


class ConversationCreateDirect(BaseModel):
    """Create direct conversation"""
    recipient_id: str


class ConversationUpdate(BaseModel):
    """Update conversation"""
    title: Optional[str] = None
    description: Optional[str] = None
    is_archived: Optional[bool] = None


class ConversationResponse(ConversationBase):
    """Conversation response"""
    id: str
    created_by_id: str
    last_message_id: Optional[str]
    last_message_at: Optional[datetime]
    last_message_preview: Optional[str]
    is_archived: bool
    archived_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    # Included data
    participants: List[ConversationParticipantResponse] = []
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0
    
    class Config:
        from_attributes = True


# ========== Invitation Schemas ==========

class ConversationInvitationCreate(BaseModel):
    """Invite users to group conversation"""
    invited_user_ids: List[str] = Field(..., min_items=1, max_items=100)
    
    @validator('invited_user_ids')
    def unique_invitations(cls, v):
        if len(v) != len(set(v)):
            raise ValueError('Duplicate user IDs')
        return v


class ConversationInvitationResponse(BaseModel):
    """Invitation response"""
    id: str
    conversation_id: str
    invited_by_id: str
    invited_user_id: str
    status: InvitationStatus
    accepted_at: Optional[datetime]
    declined_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class InvitationAction(BaseModel):
    """Accept/decline invitation"""
    action: str = Field(..., regex="^(accept|decline)$")


# ========== Chat List Schemas ==========

class ConversationListResponse(BaseModel):
    """Conversation list item (optimized for chat list view)"""
    id: str
    conversation_type: ConversationType
    title: Optional[str]
    last_message_preview: Optional[str]
    last_message_at: Optional[datetime]
    unread_count: int
    is_muted: bool
    is_pinned: bool
    
    # For direct conversations, show other participant
    other_participant_id: Optional[str]
    other_participant_name: Optional[str]
    other_participant_avatar: Optional[str]
    
    class Config:
        from_attributes = True


# ========== Search Schemas ==========

class MessageSearchRequest(BaseModel):
    """Search messages"""
    query: str = Field(..., min_length=1, max_length=100)
    conversation_id: Optional[str] = None
    sender_id: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class MessageSearchResponse(BaseModel):
    """Search result"""
    id: str
    conversation_id: str
    sender_id: Optional[str]
    content: str
    created_at: datetime
    matched_positions: List[tuple] = []  # (start, end) positions of matches
    
    class Config:
        from_attributes = True


# ========== Batch Schemas ==========

class MarkAsReadRequest(BaseModel):
    """Mark messages as read"""
    message_ids: List[str] = Field(..., min_items=1, max_items=100)


class BulkUpdateRequest(BaseModel):
    """Bulk update conversations"""
    conversation_ids: List[str] = Field(..., min_items=1, max_items=100)
    is_archived: Optional[bool] = None
    muted: Optional[bool] = None
    pinned: Optional[bool] = None


# ========== Block Schemas ==========

class BlockUserRequest(BaseModel):
    """Block user in conversation"""
    blocked_user_id: str
    reason: Optional[str] = None


class UnblockUserRequest(BaseModel):
    """Unblock user in conversation"""
    blocked_user_id: str
