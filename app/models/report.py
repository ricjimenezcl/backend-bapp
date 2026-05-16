# app/models/report.py
"""
Report Model - Sistema de Reportes de Contenido
Permite a usuarios reportar contenido inapropiado (perfiles, reseñas, servicios, mensajes)
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum
from app.core.database import Base


class ReportType(str, Enum):
    """Tipos de reporte disponibles"""
    INAPPROPRIATE_CONTENT = "INAPPROPRIATE_CONTENT"
    FAKE_PROFILE = "FAKE_PROFILE"
    HARASSMENT = "HARASSMENT"
    SPAM = "SPAM"
    FRAUD = "FRAUD"
    HATE_SPEECH = "HATE_SPEECH"
    VIOLENCE = "VIOLENCE"
    NUDITY = "NUDITY"
    INTELLECTUAL_PROPERTY = "INTELLECTUAL_PROPERTY"
    OTHER = "OTHER"


class ReportStatus(str, Enum):
    """Estados del reporte"""
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"


class ReportedEntityType(str, Enum):
    """Tipos de entidad que se pueden reportar"""
    USER = "USER"
    REVIEW = "REVIEW"
    SERVICE = "SERVICE"
    CHAT_MESSAGE = "CHAT_MESSAGE"


class ModerationAction(str, Enum):
    """Acciones tomadas por moderación"""
    NO_ACTION = "NO_ACTION"
    WARNING = "WARNING"
    CONTENT_REMOVED = "CONTENT_REMOVED"
    TEMPORARY_SUSPENSION = "TEMPORARY_SUSPENSION"
    PERMANENT_BAN = "PERMANENT_BAN"
    ACCOUNT_DELETED = "ACCOUNT_DELETED"


class Report(Base):
    """
    Modelo de Reporte
    Almacena reportes de contenido inapropiado
    """
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    
    # Tipo de reporte
    report_type = Column(SQLEnum(ReportType), nullable=False, index=True)
    
    # Entidad reportada (genérico para cualquier tipo)
    reported_entity_type = Column(SQLEnum(ReportedEntityType), nullable=False, index=True)
    reported_entity_id = Column(Integer, nullable=False, index=True)
    
    # Usuario reportante
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Usuario reportado (si aplica - para USER, o dueño del contenido)
    reported_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    # Detalles del reporte
    description = Column(Text, nullable=True)
    evidence_urls = Column(JSON, nullable=True)  # URLs de capturas de pantalla, etc.
    
    # Estado del reporte
    status = Column(SQLEnum(ReportStatus), default=ReportStatus.PENDING, nullable=False, index=True)
    
    # Revisión (moderador)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    
    # Acción tomada
    action_taken = Column(SQLEnum(ModerationAction), nullable=True)
    action_details = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    reporter = relationship("User", foreign_keys=[reporter_id], back_populates="reports_made")
    reported_user = relationship("User", foreign_keys=[reported_user_id], back_populates="reports_received")
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self):
        return f"<Report(id={self.id}, type={self.report_type}, status={self.status})>"

    @property
    def is_pending(self) -> bool:
        """Verifica si el reporte está pendiente"""
        return self.status == ReportStatus.PENDING

    @property
    def is_resolved(self) -> bool:
        """Verifica si el reporte fue resuelto"""
        return self.status == ReportStatus.RESOLVED

    @property
    def requires_action(self) -> bool:
        """Verifica si requiere acción inmediata"""
        high_priority_types = {
            ReportType.VIOLENCE,
            ReportType.HATE_SPEECH,
            ReportType.NUDITY,
            ReportType.FRAUD
        }
        return self.report_type in high_priority_types and self.is_pending
