from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class Service(Base):
    __tablename__ = "services"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    icon = Column(String(255))
    subcategory_id = Column(Integer, ForeignKey("subcategories.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    # lazy='joined' para que la property de compatibilidad ServiceProvider.service_category
    # pueda acceder a subcategory sin necesidad de lazy-load síncrono en contexto async.
    subcategory = relationship("Subcategory", back_populates="services", lazy='joined')
    service_providers = relationship("ServiceProvider", back_populates="service")
