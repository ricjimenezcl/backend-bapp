"""
Content Moderation Service - Validación de contenido contra palabras prohibidas
"""
import re
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.blocked_word import BlockedWord, WordCategory, SeverityLevel
from app.schemas.moderation import (
    ContentValidationRequest, ContentValidationResponse,
    BlockedWordCreate, BlockedWordUpdate, BlockedWordResponse
)
from fastapi import HTTPException, status


class ContentModerationService:
    """Servicio para validación y moderación de contenido"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._words_cache: Optional[List[BlockedWord]] = None
    
    async def validate_content(
        self, 
        validation_request: ContentValidationRequest
    ) -> ContentValidationResponse:
        """
        Validar texto contra palabras prohibidas
        
        Retorna:
        - is_valid: Si el contenido puede publicarse
        - blocked_words: Lista de palabras encontradas
        - severity: Severidad máxima detectada
        - suggested_text: Texto con censura (opcional)
        """
        text = validation_request.text.lower()
        
        # Obtener palabras bloqueadas (con cache)
        blocked_words_list = await self._get_active_blocked_words()
        
        found_words = []
        max_severity = SeverityLevel.LOW
        
        for blocked_word in blocked_words_list:
            word_lower = blocked_word.word.lower()
            
            # Buscar palabra exacta (word boundary)
            pattern = rf'\b{re.escape(word_lower)}\b'
            if re.search(pattern, text, re.IGNORECASE):
                found_words.append(blocked_word.word)
                
                # Actualizar severidad máxima
                if self._compare_severity(blocked_word.severity, max_severity) > 0:
                    max_severity = blocked_word.severity
            
            # Si tiene patrón regex personalizado, usarlo
            elif blocked_word.pattern:
                try:
                    if re.search(blocked_word.pattern, text, re.IGNORECASE):
                        found_words.append(blocked_word.word)
                        if self._compare_severity(blocked_word.severity, max_severity) > 0:
                            max_severity = blocked_word.severity
                except re.error:
                    pass  # Ignorar patrones regex inválidos
        
        # Determinar si es válido
        is_valid = len(found_words) == 0
        
        # Generar texto censurado si se encontraron palabras
        suggested_text = None
        if not is_valid:
            suggested_text = self._censor_text(validation_request.text, found_words)
        
        # Mensaje descriptivo
        message = None
        if not is_valid:
            if max_severity == SeverityLevel.CRITICAL:
                message = "Este contenido viola gravemente nuestras normas y no puede ser publicado."
            elif max_severity == SeverityLevel.HIGH:
                message = "Este contenido contiene palabras prohibidas y no puede ser publicado."
            elif max_severity == SeverityLevel.MEDIUM:
                message = "Este contenido podría ser inapropiado. Por favor, revísalo."
            else:
                message = "Advertencia: este contenido podría resultar ofensivo."
        
        return ContentValidationResponse(
            is_valid=is_valid,
            blocked_words=found_words,
            severity=max_severity,
            message=message,
            suggested_text=suggested_text
        )
    
    async def get_blocked_words(
        self,
        category: Optional[WordCategory] = None,
        severity: Optional[SeverityLevel] = None,
        language: str = "es",
        is_active: bool = True
    ) -> List[BlockedWordResponse]:
        """Obtener lista de palabras bloqueadas (admin only)"""
        stmt = select(BlockedWord).where(BlockedWord.language == language)
        
        if category:
            stmt = stmt.where(BlockedWord.category == category)
        if severity:
            stmt = stmt.where(BlockedWord.severity == severity)
        if is_active is not None:
            stmt = stmt.where(BlockedWord.is_active == is_active)
        
        stmt = stmt.order_by(BlockedWord.severity.desc(), BlockedWord.word.asc())
        
        result = await self.db.execute(stmt)
        words = result.scalars().all()
        
        return [BlockedWordResponse.model_validate(w) for w in words]
    
    async def add_blocked_word(
        self, 
        word_data: BlockedWordCreate,
        admin_id: int
    ) -> BlockedWordResponse:
        """Agregar palabra bloqueada (admin only)"""
        # Verificar duplicado
        existing_stmt = select(BlockedWord).where(
            and_(
                BlockedWord.word == word_data.word.lower(),
                BlockedWord.language == word_data.language
            )
        )
        existing_result = await self.db.execute(existing_stmt)
        existing_word = existing_result.scalar_one_or_none()
        
        if existing_word:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This word is already blocked"
            )
        
        # Crear palabra bloqueada
        blocked_word = BlockedWord(
            word=word_data.word.lower(),
            pattern=word_data.pattern,
            category=word_data.category,
            severity=word_data.severity,
            language=word_data.language,
            created_by=admin_id,
            is_active=True
        )
        
        self.db.add(blocked_word)
        await self.db.commit()
        await self.db.refresh(blocked_word)
        
        # Invalidar cache
        self._words_cache = None
        
        return BlockedWordResponse.model_validate(blocked_word)
    
    async def update_blocked_word(
        self,
        word_id: int,
        word_update: BlockedWordUpdate
    ) -> Optional[BlockedWordResponse]:
        """Actualizar palabra bloqueada (admin only)"""
        stmt = select(BlockedWord).where(BlockedWord.id == word_id)
        result = await self.db.execute(stmt)
        word = result.scalar_one_or_none()
        
        if not word:
            return None
        
        # Actualizar campos
        if word_update.is_active is not None:
            word.is_active = word_update.is_active
        if word_update.category is not None:
            word.category = word_update.category
        if word_update.severity is not None:
            word.severity = word_update.severity
        
        await self.db.commit()
        await self.db.refresh(word)
        
        # Invalidar cache
        self._words_cache = None
        
        return BlockedWordResponse.model_validate(word)
    
    async def delete_blocked_word(self, word_id: int) -> bool:
        """Eliminar palabra bloqueada (admin only)"""
        stmt = select(BlockedWord).where(BlockedWord.id == word_id)
        result = await self.db.execute(stmt)
        word = result.scalar_one_or_none()
        
        if not word:
            return False
        
        await self.db.delete(word)
        await self.db.commit()
        
        # Invalidar cache
        self._words_cache = None
        
        return True
    
    # ─── Métodos privados ─────────────────────────────────────────────────────
    
    async def _get_active_blocked_words(self) -> List[BlockedWord]:
        """Obtener palabras bloqueadas activas (con cache simple)"""
        if self._words_cache is not None:
            return self._words_cache
        
        stmt = select(BlockedWord).where(BlockedWord.is_active == True)
        result = await self.db.execute(stmt)
        words = result.scalars().all()
        
        self._words_cache = list(words)
        return self._words_cache
    
    def _censor_text(self, text: str, blocked_words: List[str]) -> str:
        """Censurar palabras encontradas reemplazándolas con asteriscos"""
        censored = text
        for word in blocked_words:
            pattern = rf'\b{re.escape(word)}\b'
            censored = re.sub(pattern, '***', censored, flags=re.IGNORECASE)
        return censored
    
    def _compare_severity(self, sev1: SeverityLevel, sev2: SeverityLevel) -> int:
        """Comparar severidades (-1: sev1 < sev2, 0: igual, 1: sev1 > sev2)"""
        severity_order = {
            SeverityLevel.LOW: 1,
            SeverityLevel.MEDIUM: 2,
            SeverityLevel.HIGH: 3,
            SeverityLevel.CRITICAL: 4
        }
        
        val1 = severity_order.get(sev1, 0)
        val2 = severity_order.get(sev2, 0)
        
        if val1 < val2:
            return -1
        elif val1 > val2:
            return 1
        else:
            return 0
