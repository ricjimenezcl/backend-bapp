from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.core.database import get_db_async
from app.models.provider import ServiceProvider
from app.models.user import User, UserStatus
from app.models.booking import Booking
from app.models.payment import Payment
from app.dependencies import get_current_user

router = APIRouter()

@router.get("/pending-validations")
async def get_pending_validations(
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_user)
):
    """Obtener proveedores pendientes de validación"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = await db.execute(
        select(ServiceProvider)
        .where(ServiceProvider.validation_status == "pending")
        .join(User, ServiceProvider.user_id == User.id)
    )
    providers = result.scalars().all()
    
    return providers

@router.post("/validate-provider/{user_id}")
async def validate_provider(
    user_id: int,
    approved: bool,
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_user)
):
    """Aprobar o rechazar un proveedor"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = await db.execute(
        select(ServiceProvider).where(ServiceProvider.user_id == user_id)
    )
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    if approved:
        provider.validation_status = "approved"
        
        # Activar el usuario
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            user.status = UserStatus.ACTIVE
    else:
        provider.validation_status = "rejected"
    
    await db.commit()
    
    return {"message": f"Provider {'approved' if approved else 'rejected'} successfully"}

@router.get("/users")
async def get_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_user)
):
    """Obtener todos los usuarios (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = await db.execute(
        select(User).offset(skip).limit(limit)
    )
    users = result.scalars().all()
    
    return users

@router.get("/transactions")
async def get_transactions(
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_user)
):
    """Obtener todas las transacciones (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = await db.execute(
        select(Payment)
        .join(Booking, Payment.booking_id == Booking.id)
    )
    transactions = result.scalars().all()
    
    return transactions

@router.post("/reports/generate")
async def generate_reports(
    report_type: str,
    start_date: str = None,
    end_date: str = None,
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_user)
):
    """Generar reportes administrativos"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Implementar generación de reportes
    report_data = {
        "type": report_type,
        "period": f"{start_date} to {end_date}",
        "data": {}
    }
    
    return report_data
