from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum, Text, ForeignKey, DECIMAL
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=True)
    role = Column(Enum("CLIENT", "PROVIDER", "ADMIN", name="user_role"), nullable=False)
    status = Column(Enum("PENDING", "ACTIVE", "SUSPENDED", "REJECTED", name="user_status"), default="PENDING")
    email_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Recuperación de contraseña
    reset_token = Column(String(128), nullable=True)
    reset_token_expiration = Column(DateTime, nullable=True)

    # Verificación de email
    email_verification_token = Column(String(128), nullable=True)
    email_verification_expiration = Column(DateTime, nullable=True)

    # OAuth social login
    oauth_provider = Column(String(20), nullable=True)    # 'google' | 'facebook' | None
    oauth_id = Column(String(255), nullable=True)         # ID único del proveedor OAuth
    oauth_avatar_url = Column(String(500), nullable=True) # URL foto de perfil OAuth

    # Legal compliance
    terms_accepted = Column(Boolean, default=False, nullable=False)
    terms_accepted_at = Column(DateTime, nullable=True)
    email_opt_in = Column(Boolean, default=False, nullable=False)

    # Premium access control
    has_premium = Column(Boolean, default=False, nullable=False)
    premium_activated_at = Column(DateTime, nullable=True)
    premium_expires_at = Column(DateTime, nullable=True)

    # Relationships - lazy="selectin" para async compatibility
    # selectin: carga automática en async usando SELECT IN queries
    client_profile = relationship(
        "UserProfile", 
        back_populates="user", 
        uselist=False, 
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    provider_profile = relationship(
        "Provider", 
        back_populates="user", 
        uselist=False, 
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    bookings_as_client = relationship(
        "Booking", 
        back_populates="client", 
        foreign_keys="Booking.client_id",
        lazy="selectin"
    )
    reports_made = relationship(
        "Report",
        back_populates="reporter",
        foreign_keys="Report.reporter_id",
        lazy="dynamic"
    )
    reports_received = relationship(
        "Report",
        back_populates="reported_user",
        foreign_keys="Report.reported_user_id",
        lazy="dynamic"
    )
    moderation_history = relationship(
        "ModerationHistory",
        back_populates="user",
        foreign_keys="ModerationHistory.user_id",
        lazy="dynamic"
    )

    @property
    def is_premium_active(self) -> bool:
        """Verifica si el acceso premium está vigente"""
        from datetime import datetime
        if not self.has_premium:
            return False
        if not self.premium_expires_at:
            return False
        return datetime.utcnow() < self.premium_expires_at

class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(20))
    avatar = Column(String(500))
    bio = Column(Text)
    rating_avg = Column(DECIMAL(3, 2), default=0.0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="client_profile")