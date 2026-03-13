"""
Document Management Models
- UserDocument: stores uploaded documents (selfie, ID, etc)
- ProviderVerification: tracks face matching and verification status
- Gallery: provider gallery images
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Enum, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class UserDocument(Base):
    """
    Stores all uploaded documents for users.
    Used for identity verification, background checks, etc.
    """
    __tablename__ = "user_documents"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Document metadata
    document_type = Column(
        Enum(
            "IDENTITY_DOCUMENT",
            "SELFIE",
            "BACKGROUND_CHECK",
            name="documenttype"
        ),
        nullable=False,
        index=True
    )
    
    # Cloudinary storage info
    cloudinary_url = Column(String(500), nullable=False)
    cloudinary_public_id = Column(String(255), unique=True)
    
    # File metadata
    file_size = Column(Integer)
    mime_type = Column(String(50))
    
    # Timestamps
    uploaded_at = Column(DateTime, default=func.now(), index=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    
    def __repr__(self):
        return f"<UserDocument(id={self.id}, type={self.document_type}, user_id={self.user_id})>"


class ProviderVerification(Base):
    """
    Tracks face matching and identity verification for service providers.
    This is BLOCKING: Provider cannot add services until face_match_status = APPROVED
    """
    __tablename__ = "provider_verification"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False, unique=True)
    
    # Document references
    selfie_document_id = Column(Integer, ForeignKey("user_documents.id"), nullable=False)
    id_document_id = Column(Integer, ForeignKey("user_documents.id"), nullable=False)
    
    # Face Matching Results (0-100 confidence score)
    face_match_score = Column(Numeric(5, 2), default=0.00)
    face_match_status = Column(
        Enum(
            "PENDING",        # Waiting for verification
            "PROCESSING",     # AI processing face match
            "APPROVED",       # Faces match + admin approved
            "REJECTED",       # Faces don't match or admin rejected
            "EXPIRED",        # Verification expired, needs renewal
            name="facematchstatus"
        ),
        default="PENDING",
        index=True
    )
    
    # Admin Verification
    verified_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    admin_verification_date = Column(DateTime, nullable=True, index=True)
    admin_notes = Column(Text, nullable=True)
    
    # OCR Results from ID Document
    ocr_extracted_name = Column(String(255), nullable=True)
    ocr_extracted_id = Column(String(50), nullable=True)
    ocr_confidence = Column(Numeric(5, 2), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), index=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    provider = relationship("Provider", foreign_keys=[provider_id])
    selfie_document = relationship(
        "UserDocument",
        foreign_keys=[selfie_document_id],
        primaryjoin="ProviderVerification.selfie_document_id == UserDocument.id"
    )
    id_document = relationship(
        "UserDocument",
        foreign_keys=[id_document_id],
        primaryjoin="ProviderVerification.id_document_id == UserDocument.id"
    )
    verified_by_admin = relationship("User", foreign_keys=[verified_by_admin_id])
    
    def __repr__(self):
        # Avoid accessing lazy-loaded properties that require active session
        return f"<ProviderVerification(id={self.id}, provider_id={self.provider_id})"
    
    @property
    def is_verified(self) -> bool:
        """Check if verification is approved"""
        return self.face_match_status == "APPROVED"
    
    @property
    def is_pending(self) -> bool:
        """Check if verification is pending"""
        return self.face_match_status in ["PENDING", "PROCESSING"]


class Gallery(Base):
    """
    Provider gallery images (work portfolio).
    Stored in Cloudinary, references only URL and metadata.
    """
    __tablename__ = "galleries"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False, index=True)
    
    # Cloudinary storage
    cloudinary_url = Column(String(500), nullable=False)
    cloudinary_public_id = Column(String(255), unique=True)
    
    # Metadata
    caption = Column(String(255), nullable=True)
    display_order = Column(Integer, default=0, index=True)
    
    # Timestamp
    uploaded_at = Column(DateTime, default=func.now())
    
    # Relationships
    provider = relationship("Provider", foreign_keys=[provider_id])
    
    def __repr__(self):
        return f"<Gallery(id={self.id}, provider_id={self.provider_id})>"
