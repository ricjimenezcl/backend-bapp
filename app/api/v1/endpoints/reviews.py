from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.review import CreateReviewRequest, ReviewResponse
from app.services.review_service import ReviewService

router = APIRouter()

@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    review_in: CreateReviewRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Crear una reseña para un servicio completado. (Solo Clientes)
    """
    if current_user.role != "CLIENT":
        raise HTTPException(status_code=403, detail="Only clients can leave reviews")

    service = ReviewService(db)
    return await service.create_review(current_user.id, review_in)

@router.get("/providers/{provider_id}/reviews", response_model=List[ReviewResponse])
async def get_provider_reviews(
    provider_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener reseñas de un proveedor de servicios (Público)
    """
    service = ReviewService(db)
    return await service.get_provider_reviews(provider_id)
