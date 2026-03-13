"""
Product Model - Catálogo de productos monetizables
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DECIMAL, TIMESTAMP, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from enum import Enum as PyEnum


class TargetRole(str, PyEnum):
    """Roles objetivo para productos"""
    CLIENT = "CLIENT"
    PROVIDER = "PROVIDER"
    ALL = "ALL"


class Product(Base):
    """
    Productos del sistema (Premium Access, Service Slots, etc.)
    """
    __tablename__ = "products"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    target_role = Column(String(20), nullable=False)  # 'CLIENT' | 'PROVIDER' | 'ALL'
    duration_days = Column(Integer, nullable=False)
    price_usd = Column(DECIMAL(10, 2), nullable=False)
    price_clp = Column(DECIMAL(10, 2), nullable=False)
    free_limit = Column(Integer, default=0)  # Para proveedores: límite gratuito (ej: 2 servicios gratis)
    is_active = Column(Boolean, default=True, nullable=False)
    product_metadata = Column(JSON)  # Configuración adicional flexible
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    # Relationships
    platform_products = relationship("PlatformProduct", back_populates="product", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="product")

    def __repr__(self):
        return f"<Product {self.sku}: {self.name}>"
