from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.conversation import Conversation, Message, ConversationParticipant
from app.models.user import User
from datetime import datetime
import uuid

router = APIRouter()

@router.post("/conversations/start")
async def start_conversation(
    other_user_id: int = Body(...),
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_active_user)
):
    """
    Inicia (o retorna) una conversación directa entre el usuario autenticado y otro usuario.
    """
    # Buscar si ya existe una conversación directa entre ambos
    result = await db.execute(
        select(Conversation)
        .join(ConversationParticipant)
        .where(
            Conversation.conversation_type == "direct",
            ConversationParticipant.user_id.in_([current_user.id, other_user_id])
        )
    )
    existing = result.scalars().first()
    if existing:
        return {"conversation_id": existing.id}
    # Crear nueva conversación
    conv = Conversation(
        id=str(uuid.uuid4()),
        conversation_type="direct",
        created_by_id=current_user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(conv)
    await db.flush()
    # Participantes
    db.add_all([
        ConversationParticipant(id=str(uuid.uuid4()), conversation_id=conv.id, user_id=current_user.id),
        ConversationParticipant(id=str(uuid.uuid4()), conversation_id=conv.id, user_id=other_user_id)
    ])
    await db.commit()
    return {"conversation_id": conv.id}

@router.get("/conversations")
async def list_conversations(
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_active_user)
):
    """
    Lista todas las conversaciones del usuario autenticado.
    """
    result = await db.execute(
        select(Conversation)
        .join(ConversationParticipant)
        .where(ConversationParticipant.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    conversations = result.scalars().all()
    return [{"id": c.id, "type": c.conversation_type, "title": c.title, "updated_at": c.updated_at} for c in conversations]

@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_active_user)
):
    """
    Lista los mensajes de una conversación (si el usuario es participante).
    """
    # Verificar participación
    result = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == current_user.id
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=403, detail="No autorizado")
    # Listar mensajes
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [{"id": m.id, "sender_id": m.sender_id, "content": m.content, "created_at": m.created_at} for m in messages]

@router.post("/conversations/{conversation_id}/messages/send")
async def send_message(
    conversation_id: str,
    content: str = Body(...),
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_active_user)
):
    """
    Envía un mensaje en una conversación (si el usuario es participante).
    """
    # Verificar participación
    result = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == current_user.id
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=403, detail="No autorizado")
    # Crear mensaje
    msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=content,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(msg)
    await db.commit()
    return {"message_id": msg.id, "created_at": msg.created_at}
