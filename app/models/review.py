# app/models/review.py
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, DECIMAL
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, unique=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # ¡ESTA COLUMNA SÍ EXISTE!
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False, index=True)  # ✅ OPCIÓN B: provider_id = providers.id
    rating = Column(DECIMAL(2, 1), nullable=False)  # 1.0 to 5.0
    comment = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    booking = relationship("Booking", back_populates="reviews")
    client = relationship("User", foreign_keys=[client_id])
    provider = relationship("Provider", back_populates="reviews", foreign_keys=[provider_id], overlaps="reviews")

    def __repr__(self):
        return f"<Review(id={self.id}, rating={self.rating})>"