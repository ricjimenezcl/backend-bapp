
"""
Document and Verification Schemas - Pydantic V2
For validation and serialization
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


# ============================================================
# SIGNATURE RESULT SCHEMA (para API)
# ============================================================
from pydantic import BaseModel
class SignatureResultSchema(BaseModel):
    signature: str
    api_key: str
    cloud_name: str
    timestamp: int
    public_id: str
    upload_preset: str
    folder: str


# ============================================================
# ENUMS
# ============================================================

class DocumentTypeEnum(str, Enum):
    IDENTITY_DOCUMENT = "IDENTITY_DOCUMENT"
    SELFIE = "SELFIE"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"


class FaceMatchStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# ============================================================
# USER DOCUMENTS
# ============================================================

class UserDocumentBase(BaseModel):
    document_type: DocumentTypeEnum
    cloudinary_public_id: str = Field(..., description="Cloudinary public ID for the document")
    cloudinary_url: str = Field(..., description="Cloudinary CDN URL")
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    expires_at: Optional[datetime] = None


class UserDocumentCreate(BaseModel):
    """Used when uploading a document"""
    document_type: DocumentTypeEnum
    cloudinary_public_id: str
    cloudinary_url: str
    file_size: int
    mime_type: str


class UserDocumentResponse(UserDocumentBase):
    id: int
    user_id: int
    uploaded_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================
# PROVIDER VERIFICATION
# ============================================================

class InitiateVerificationRequest(BaseModel):
    """Request body for initiating face verification"""
    selfie_document_id: int = Field(..., description="ID of the selfie document")
    id_document_id: int = Field(..., description="ID of the identity document")


class ProviderVerificationBase(BaseModel):
    face_match_score: Decimal = Field(default=0.00, ge=0, le=100)
    face_match_status: FaceMatchStatusEnum
    
    # OCR Results
    ocr_extracted_name: Optional[str] = None
    ocr_extracted_id: Optional[str] = None
    ocr_confidence: Optional[Decimal] = None


class ProviderVerificationCreate(BaseModel):
    """Initial verification request with document references"""
    selfie_document_id: int = Field(..., description="Document ID of selfie")
    id_document_id: int = Field(..., description="Document ID of ID card/document")


class ProviderVerificationUpdate(BaseModel):
    """Admin updates verification status"""
    face_match_status: FaceMatchStatusEnum
    admin_notes: Optional[str] = None


class ProviderVerificationResponse(ProviderVerificationBase):
    id: int
    provider_id: int
    selfie_document_id: int
    id_document_id: int
    verified_by_admin_id: Optional[int] = None
    admin_verification_date: Optional[datetime] = None
    admin_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProviderVerificationDetailedResponse(ProviderVerificationResponse):
    """Detailed view with document info"""
    selfie_document: Optional[UserDocumentResponse] = None
    id_document: Optional[UserDocumentResponse] = None


# ============================================================
# GALLERY IMAGES
# ============================================================

class GalleryBase(BaseModel):
    cloudinary_public_id: str
    cloudinary_url: str
    caption: Optional[str] = None
    display_order: int = 0


class GalleryCreate(BaseModel):
    cloudinary_public_id: str
    cloudinary_url: str
    caption: Optional[str] = None
    display_order: int = 0


class GalleryResponse(GalleryBase):
    id: int
    provider_id: int
    uploaded_at: datetime
    
    class Config:
        from_attributes = True


class GalleryUpdate(BaseModel):
    caption: Optional[str] = None
    display_order: Optional[int] = None


# ============================================================
# BULK RESPONSES
# ============================================================

class ProviderDocumentsResponse(BaseModel):
    """All documents for a provider (for verification flow)"""
    identity_documents: List[UserDocumentResponse] = []
    selfies: List[UserDocumentResponse] = []
    verification: Optional[ProviderVerificationDetailedResponse] = None


class ProviderGalleryResponse(BaseModel):
    """All gallery images for a provider"""
    total_images: int
    images: List[GalleryResponse]


# ============================================================
# FACE PREVIEW SCHEMA
# ============================================================

class FacePreviewRequest(BaseModel):
    """Request to get face preview for verification"""
    selfie_document_id: int
    id_document_id: int


class FacePreviewResponse(BaseModel):
    """Response with face preview images"""
    success: bool
    selfie_preview: Optional[str] = None  # base64 data URI
    id_preview: Optional[str] = None      # base64 data URI
    selfie_detected: bool = False
    id_detected: bool = False
    selfie_count: Optional[int] = None
    id_count: Optional[int] = None
    error: Optional[str] = None
