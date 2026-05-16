# app/models/moderation_history.py
"""
Moderation History Model - Historial de acciones de moderación
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum
from app.core.database import Base


class ModerationType(str, Enum):
    """Tipos de acción de moderación"""
    USER_SUSPENDED = "USER_SUSPENDED"
    USER_BANNED = "USER_BANNED"
    USER_WARNING = "USER_WARNING"
    USER_REINSTATED = "USER_REINSTATED"
    CONTENT_REMOVED = "CONTENT_REMOVED"
    CONTENT_APPROVED = "CONTENT_APPROVED"
    REPORT_RESOLVED = "REPORT_RESOLVED"
    REPORT_DISMISSED = "REPORT_DISMISSED"


class ModerationHistory(Base):
    """
    Modelo de Historial de Moderación
    Registra todas las acciones de moderación tomadas
    """
    __tablename__ = "moderation_history"

    id = Column(Integer, primary_key=True, index=True)
    
    # Tipo de acción
    moderation_type = Column(SQLEnum(ModerationType), nullable=False, index=True)
    
    # Usuario afectado
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Moderador que tomó la acción
    moderator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Reporte relacionado (si aplica)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=True)
    
    # Razón y detalles
    reason = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)  # Información adicional estructurada
    
    # Duración (para suspensiones temporales, en días)
    duration_days = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="moderation_history")
    moderator = relationship("User", foreign_keys=[moderator_id])
    report = relationship("Report")

    def __repr__(self):
        return f"<ModerationHistory(id={self.id}, type={self.moderation_type}, user_id={self.user_id})>"

    @property
    def is_suspension(self) -> bool:
        """Verifica si es una suspensión"""
        return self.moderation_type == ModerationType.USER_SUSPENDED

    @property
    def is_ban(self) -> bool:
        """Verifica si es un ban permanente"""
        return self.moderation_type == ModerationType.USER_BANNED
