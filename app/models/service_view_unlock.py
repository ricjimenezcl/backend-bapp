"""
ServiceViewUnlock — acceso premium del proveedor a la lista de clientes que vieron sus servicios.
Duración: 7 días. Precio: $1.990 CLP.
"""
from sqlalchemy import Column, Integer, String, DECIMAL, TIMESTAMP, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ServiceViewUnlock(Base):
    __tablename__ = "provider_service_view_unlocks"
    __table_args__ = {"extend_existing": True}

    id                  = Column(Integer, primary_key=True, index=True)
    provider_id         = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_reference   = Column(String(64), unique=True, nullable=False, index=True)
    amount              = Column(DECIMAL(10, 2), nullable=False, default=1990.00)
    currency            = Column(String(3), default="CLP")
    status              = Column(
        Enum("pending", "active", "expired", "failed", name="svu_status", native_enum=False),
        default="pending",
        nullable=False,
        index=True,
    )
    unlocked_at         = Column(TIMESTAMP, nullable=True)
    expires_at          = Column(TIMESTAMP, nullable=True, index=True)
    created_at          = Column(TIMESTAMP, server_default=func.now())
    updated_at          = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    provider = relationship("Provider", foreign_keys=[provider_id])
