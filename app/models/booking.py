# Constantes globales para claves foráneas y opciones de cascada
USERS_ID_FK = "users.id"
BOOKINGS_ID_FK = "bookings.id"
CASCADE_OPTION = "CASCADE"
ALL_DELETE_ORPHAN = "all, delete-orphan"
SET_NULL_OPTION = "SET NULL"
"""
Modelos SQLAlchemy para el sistema de reservas (Booking System)
Incluye: Booking, BookingStatusHistory, Payment, Review, BookingCancellation, ServiceAvailability
"""

from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, 
    Boolean, Numeric, Text, Date, Time,
    UniqueConstraint, Index, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


# ============================================================================
# ENUMS (ahora como constantes de string para compatibilidad PostgreSQL)
# ============================================================================

class BookingStatus:
    """Estados posibles de una reserva"""
    PENDING     = "PENDING"       # Pendiente confirmación del proveedor
    APPROVED    = "APPROVED"      # Aprobada por el proveedor
    REJECTED    = "REJECTED"      # Rechazada por el proveedor
    COMPLETED   = "COMPLETED"     # Completada
    # Legacy — mantener para compatibilidad con datos históricos
    CONFIRMED   = "CONFIRMED"     # deprecated → usar APPROVED
    IN_PROGRESS = "IN_PROGRESS"   # deprecated → usar APPROVED
    CANCELLED   = "CANCELLED"     # deprecated → usar REJECTED
    NOSHOW      = "NOSHOW"        # deprecated


class PaymentStatus:
    """Estados posibles de un pago"""
    PENDING = "PENDING"           # Pendiente de procesar
    PROCESSING = "PROCESSING"     # En procesamiento
    COMPLETED = "COMPLETED"       # Completado
    FAILED = "FAILED"            # Falló
    REFUNDED = "REFUNDED"        # Reembolsado


class PaymentMethod:
    """Métodos de pago disponibles"""
    CARD = "CARD"               # Tarjeta
    TRANSFER = "TRANSFER"       # Transferencia
    CASH = "CASH"              # Efectivo
    WALLET = "WALLET"          # Billetera


class CancellationReason:
    """Razones de cancelación"""
    CLIENT_REQUEST = "CLIENT_REQUEST"
    PROVIDER_REQUEST = "PROVIDER_REQUEST"
    ADMIN_REQUEST = "ADMIN_REQUEST"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CLIENT_NO_SHOW = "CLIENT_NO_SHOW"
    OTHER = "OTHER"


class DayOfWeek:
    """Días de la semana (0=Lunes, 6=Domingo)"""
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


# ============================================================================
# MODELO: BOOKING (Reservas)
# ============================================================================

class Booking(Base):
    """Modelo para reservas de servicios"""
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Relaciones
    client_id = Column(Integer, ForeignKey(USERS_ID_FK, ondelete=CASCADE_OPTION), nullable=False)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete=CASCADE_OPTION), nullable=False)  # provider_id = providers.id
    service_id = Column(Integer, ForeignKey("service_categories.id", ondelete=CASCADE_OPTION), nullable=True)  # service_id = service_categories.id
    service_provider_id = Column(Integer, ForeignKey("service_providers.id"), nullable=True, index=True)
    
    # Información de la reserva (compatibilidad con columnas existentes)
    service_category = Column(String(255), nullable=False, default="GENERAL")  # Categoría del servicio
    location_address = Column(String(255), nullable=False, default="")  # Dirección de la reserva
    location_lat = Column(Numeric(10, 8), nullable=True)  # Latitud
    location_lng = Column(Numeric(10, 8), nullable=True)  # Longitud
    
    scheduled_date = Column(Date, nullable=True, index=True)
    scheduled_time = Column(Time, nullable=True)
    duration = Column(Integer, nullable=True)  # en minutos
    description = Column(Text, nullable=True)
    
    # Precio (compatibilidad con columnas 'price' existentes)
    price = Column(Numeric(10, 2), nullable=True)  # Campo legacy
    total_price = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), default="CLP")
    
    # Estado
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    
    # Metadatos
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    reminder_24h_sent_at = Column(DateTime, nullable=True)
    
    # Relaciones con otros modelos
    client = relationship("User", foreign_keys=[client_id], back_populates="bookings_as_client")
    provider = relationship("Provider", foreign_keys=[provider_id], back_populates="bookings")
    service_category_rel = relationship("ServiceCategory", backref="bookings")
    service_provider = relationship("ServiceProvider", back_populates="bookings")
    payments = relationship("Payment", back_populates="booking", cascade=ALL_DELETE_ORPHAN)
    reviews = relationship("Review", back_populates="booking", cascade=ALL_DELETE_ORPHAN)
    status_history = relationship("BookingStatusHistory", back_populates="booking", cascade=ALL_DELETE_ORPHAN)
    cancellation = relationship("BookingCancellation", back_populates="booking", cascade=ALL_DELETE_ORPHAN, uselist=False)
    notes = relationship("BookingNote", back_populates="booking", cascade=ALL_DELETE_ORPHAN)
    
    # Índices
    __table_args__ = (
        UniqueConstraint('provider_id', 'scheduled_date', 'scheduled_time', name='unique_booking_datetime'),
        Index('idx_bookings_client_id', 'client_id'),
        Index('idx_bookings_provider_id', 'provider_id'),
        Index('idx_bookings_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<Booking {self.id} - {self.status}>"


# ============================================================================
# MODELO: BOOKING STATUS HISTORY (Historial de cambios)
# ============================================================================

class BookingStatusHistory(Base):
    """Registra todos los cambios de estado de una reserva"""
    __tablename__ = "booking_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Relación
    booking_id = Column(Integer, ForeignKey(BOOKINGS_ID_FK, ondelete=CASCADE_OPTION), nullable=False, index=True)
    
    # Estados
    previous_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=False)
    
    # Quién realizó el cambio
    changed_by_id = Column(Integer, ForeignKey(USERS_ID_FK, ondelete=SET_NULL_OPTION), nullable=False)
    
    # Razón
    reason = Column(String(50), nullable=True)
    reason_comment = Column(Text, nullable=True)
    
    # Metadatos
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relaciones
    booking = relationship("Booking", back_populates="status_history")
    changed_by = relationship("User")
    
    # Índices
    __table_args__ = (
        Index('idx_booking_status_history_booking_id', 'booking_id'),
        Index('idx_booking_status_history_changed_by_id', 'changed_by_id'),
    )

    def __repr__(self):
        return f"<BookingStatusHistory {self.booking_id} {self.previous_status} → {self.new_status}>"


# ============================================================================




# ============================================================================
# MODELO: BOOKING CANCELLATION (Detalles de cancelaciones)
# ============================================================================

class BookingCancellation(Base):
    """Modelo para registrar detalles de cancelaciones"""
    __tablename__ = "booking_cancellations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Relación
    booking_id = Column(Integer, ForeignKey(BOOKINGS_ID_FK, ondelete=CASCADE_OPTION), nullable=False, unique=True, index=True)

    # Quién canceló
    cancelled_by_id = Column(Integer, ForeignKey(USERS_ID_FK, ondelete=SET_NULL_OPTION), nullable=False)
    
    # Razón
    reason = Column(String(50), nullable=False)
    reason_comment = Column(Text, nullable=True)
    
    # Reembolso
    refund_percentage = Column(Integer, default=100)
    refund_amount = Column(Numeric(10, 2), nullable=True)
    
    # Metadatos
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    processed_at = Column(DateTime, nullable=True)
    
    # Relaciones
    booking = relationship("Booking", back_populates="cancellation")
    cancelled_by = relationship("User")
    
    # Índices
    __table_args__ = (
        Index('idx_booking_cancellations_booking_id', 'booking_id'),
        Index('idx_booking_cancellations_cancelled_by_id', 'cancelled_by_id'),
    )

    def __repr__(self):
        return f"<BookingCancellation {self.booking_id} - {self.reason}>"


# ============================================================================
# MODELO: SERVICE AVAILABILITY (Disponibilidad de servicios)
# ============================================================================

class ServiceAvailability(Base):
    """Horarios disponibles por servicio publicado (service_providers) y día de semana.

    provider_id → providers.id  (FK corregida desde users.id)
    service_id  → service_providers.id  (FK corregida desde services.id)
    """
    __tablename__ = "service_availability"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # FKs corregidas
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete=CASCADE_OPTION), nullable=False, index=True)
    service_id = Column(Integer, ForeignKey("service_providers.id", ondelete=CASCADE_OPTION), nullable=False, index=True)

    # Disponibilidad
    day_of_week = Column(Integer, nullable=False)  # 0=Lunes … 6=Domingo
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    # Información
    is_available = Column(Boolean, default=True)
    timezone = Column(String(50), default="America/Santiago")

    # Metadatos
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones corregidas
    provider = relationship("Provider")
    service_provider = relationship("ServiceProvider")

    # Índices y constraints
    __table_args__ = (
        UniqueConstraint('provider_id', 'service_id', 'day_of_week', name='unique_availability'),
        Index('idx_service_availability_provider_id', 'provider_id'),
        Index('idx_service_availability_service_id', 'service_id'),
        Index('idx_service_availability_day_of_week', 'day_of_week'),
    )

    def __repr__(self):
        return f"<ServiceAvailability provider={self.provider_id} sp={self.service_id} day={self.day_of_week}>"


# ============================================================================
# MODELO: BOOKING NOTE (Notas internas)
# ============================================================================

class BookingNote(Base):
    """Modelo para notas asociadas a una reserva"""
    __tablename__ = "booking_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Relación
    booking_id = Column(Integer, ForeignKey(BOOKINGS_ID_FK, ondelete=CASCADE_OPTION), nullable=False, index=True)
    
    # Contenido
    note_type = Column(String(20), nullable=False)  # INTERNAL, CLIENT_VISIBLE, PROVIDER_VISIBLE
    content = Column(Text, nullable=False)
    
    # Quién escribió
    created_by_id = Column(Integer, ForeignKey(USERS_ID_FK, ondelete=SET_NULL_OPTION), nullable=False)
    
    # Metadatos
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relaciones
    booking = relationship("Booking", back_populates="notes")
    created_by = relationship("User")
    
    # Índices
    __table_args__ = (
        Index('idx_booking_notes_booking_id', 'booking_id'),
    )

    def __repr__(self):
        return f"<BookingNote {self.booking_id}>"