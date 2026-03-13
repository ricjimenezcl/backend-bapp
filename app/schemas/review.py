"""
Schemas Pydantic para Reviews (Reseñas y calificaciones)
Alineados con el modelo Review real:
  id, booking_id, client_id, provider_id, rating, comment, created_at, updated_at
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


# ─── Request ──────────────────────────────────────────────────────────────────

class CreateReviewRequest(BaseModel):
    """Request para crear una reseña de un booking completado."""
    booking_id: int = Field(..., description="ID de la reserva completada")
    rating: float = Field(..., ge=1.0, le=5.0, description="Calificación 1.0–5.0")
    comment: Optional[str] = Field(None, max_length=500, description="Comentario opcional")


# ─── Response ─────────────────────────────────────────────────────────────────

class ReviewResponse(BaseModel):
    """Response de una reseña."""
    id: int
    booking_id: int
    client_id: int
    provider_id: int
    rating: float
    comment: Optional[str]
    client_name: Optional[str] = None   # Nombre del cliente (enriquecido por el servicio)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
