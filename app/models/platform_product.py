"""
Platform Product Model - Mapeo de productos por plataforma
"""
from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from enum import Enum as PyEnum


class Platform(str, PyEnum):
    """Plataformas soportadas"""
    GOOGLE_PLAY = "google_play"
    APPLE_IAP = "apple_iap"
    WEB = "web"


class PlatformProduct(Base):
    """
    Mapeo de productos internos a IDs de productos específicos de cada plataforma
    (Google Play, Apple IAP, Web)
    """
    __tablename__ = "platform_products"
    __table_args__ = (
        UniqueConstraint('product_id', 'platform', name='uq_product_platform'),
        {'extend_existing': True}
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(20), nullable=False, index=True)  # 'google_play' | 'apple_iap' | 'web'
    platform_product_id = Column(String(255), nullable=False)  # SKU de la plataforma externa
    platform_price = Column(String(50))  # Precio en formato de plataforma
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # Relationships
    product = relationship("Product", back_populates="platform_products")

    def __repr__(self):
        return f"<PlatformProduct {self.platform}: {self.platform_product_id}>"
