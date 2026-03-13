"""
Provider Service Slot Model - Gestión de slots de servicios para proveedores
"""
from sqlalchemy import Column, Integer, Boolean, TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ProviderServiceSlot(Base):
    """
    Slots de servicios para proveedores
    - Slots 1 y 2: Gratuitos permanentes (is_free=True)
    - Slots 3+: Requieren pago con vigencia de 30 días
    """
    __tablename__ = "provider_service_slots"
    __table_args__ = (
        UniqueConstraint('provider_id', 'slot_number', name='uq_provider_slot_number'),
        {'extend_existing': True}
    )

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_number = Column(Integer, nullable=False)  # 1, 2, 3, 4, etc.
    is_free = Column(Boolean, default=True, nullable=False)  # TRUE para slots 1 y 2
    service_provider_id = Column(Integer, ForeignKey("service_providers.id", ondelete="SET NULL"), nullable=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    # Control de vigencia
    activated_at = Column(TIMESTAMP)
    expires_at = Column(TIMESTAMP, index=True)
    is_active = Column(Boolean, default=False, nullable=False, index=True)

    # Auditoría
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    # Relationships
    provider = relationship("Provider", foreign_keys=[provider_id])
    service_provider = relationship("ServiceProvider", foreign_keys=[service_provider_id])
    transaction = relationship("Transaction", foreign_keys=[transaction_id])

    def __repr__(self):
        return f"<ProviderServiceSlot Provider:{self.provider_id} Slot:{self.slot_number} Active:{self.is_active}>"
