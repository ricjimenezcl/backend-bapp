"""
Content Moderation Endpoints - Validación de contenido contra palabras prohibidas
Endpoints para validar texto y gestionar palabras bloqueadas
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.moderation import (
    ContentValidationRequest, ContentValidationResponse,
    BlockedWordCreate, BlockedWordUpdate, BlockedWordResponse, BlockedWordListResponse,
    WordCategory, SeverityLevel
)
from app.services.content_moderation_service import ContentModerationService

router = APIRouter()


@router.post("/validate", response_model=ContentValidationResponse)
async def validate_content(
    validation_request: ContentValidationRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Validar texto contra palabras prohibidas.
    
    - Verifica si el texto contiene palabras bloqueadas
    - Retorna severidad y sugerencias de texto censurado
    - Usado en tiempo real para validar bios, reseñas, mensajes, etc.
    
    Contextos soportados:
    - bio: Biografía de perfil
    - review: Reseña/comentario
    - chat: Mensaje de chat
    - service_description: Descripción de servicio
    - service_name: Nombre de servicio
    """
    service = ContentModerationService(db)
    return await service.validate_content(validation_request)


@router.get("/blocked-words", response_model=List[BlockedWordResponse])
async def get_blocked_words(
    category: Optional[WordCategory] = Query(None, description="Filtrar por categoría"),
    severity: Optional[SeverityLevel] = Query(None, description="Filtrar por severidad"),
    language: str = Query("es", description="Código de idioma ISO 639-1"),
    is_active: bool = Query(True, description="Solo palabras activas"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener lista de palabras bloqueadas (ADMIN ONLY).
    
    - Solo admins pueden ver la lista completa
    - Útil para gestionar diccionario de palabras prohibidas
    """
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = ContentModerationService(db)
    return await service.get_blocked_words(category, severity, language, is_active)


@router.post("/blocked-words", response_model=BlockedWordResponse, status_code=status.HTTP_201_CREATED)
async def add_blocked_word(
    word_data: BlockedWordCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Agregar una palabra bloqueada (ADMIN ONLY).
    
    - Solo admins pueden agregar palabras al diccionario
    - Valida que no exista duplicado
    """
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = ContentModerationService(db)
    return await service.add_blocked_word(word_data, current_user.id)


@router.put("/blocked-words/{word_id}", response_model=BlockedWordResponse)
async def update_blocked_word(
    word_id: int,
    word_update: BlockedWordUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Actualizar una palabra bloqueada (ADMIN ONLY).
    
    - Permite activar/desactivar palabras
    - Cambiar categoría o severidad
    """
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = ContentModerationService(db)
    updated_word = await service.update_blocked_word(word_id, word_update)
    
    if not updated_word:
        raise HTTPException(status_code=404, detail="Blocked word not found")
    
    return updated_word


@router.delete("/blocked-words/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocked_word(
    word_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Eliminar una palabra bloqueada (ADMIN ONLY).
    
    - Eliminación permanente (no soft delete)
    - Usar con precaución
    """
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = ContentModerationService(db)
    success = await service.delete_blocked_word(word_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Blocked word not found")
    
    return None
