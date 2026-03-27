"""
Chat API Endpoints for FASE 2
Handles all chat-related HTTP requests
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db_async
from app.models.user import User, UserProfile
from app.models.provider import Provider
from app.models.chat import ChatConversation as Conversation  # Import with alias
from app.services.chat_service import ChatService
from app.services.premium_service import PremiumService
from app.infra.redis import get_chat_messages_cache, set_chat_messages_cache
from app.infra.redis import get_chat_conversations_cache, set_chat_conversations_cache
from app.services.notification_dispatcher import NotificationDispatcher
from app.dependencies import get_current_user
from app.schemas.chat import (
    ConversationResponse,
    ConversationDetailResponse,
    MessageResponse,
    MessageCreateRequest,
    ConversationListResponse,
    UserBasicResponse
)

router = APIRouter(tags=["chat"])


# ==================== Conversation Endpoints ====================

@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Get all conversations for the current user (as client or provider)"""
    try:
        service = ChatService(db)
        provider_id = None
        if current_user.role == "PROVIDER":
            provider_result = await db.execute(
                select(Provider).where(Provider.user_id == current_user.id)
            )
            provider = provider_result.scalar_one_or_none()
            if provider:
                provider_id = provider.id
        # Intentar cache
        cached = get_chat_conversations_cache(current_user.id, provider_id or 0, skip, limit)
        if cached:
            logger.info(f"✅ [CACHE] Chat conversations hit ({current_user.id}, {provider_id}, {skip}, {limit})")
            return ConversationListResponse(**cached)
        conversations, total = await service.get_user_conversations(
            user_id=current_user.id,
            provider_id=provider_id,
            skip=skip,
            limit=limit
        )

        # Bulk queries: 2 queries reemplazan 2×N queries individuales
        conversation_ids = [conv.id for conv in conversations]
        last_messages = await service.get_last_messages_bulk(conversation_ids)
        unread_counts = await service.get_unread_counts_bulk(conversation_ids, current_user.id)

        items = []
        for conv in conversations:
            # Identificar al otro participante
            other_user_id = conv.provider.user_id if current_user.id == conv.client_id else conv.client_id

            other_name = "Usuario"
            other_avatar = None

            if current_user.id == conv.client_id and conv.provider:
                other_name = conv.provider.full_name
                other_avatar = conv.provider.avatar
            elif conv.client:
                if hasattr(conv.client, 'client_profile') and conv.client.client_profile:
                    other_name = conv.client.client_profile.full_name
                    other_avatar = conv.client.client_profile.avatar
                else:
                    other_name = conv.client.email.split('@')[0]

            last_msg = last_messages.get(conv.id)
            last_preview = last_msg.message_content if last_msg else "Sin mensajes"
            unread = unread_counts.get(conv.id, 0)

            items.append(ConversationResponse(
                id=conv.id,
                client_id=conv.client_id,
                provider_id=conv.provider_id,
                started_at=conv.started_at,
                ended_at=conv.ended_at,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                other_participant_id=other_user_id,
                other_participant_name=other_name,
                other_participant_avatar=other_avatar,
                last_message_preview=last_preview,
                unread_count=unread
            ))

        response = dict(total=total, skip=skip, limit=limit, items=[item.dict() for item in items])
        set_chat_conversations_cache(current_user.id, provider_id or 0, skip, limit, response)
        logger.info(f"✅ [CACHE] Guardado chat conversations ({current_user.id}, {provider_id}, {skip}, {limit})")
        return ConversationListResponse(**response)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/conversations/{provider_id}", response_model=ConversationDetailResponse)
async def get_or_create_conversation(
    provider_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Get existing conversation or create a new one (⚠️ PREMIUM ACCESS PROTECTED for new conversations)"""
    try:
        # Validate that provider_id exists in providers table
        provider_result = await db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        provider = provider_result.scalars().first()

        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Proveedor con ID {provider_id} no encontrado"
            )

        # Check if conversation already exists — if yes, skip premium check
        from app.models.chat import ChatConversation
        from sqlalchemy import and_
        existing = await db.execute(
            select(ChatConversation).where(
                and_(
                    ChatConversation.client_id == current_user.id,
                    ChatConversation.provider_id == provider_id,
                )
            )
        )
        conversation_exists = existing.scalar_one_or_none() is not None

        # Only validate premium when creating a NEW conversation
        if not conversation_exists and current_user.role == "CLIENT":
            premium_service = PremiumService(db)
            try:
                await premium_service.validate_provider_access(
                    client_id=current_user.id,
                    provider_id=provider_id
                )
            except HTTPException as pe:
                # Fail-open when location is unavailable (400) — block only explicit PREMIUM_REQUIRED (403)
                if pe.status_code == status.HTTP_403_FORBIDDEN:
                    raise

        service = ChatService(db)
        conversation = await service.get_or_create_conversation(
            client_id=current_user.id,
            provider_id=provider_id
        )
        
        # Manual conversion to avoid serialization issues
        return ConversationDetailResponse(
            id=conversation.id,
            client_id=conversation.client_id,
            provider_id=conversation.provider_id,
            started_at=conversation.started_at,
            ended_at=conversation.ended_at,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            client=None,  # Placeholder - relationships loaded but not needed for now
            provider=None,  # Placeholder - relationships loaded but not needed for now
            messages=[]  # Placeholder - messages loaded but not needed for now
        )
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Get a specific conversation with all messages"""
    try:
        logger.debug(f"\n[DEBUG GET_CONVERSATION] Starting for conversation {conversation_id}")
        logger.debug(f"[DEBUG GET_CONVERSATION] Current user: {current_user.id}")
        
        service = ChatService(db)
        # Don't load messages here - frontend will fetch separately
        conversation = await service.get_conversation_by_id(conversation_id, include_messages=False)
        
        logger.debug(f"[DEBUG GET_CONVERSATION] Conversation found: {conversation is not None}")
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Verificar si el usuario es participante (cliente o proveedor)
        is_participant = False
        if current_user.id == conversation.client_id:
            is_participant = True
        elif current_user.role == "PROVIDER":
            # Buscar provider_id correspondiente
            provider_result = await db.execute(
                select(Provider).where(Provider.user_id == current_user.id)
            )
            provider = provider_result.scalar_one_or_none()
            if provider and provider.id == conversation.provider_id:
                is_participant = True
        if not is_participant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        
        # --- Cargar datos del CLIENT ---
        # CLIENT: users.id == conversation.client_id
        # Nombre: user_profiles.full_name (si existe), fallback email
        client_user_result = await db.execute(
            select(User).where(User.id == conversation.client_id)
        )
        client_user_obj = client_user_result.scalar_one_or_none()

        client_profile_result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == conversation.client_id)
        )
        client_profile_obj = client_profile_result.scalar_one_or_none()

        # --- Cargar datos del PROVIDER ---
        # PROVIDER: providers.id == conversation.provider_id → obtener providers.user_id
        # Nombre: providers.full_name
        provider_record_result = await db.execute(
            select(Provider).where(Provider.id == conversation.provider_id)
        )
        provider_record = provider_record_result.scalar_one_or_none()

        provider_user_obj = None
        if provider_record:
            provider_user_result = await db.execute(
                select(User).where(User.id == provider_record.user_id)
            )
            provider_user_obj = provider_user_result.scalar_one_or_none()

        # --- Construir respuesta ---
        client_user = None
        provider_user = None

        if client_user_obj:
            client_name = (
                client_profile_obj.full_name
                if client_profile_obj and client_profile_obj.full_name
                else client_user_obj.email.split('@')[0]
            )
            client_user = UserBasicResponse(
                id=client_user_obj.id,
                email=client_user_obj.email,
                role=client_user_obj.role,
                status=client_user_obj.status,
                name=client_name
            )

        if provider_user_obj and provider_record:
            provider_user = UserBasicResponse(
                id=provider_user_obj.id,
                email=provider_user_obj.email,
                role=provider_user_obj.role,
                status=provider_user_obj.status,
                name=provider_record.full_name or provider_user_obj.email.split('@')[0]
            )
        
        logger.debug(f"[DEBUG GET_CONVERSATION] Returning conversation {conversation_id}")
        
        # Return conversation WITHOUT messages - frontend will fetch them separately
        response = ConversationDetailResponse(
            id=conversation.id,
            client_id=conversation.client_id,
            provider_id=conversation.provider_id,
            started_at=conversation.started_at,
            ended_at=conversation.ended_at,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            client=client_user,
            provider=provider_user,
            messages=[]  # Empty - frontend will fetch with separate call
        )
        logger.debug(f"[DEBUG GET_CONVERSATION] Response created successfully")
        return response
        
    except HTTPException as e:
        logger.debug(f"[DEBUG GET_CONVERSATION] HTTPException: {e.detail}")
        raise
    except Exception as e:
        logger.debug(f"[DEBUG GET_CONVERSATION] Exception: {str(e)}")
        import traceback
        logger.info(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ==================== Message Endpoints ====================

@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Get messages for a conversation"""
    try:
        service = ChatService(db)
        # Verify conversation exists and user is participant
        conversation = await service.get_conversation_by_id(conversation_id)
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        # Validar acceso correctamente para proveedores y clientes
        is_authorized = False
        if current_user.id == conversation.client_id:
            is_authorized = True
        else:
            from app.models.provider import Provider
            provider = await db.execute(
                select(Provider).where(Provider.user_id == current_user.id)
            )
            provider = provider.scalar_one_or_none()
            if provider and provider.id == conversation.provider_id:
                is_authorized = True
        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this conversation"
            )
        # Intentar cache
        cached = get_chat_messages_cache(conversation_id, skip, limit)
        if cached:
            logger.info(f"✅ [CACHE] Chat messages hit ({conversation_id}, {skip}, {limit})")
            return [MessageResponse(**msg) for msg in cached]
        messages, total = await service.get_conversation_messages(
            conversation_id=conversation_id,
            skip=skip,
            limit=limit
        )
        result = [MessageResponse(
            id=msg.id,
            conversation_id=msg.conversation_id,
            sender_id=msg.sender_id,
            message_content=msg.message_content,
            is_read=msg.is_read,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
            sender=None
        ).dict() for msg in messages]
        set_chat_messages_cache(conversation_id, skip, limit, result)
        logger.info(f"✅ [CACHE] Guardado chat messages ({conversation_id}, {skip}, {limit})")
        return [MessageResponse(**msg) for msg in result]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: int,
    request: MessageCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Send a message in a conversation"""
    try:
        service = ChatService(db)
        # Verify conversation and user is participant
        conversation = await service.get_conversation_by_id(conversation_id)
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        # Validar acceso correctamente para proveedores y clientes
        is_authorized = False
        sender_id = current_user.id
        if current_user.id == conversation.client_id:
            is_authorized = True
        else:
            from app.models.provider import Provider
            provider = await db.execute(
                select(Provider).where(Provider.user_id == current_user.id)
            )
            provider = provider.scalar_one_or_none()
            if provider and provider.id == conversation.provider_id:
                is_authorized = True
                sender_id = current_user.id
        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to send messages in this conversation"
            )
        # Send message
        message = await service.send_message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            content=request.content
        )
        # Determine recipient (the other participant)
        recipient_id = conversation.provider_id if current_user.id == conversation.client_id else conversation.client_id
        # Load recipient user
        recipient_result = await db.execute(
            select(User).where(User.id == recipient_id)
        )
        recipient = recipient_result.scalars().first()
        # Dispatch notification in background (non-blocking)
        if recipient:
            async def send_notification():
                try:
                    dispatcher = NotificationDispatcher(db)
                    await dispatcher.dispatch_chat_message(
                        message=message,
                        recipient=recipient,
                        sender=current_user,
                        conversation=conversation
                    )
                except Exception:
                    pass
            background_tasks.add_task(send_notification)
        
        # Manual conversion to avoid serialization issues
        sender_data = None
        if message.sender:
            sender_data = UserBasicResponse(
                id=message.sender.id,
                email=message.sender.email,
                role=message.sender.role,
                status=message.sender.status
            )
        
        response = MessageResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_id=message.sender_id,
            message_content=message.message_content,
            is_read=message.is_read,
            created_at=message.created_at,
            updated_at=message.updated_at,
            sender=sender_data
        )
        return response
    except HTTPException as e:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Total de mensajes no leídos en todas las conversaciones del usuario."""
    try:
        service = ChatService(db)
        # Obtener todas las conversaciones del usuario
        provider_id = None
        if current_user.role == "PROVIDER":
            from sqlalchemy import select as _select
            p_result = await db.execute(_select(Provider).where(Provider.user_id == current_user.id))
            p = p_result.scalar_one_or_none()
            if p:
                provider_id = p.id
        conversations, _ = await service.get_user_conversations(
            user_id=current_user.id, provider_id=provider_id, skip=0, limit=500
        )
        conv_ids = [c.id for c in conversations]
        counts = await service.get_unread_counts_bulk(conv_ids, current_user.id)
        total = sum(counts.values())
        return {"count": total}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/conversations/{conversation_id}/read")
async def mark_conversation_read(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Marca todos los mensajes de una conversación como leídos (alias PUT de /read-all)."""
    try:
        service = ChatService(db)
        count = await service.mark_conversation_messages_as_read(
            conversation_id=conversation_id,
            reader_id=current_user.id
        )
        return {"status": "success", "marked_read": count}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/conversations/{conversation_id}/read-all")
async def mark_all_messages_as_read(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Mark all messages in a conversation as read for the current user"""
    try:
        service = ChatService(db)
        count = await service.mark_conversation_messages_as_read(
            conversation_id=conversation_id,
            reader_id=current_user.id
        )
        return {"status": "success", "marked_read": count}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/messages/{message_id}/read")
async def mark_message_as_read(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Mark a message as read"""
    try:
        service = ChatService(db)
        success = await service.mark_message_as_read(message_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        return {"status": "success", "message": "Message marked as read"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Delete a message (only sender can delete)"""
    try:
        service = ChatService(db)
        success = await service.delete_message(
            message_id=message_id,
            user_id=current_user.id
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        return {"status": "success", "message": "Message deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
