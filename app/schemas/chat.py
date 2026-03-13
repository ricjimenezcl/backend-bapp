"""
Chat API Schemas for request/response validation
"""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class UserBasicResponse(BaseModel):
    """Basic user info for responses"""
    id: int
    email: str
    role: str
    status: str
    name: Optional[str] = None

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    """Message response schema"""
    id: int
    conversation_id: int
    sender_id: int
    message_content: str
    is_read: bool
    created_at: datetime
    updated_at: datetime
    sender: Optional[UserBasicResponse] = None

    class Config:
        from_attributes = True


class MessageCreateRequest(BaseModel):
    """Message creation request schema"""
    content: str

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    """Conversation response schema (enriched for listing)"""
    id: int
    client_id: int
    provider_id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    # Enriched fields for UX
    other_participant_id: Optional[int] = None
    other_participant_name: Optional[str] = None
    other_participant_avatar: Optional[str] = None
    last_message_preview: Optional[str] = None
    unread_count: int = 0

    class Config:
        from_attributes = True


class ConversationDetailResponse(BaseModel):
    """Detailed conversation response with participants and messages"""
    id: int
    client_id: int
    provider_id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    client: Optional[UserBasicResponse] = None
    provider: Optional[UserBasicResponse] = None
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """List of conversations with pagination"""
    total: int
    skip: int
    limit: int
    items: List[ConversationResponse]

    class Config:
        from_attributes = True


# Notification Schemas

class NotificationResponse(BaseModel):
    """Notification response schema"""
    id: int
    user_id: int
    notification_type: str
    title: str
    content: str
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    is_read: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NotificationCreateRequest(BaseModel):
    """Notification creation request"""
    notification_type: str
    title: str
    content: str
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """List of notifications with pagination"""
    total: int
    skip: int
    limit: int
    items: List[NotificationResponse]

    class Config:
        from_attributes = True
