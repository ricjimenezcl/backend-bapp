"""
Schemas Pydantic para Pagos (Payment)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field


# ============================================================================
# ENUMS
# ============================================================================

class PaymentStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentMethodEnum(str, Enum):
    CARD = "CARD"
    TRANSFER = "TRANSFER"
    CASH = "CASH"
    WALLET = "WALLET"


# ============================================================================
# PAYMENT SCHEMAS
# ============================================================================

class InitiatePaymentRequest(BaseModel):
    """Request para iniciar un pago"""
    booking_id: str = Field(..., description="UUID de la reserva")
    amount: Decimal = Field(..., ge=0, description="Monto a pagar")
    payment_method: PaymentMethodEnum = Field(..., description="Método de pago")
    payment_gateway: Optional[str] = Field(None, description="Gateway de pago (STRIPE, MERCADO_PAGO)")
    
    class Config:
        example = {
            "booking_id": "123e4567-e89b-12d3-a456-426614174000",
            "amount": "50000.00",
            "payment_method": "CARD",
            "payment_gateway": "STRIPE"
        }


class ConfirmPaymentRequest(BaseModel):
    """Request para confirmar un pago"""
    transaction_id: str = Field(..., description="ID de la transacción desde el gateway")
    
    class Config:
        example = {
            "transaction_id": "ch_1234567890abcdef"
        }


class ProcessRefundRequest(BaseModel):
    """Request para procesar un reembolso"""
    reason: str = Field(..., description="Razón del reembolso")
    refund_percentage: int = Field(default=100, ge=0, le=100, description="Porcentaje a reembolsar")
    
    class Config:
        example = {
            "reason": "Servicio no completado",
            "refund_percentage": 100
        }


class PaymentResponse(BaseModel):
    """Response de un pago"""
    id: str
    booking_id: str
    amount: Decimal
    currency: str
    payment_method: PaymentMethodEnum
    transaction_id: Optional[str]
    payment_gateway: Optional[str]
    status: PaymentStatusEnum
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime]
    error_message: Optional[str]
    refund_amount: Optional[Decimal]
    refund_reason: Optional[str]
    refunded_at: Optional[datetime]
    
    class Config:
        from_attributes = True
        example = {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "booking_id": "223e4567-e89b-12d3-a456-426614174000",
            "amount": "50000.00",
            "currency": "CLP",
            "payment_method": "CARD",
            "transaction_id": "ch_1234567890abcdef",
            "payment_gateway": "STRIPE",
            "status": "COMPLETED",
            "created_at": "2026-01-27T10:00:00",
            "updated_at": "2026-01-27T10:01:00",
            "processed_at": "2026-01-27T10:01:00",
            "error_message": None,
            "refund_amount": None,
            "refund_reason": None,
            "refunded_at": None
        }


class PaymentListResponse(BaseModel):
    """Response para listar pagos"""
    total: int
    page: int
    size: int
    items: list[PaymentResponse]
    
    class Config:
        from_attributes = True


# ============================================================================
# WEBHOOK SCHEMAS (desde gateways de pago)
# ============================================================================

class StripeWebhookPayload(BaseModel):
    """Payload de webhook desde Stripe"""
    id: str = Field(..., description="Event ID")
    type: str = Field(..., description="Tipo de evento (charge.succeeded, charge.failed)")
    data: dict = Field(..., description="Datos del evento")
    
    class Config:
        example = {
            "id": "evt_1234567890",
            "type": "charge.succeeded",
            "data": {
                "object": {
                    "id": "ch_1234567890abcdef",
                    "amount": 5000000,
                    "currency": "clp",
                    "status": "succeeded"
                }
            }
        }


class MercadoPagoWebhookPayload(BaseModel):
    """Payload de webhook desde Mercado Pago"""
    id: str = Field(..., description="Notification ID")
    type: str = Field(..., description="Tipo de notificación (payment)")
    data: dict = Field(..., description="Datos de la notificación")
    
    class Config:
        example = {
            "id": "123456789",
            "type": "payment",
            "data": {
                "id": "987654321"
            }
        }
