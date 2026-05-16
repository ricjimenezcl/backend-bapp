# app/models/blocked_word.py
"""
Blocked Word Model - Lista de palabras prohibidas para moderación de contenido
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.sql import func
from enum import Enum
from app.core.database import Base


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


class BlockedWord(Base):
    """
    Modelo de Palabra Bloqueada
    Almacena palabras y patrones prohibidos para validación de contenido
    """
    __tablename__ = "blocked_words"

    id = Column(Integer, primary_key=True, index=True)
    
    # Palabra o frase bloqueada
    word = Column(String(255), nullable=False, unique=True, index=True)
    
    # Patrón regex opcional (para variaciones)
    pattern = Column(String(500), nullable=True)
    
    # Categoría y severidad
    category = Column(SQLEnum(WordCategory), nullable=False, index=True)
    severity = Column(SQLEnum(SeverityLevel), nullable=False, index=True)
    
    # Idioma (ISO 639-1: es, en, pt, etc.)
    language = Column(String(2), default="es", nullable=False, index=True)
    
    # Estado
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    created_by = Column(Integer, nullable=True)  # Admin que agregó la palabra
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<BlockedWord(id={self.id}, word={self.word}, category={self.category}, severity={self.severity})>"

    @property
    def is_critical(self) -> bool:
        """Verifica si es de severidad crítica"""
        return self.severity == SeverityLevel.CRITICAL

    @property
    def should_auto_block(self) -> bool:
        """Verifica si debe bloquear automáticamente"""
        return self.severity in {SeverityLevel.CRITICAL, SeverityLevel.HIGH}
