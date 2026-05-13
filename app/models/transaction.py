"""
Transaction Model - Historial completo de transacciones y pagos
Reemplaza el modelo Payment.py básico con un sistema completo de auditoría
"""
from sqlalchemy import Column, Integer, String, Text, DECIMAL, TIMESTAMP, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from enum import Enum as PyEnum


class TransactionStatus(str, PyEnum):
    """Estados de transacción"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class Transaction(Base):
    """
    Registro completo de todas las transacciones del sistema
    Soporta múltiples plataformas de pago con validación y auditoría
    """
    __tablename__ = "transactions"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    platform = Column(String(20), nullable=False, index=True)  # 'google_play' | 'apple_iap' | 'web'
    amount = Column(DECIMAL(10, 2), nullable=False)
    currency = Column(String(3), default='CLP')
    status = Column(
        Enum(TransactionStatus, values_callable=lambda x: [e.value for e in x], native_enum=False),
        default=TransactionStatus.PENDING,
        nullable=False,
        index=True
    )

    # IDs de transacción por plataforma
    transaction_id = Column(String(255), index=True)  # ID interno único
    platform_transaction_id = Column(String(255), index=True)  # ID de la plataforma externa
    platform_order_id = Column(String(255))  # Order ID adicional
    buy_order = Column(String(255), index=True)
    tbk_token = Column(String(255), index=True)
    authorization_code = Column(String(50))
    product_type = Column(String(50), index=True)

    # Validación de compra
    purchase_token = Column(Text)  # Token de Google Play o Apple
    receipt_data = Column(Text)  # Receipt completo (JSON serializado)
    validated_at = Column(TIMESTAMP)
    validation_response = Column(Text)  # Respuesta de validación de la plataforma

    # Metadata de seguridad
    ip_address = Column(String(50))
    user_agent = Column(Text)
    device_info = Column(JSON)

    # Activación del beneficio
    activated_at = Column(TIMESTAMP)
    paid_at = Column(TIMESTAMP)
    expires_at = Column(TIMESTAMP, index=True)
    benefit_metadata = Column(JSON)  # Información del beneficio activado

    # Auditoría y timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    refunded_at = Column(TIMESTAMP)
    refund_reason = Column(Text)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    product = relationship("Product", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction {self.id}: {self.status} - {self.amount} {self.currency}>"
