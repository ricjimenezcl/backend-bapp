from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class ServiceCategory(Base):
    __tablename__ = "service_categories"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    icon = Column(String(500))
    parent_category = Column(String(100))
    is_active = Column(Boolean, default=True)
    main_category_id = Column(Integer, ForeignKey("main_categories.id"))
    created_at = Column(DateTime, default=func.now())

    # Relationships
    # NOTA: ya no existe back-reference a ServiceProvider (que ahora apunta a Service,
    # tabla "services", vía la FK real service_providers_service_id_fkey).
    main_category = relationship("MainCategory", back_populates="service_categories")

class MainCategory(Base):
    __tablename__ = "main_categories"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    icon = Column(String(500))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    service_categories = relationship("ServiceCategory", back_populates="main_category")
    subcategories = relationship("Subcategory", back_populates="main_category")