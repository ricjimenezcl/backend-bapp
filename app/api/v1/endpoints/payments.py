from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any

from app.core.database import get_db_async
from app.models.booking import Booking
from app.models.payment import Payment
from app.models.user import User
from app.services.payment_service import PaymentService
from app.dependencies import get_current_user

router = APIRouter()

@router.post("/create-intent")
async def create_payment_intent(
    booking_id: int,
    payment_method: str,
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_user)
):
    """Crear intento de pago para una reserva"""
    
    # Verificar que la reserva existe y pertenece al usuario
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    if booking.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this booking")
    
    # Crear intento de pago
    payment_service = PaymentService(db)
    payment_intent = await payment_service.create_payment_intent(
        booking_data={
            'id': booking.id,
            'service_name': booking.service_category,
            'amount': float(booking.price) if booking.price else 0.0
        },
        payment_method=payment_method
    )
    
    # Crear registro de pago
    payment = Payment(
        booking_id=booking_id,
        amount=booking.price,
        payment_method=payment_method,
        status="pending"
    )
    
    db.add(payment)
    await db.commit()
    
    return payment_intent

@router.post("/confirm")
async def confirm_payment(
    payment_intent_id: str,
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_user)
):
    """Confirmar un pago completado"""
    payment_service = PaymentService(db)
    await payment_service.confirm_payment(payment_intent_id)
    
    # Actualizar estado del pago en la base de datos
    result = await db.execute(
        select(Payment).where(Payment.transaction_id == payment_intent_id)
    )
    payment = result.scalar_one_or_none()
    
    if payment:
        payment.status = "completed"
        await db.commit()
    
    return result

@router.post("/webhook")
async def payment_webhook(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_async)
):
    """Webhook para recibir notificaciones de pago"""
    payment_service = PaymentService(db)
    
    # Procesar webhook en segundo plano
    background_tasks.add_task(
        payment_service.handle_webhook,
        payload
    )
    
    return {"status": "received"}
