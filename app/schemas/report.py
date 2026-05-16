"""
Schemas Pydantic para Reports (Reportes de contenido)
Sistema de moderación y reportes de contenido inapropiado
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


# ─── Enums ────────────────────────────────────────────────────────────────────

class ReportType(str, Enum):
    """Tipos de reporte"""
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
    """Tipos de entidad reportable"""
    USER = "USER"
    REVIEW = "REVIEW"
    SERVICE = "SERVICE"
    CHAT_MESSAGE = "CHAT_MESSAGE"


class ModerationAction(str, Enum):
    """Acciones de moderación"""
    NO_ACTION = "NO_ACTION"
    WARNING = "WARNING"
    CONTENT_REMOVED = "CONTENT_REMOVED"
    TEMPORARY_SUSPENSION = "TEMPORARY_SUSPENSION"
    PERMANENT_BAN = "PERMANENT_BAN"
    ACCOUNT_DELETED = "ACCOUNT_DELETED"


# ─── Request ──────────────────────────────────────────────────────────────────

class ReportCreate(BaseModel):
    """Request para crear un reporte"""
    report_type: ReportType = Field(..., description="Tipo de reporte")
    reported_entity_type: ReportedEntityType = Field(..., description="Tipo de entidad reportada")
    reported_entity_id: int = Field(..., description="ID de la entidad reportada")
    reported_user_id: Optional[int] = Field(None, description="ID del usuario reportado (si aplica)")
    description: Optional[str] = Field(None, max_length=1000, description="Descripción del problema")
    evidence_urls: Optional[List[str]] = Field(None, description="URLs de evidencia (capturas, etc.)")


class ReportReview(BaseModel):
    """Request para revisar un reporte (admin/moderador)"""
    status: ReportStatus = Field(..., description="Nuevo estado del reporte")
    review_notes: Optional[str] = Field(None, max_length=1000, description="Notas de revisión")
    action_taken: Optional[ModerationAction] = Field(None, description="Acción tomada")
    action_details: Optional[str] = Field(None, max_length=500, description="Detalles de la acción")


# ─── Response ─────────────────────────────────────────────────────────────────

class ReportResponse(BaseModel):
    """Response de un reporte"""
    id: int
    report_type: ReportType
    reported_entity_type: ReportedEntityType
    reported_entity_id: int
    reporter_id: int
    reported_user_id: Optional[int]
    description: Optional[str]
    evidence_urls: Optional[List[str]]
    status: ReportStatus
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    review_notes: Optional[str]
    action_taken: Optional[ModerationAction]
    action_details: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Campos enriquecidos (opcional, agregados por servicio)
    reporter_name: Optional[str] = None
    reported_user_name: Optional[str] = None
    reviewer_name: Optional[str] = None

    model_config = {"from_attributes": True}


class ReportListResponse(BaseModel):
    """Response para lista de reportes"""
    reports: List[ReportResponse]
    total: int
    page: int
    page_size: int


class ReportStatsResponse(BaseModel):
    """Response para estadísticas de reportes"""
    total_reports: int
    pending_reports: int
    resolved_reports: int
    dismissed_reports: int
    escalated_reports: int
    reports_by_type: dict
    reports_last_30_days: int
