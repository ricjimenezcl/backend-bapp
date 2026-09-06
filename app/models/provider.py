from sqlalchemy import Column, Integer, SmallInteger, String, DateTime, Time, Text, ForeignKey, DECIMAL, Boolean, Enum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from enum import Enum as PyEnum
from types import SimpleNamespace
try:
    from geoalchemy2 import Geometry as GeoGeometry
    _GEOALCHEMY2_AVAILABLE = True
except ImportError:
    _GEOALCHEMY2_AVAILABLE = False

# ✅ UNIFIED VALIDATION STATUS ENUM
class ValidationStatus(str, PyEnum):
    """Enum unificado para validation_status en providers y service_providers"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(20))
    avatar = Column(String(500))  # URL o base64 string, no binary data
    bio = Column(Text)
    rating_avg = Column(DECIMAL(3, 2), default=5.00)
    run = Column(String(15))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Validación biométrica
    identity_document_url = Column(String(500), nullable=True)
    selfie_url = Column(String(500), nullable=True)
    # ✅ Use native_enum=False to handle string values from DB
    validation_status = Column(Enum(ValidationStatus, values_callable=lambda x: [e.value for e in x], name="validation_status", native_enum=False), default=ValidationStatus.PENDING)
    validation_notes = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="provider_profile")
    service_providers = relationship("ServiceProvider", back_populates="provider", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="provider", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="provider", foreign_keys="Review.provider_id", cascade="all, delete-orphan")
    working_hours = relationship("ProviderWorkingHours", back_populates="provider", cascade="all, delete-orphan")

class ServiceProvider(Base):
    __tablename__ = "service_providers"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    # FK real confirmada en producción (constraint service_providers_service_id_fkey): services.id
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    business_name = Column(String(255), nullable=False)
    description = Column(Text)
    address = Column(String(500), nullable=False)
    latitude = Column(DECIMAL(10, 8), nullable=False)
    longitude = Column(DECIMAL(11, 8), nullable=False)
    phone = Column(String(20), nullable=False)
    hourly_rate = Column(DECIMAL(10, 2))
    is_available = Column(Boolean, default=True)
    # PostGIS geometry — nullable durante transición. Gestionado por trigger en BD.
    # Requiere geoalchemy2 instalado y migración 003_postgis_geolocation.sql ejecutada.
    location = Column(GeoGeometry('POINT', srid=4326), nullable=True) if _GEOALCHEMY2_AVAILABLE else Column(Text, nullable=True)
    # ✅ Use native_enum=False to handle string values from DB
    validation_status = Column(Enum(ValidationStatus, values_callable=lambda x: [e.value for e in x], name="validation_status", native_enum=False), default=ValidationStatus.PENDING)
    rating_avg = Column(DECIMAL(3, 2), default=0.00)
    total_reviews = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Fotos del portafolio de este servicio específico
    # Formato: [{"id": "abc123", "url": "https://...", "public_id": "bappsearch/..."}]
    portfolio_images = Column(JSON, nullable=True, default=None)

    # Relationships - FIXED: Use lazy='joined' for eager loading
    provider = relationship("Provider", back_populates="service_providers", lazy='joined')
    # Nueva taxonomía: apunta al modelo Service (tabla services), no a ServiceCategory (legacy)
    service = relationship("Service", back_populates="service_providers", lazy='joined')
    bookings = relationship("Booking", back_populates="service_provider", cascade="all, delete-orphan")

    @property
    def service_category(self):
        """Compatibilidad hacia atrás: expone el servicio (nueva taxonomía:
        services + subcategories) con el mismo shape que antes exponía
        ServiceCategory, para no romper el contrato de ServiceCategoryResponse
        consumido por el frontend (web y mobile).

        Requiere 'service' y 'service.subcategory' cargados vía lazy='joined'
        (configurado por defecto en ambos modelos) para evitar lazy-load
        síncrono en contexto async.
        """
        svc = self.service
        if svc is None:
            return None
        subcat = getattr(svc, "subcategory", None)
        return SimpleNamespace(
            id=svc.id,
            name=svc.name,
            description=svc.description,
            icon=svc.icon,
            parent_category=subcat.name if subcat else None,
            is_active=True,
            main_category_id=subcat.main_category_id if subcat else None,
            created_at=svc.created_at,
        )


class ProviderWorkingHours(Base):
    """Horarios de trabajo del proveedor por día de la semana.
    day_of_week: 0=Lunes, 1=Martes, ..., 5=Sábado, 6=Domingo
    (coincide con Python datetime.weekday())
    """
    __tablename__ = "provider_working_hours"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = Column(SmallInteger, nullable=False)  # 0=Lun … 6=Dom
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    provider = relationship("Provider", back_populates="working_hours")