"""
Schemas Pydantic para Content Moderation (Moderación de contenido)
Validación de texto contra palabras prohibidas
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────────────

class WordCategory(str, Enum):
    """Categorías de palabras bloqueadas"""
    SEXUAL = "SEXUAL"
    DRUGS = "DRUGS"
    VIOLENCE = "VIOLENCE"
    HATE = "HATE"
    FRAUD = "FRAUD"
    SPAM = "SPAM"


class SeverityLevel(str, Enum):
    """Nivel de severidad"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ─── Request ──────────────────────────────────────────────────────────────────

class ContentValidationRequest(BaseModel):
    """Request para validar contenido"""
    text: str = Field(..., min_length=1, max_length=5000, description="Texto a validar")
    context: Optional[str] = Field(None, description="Contexto del texto (bio, review, chat, etc.)")


class BlockedWordCreate(BaseModel):
    """Request para crear una palabra bloqueada (admin only)"""
    word: str = Field(..., min_length=1, max_length=255, description="Palabra o frase a bloquear")
    pattern: Optional[str] = Field(None, max_length=500, description="Patrón regex opcional")
    category: WordCategory = Field(..., description="Categoría de la palabra")
    severity: SeverityLevel = Field(..., description="Nivel de severidad")
    language: str = Field("es", min_length=2, max_length=2, description="Código de idioma ISO 639-1")


class BlockedWordUpdate(BaseModel):
    """Request para actualizar una palabra bloqueada (admin only)"""
    is_active: Optional[bool] = Field(None, description="Activar/desactivar palabra")
    category: Optional[WordCategory] = Field(None, description="Cambiar categoría")
    severity: Optional[SeverityLevel] = Field(None, description="Cambiar severidad")


# ─── Response ─────────────────────────────────────────────────────────────────

class ContentValidationResponse(BaseModel):
    """Response de validación de contenido"""
    is_valid: bool = Field(..., description="Si el contenido es válido")
    blocked_words: List[str] = Field(default_factory=list, description="Palabras bloqueadas encontradas")
    severity: SeverityLevel = Field(..., description="Severidad máxima encontrada")
    message: Optional[str] = Field(None, description="Mensaje descriptivo")
    suggested_text: Optional[str] = Field(None, description="Texto sugerido con censura")


class BlockedWordResponse(BaseModel):
    """Response de palabra bloqueada"""
    id: int
    word: str
    pattern: Optional[str]
    category: WordCategory
    severity: SeverityLevel
    language: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BlockedWordListResponse(BaseModel):
    """Response para lista de palabras bloqueadas"""
    words: List[BlockedWordResponse]
    total: int
    page: int
    page_size: int
