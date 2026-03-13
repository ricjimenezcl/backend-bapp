from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum, Text, ForeignKey, DECIMAL
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    amount = Column(DECIMAL(10, 2), nullable=False)
    payment_method = Column(String(50), nullable=False)
    transaction_id = Column(String(255))
    status = Column(Enum("pending", "completed", "failed", "refunded", name="paymentstatus"), default="pending")
    sii_receipt_url = Column(String(500))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    booking = relationship("Booking", back_populates="payments")