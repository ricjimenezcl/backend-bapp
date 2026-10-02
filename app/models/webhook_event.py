"""
WebhookEvent Model - Auditoría e idempotencia de webhooks entrantes
(Mercado Pago, RevenueCat, Google Play, Apple IAP, etc.)

La tabla `webhook_events` ya existía desde la migración 011 pero no tenía
un modelo ORM asociado. Se agrega ahora para el webhook de RevenueCat.
"""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class WebhookEvent(Base):
    """Registro de eventos de webhook recibidos, para idempotencia y auditoría"""
    __tablename__ = "webhook_events"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)  # 'mercadopago' | 'revenuecat' | 'google_play' | 'apple_iap'
    event_type = Column(String(64))
    received_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    processed = Column(Boolean, default=False, nullable=False)
    processed_at = Column(TIMESTAMP(timezone=True))
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    payload = Column(JSON)
    error_message = Column(Text)

    transaction = relationship("Transaction", foreign_keys=[transaction_id])

    def __repr__(self):
        return f"<WebhookEvent {self.provider}:{self.event_id} processed={self.processed}>"
