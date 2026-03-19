"""
Premium Access Endpoints
Handles premium subscription activation and status
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_async
from app.core.config import settings
from app.dependencies import get_current_user
from app.models.user import User
from app.services.premium_service import PremiumService

router = APIRouter(tags=["premium"])


@router.post("/activate")
async def activate_premium(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Activa acceso premium por 7 días — SOLO para entornos no productivos.
    En producción usar POST /payments/transbank/create o /payments/verify/*
    """
    if settings.ENVIRONMENT != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este endpoint solo está disponible en entorno de desarrollo"
        )
    premium_service = PremiumService(db)
    result = await premium_service.activate_premium(current_user.id)
    return result


@router.get("/status")
async def get_premium_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtiene el estado de la suscripción premium del usuario actual
    
    Returns:
        {
            "has_premium": bool,
            "is_active": bool,
            "activated_at": str | null,
            "expires_at": str | null,
            "days_remaining": int
        }
    """
    premium_service = PremiumService(db)
    status_data = await premium_service.get_premium_status(current_user.id)
    return status_data
