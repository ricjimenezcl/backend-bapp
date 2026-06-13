"""
Document Upload and Verification Endpoints
"""

import logging
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db_async
from app.dependencies import get_current_user, get_current_provider
from app.models import User, Provider, ProviderVerification
from app.schemas.document import (
    UserDocumentResponse,
    ProviderVerificationResponse,
    ProviderVerificationDetailedResponse,
    SignatureResultSchema,
    InitiateVerificationRequest,
    FacePreviewRequest,
    FacePreviewResponse,
)
from app.modules.documents.service import DocumentService
from app.infra.storage import get_storage
from sqlalchemy.future import select


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


# ============================================================
# UPLOAD ENDPOINTS
# ============================================================

@router.post(
    "/generate-upload-signature",
    response_model=SignatureResultSchema,
    summary="Generate Cloudinary signed upload credentials"
)
async def generate_upload_signature(
    document_type: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Generate signed upload credentials for direct Cloudinary upload from frontend.
    
    This allows secure, direct uploads from the Ionic app without exposing
    API secrets. Frontend uses these credentials to upload directly to Cloudinary.
    
    Args:
        document_type: IDENTITY_DOCUMENT, SELFIE, BACKGROUND_CHECK o PORTFOLIO
    """
    
    try:
        logger.info(f"[DEBUG] generate_upload_signature called for user: {current_user.email}, ID: {current_user.id}")
        
        # Verify user is a provider
        result = await db.execute(
            select(Provider).where(Provider.user_id == current_user.id)
        )
        provider = result.scalar_one_or_none()
        
        if not provider:
            logger.warning(f"[DEBUG] No provider found for user_id={current_user.id}, email={current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only providers can upload documents"
            )
        
        storage = get_storage()
        folder = f"users/{current_user.id}/documents/{document_type.lower()}"

        # PORTFOLIO usa firma signed para no depender de un unsigned preset whitelisted.
        use_unsigned = document_type.lower() != "portfolio"
        
        signature_result = await storage.generate_upload_signature(
            folder=folder,
            resource_type="image",
            unsigned=use_unsigned,
        )
        
        # Generate a unique public_id for this upload
        import uuid
        public_id = f"{document_type.lower()}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        
        logger.info(f"[UPLOAD_SIGNATURE] Generated for user {current_user.id}:")
        logger.info(f"  - Cloud: {signature_result.cloud_name}")
        logger.info(f"  - Preset: {signature_result.upload_preset}")
        logger.info(f"  - Folder: {signature_result.folder}")
        logger.info(f"  - Public ID: {public_id}")
        
        from app.schemas.document import SignatureResultSchema
        return SignatureResultSchema(
            signature=signature_result.signature,
            timestamp=signature_result.timestamp,
            api_key=signature_result.api_key,
            cloud_name=signature_result.cloud_name,
            upload_preset=signature_result.upload_preset,
            folder=signature_result.folder,
            public_id=public_id
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate signature: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate upload signature"
        )


@router.post(
    "/upload-signed",
    response_model=UserDocumentResponse,
    summary="Upload document directly (backend handles Cloudinary)"
)
async def upload_document_signed(
    document_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Upload document file directly. Backend uploads to Cloudinary using signed credentials.
    This is more secure than unsigned uploads and doesn't require Cloudinary preset configuration.
    
    Args:
        document_type: IDENTITY_DOCUMENT, SELFIE, or BACKGROUND_CHECK
        file: Document file to upload
    """
    
    try:
        logger.info(f"[UPLOAD_SIGNED] Backend upload for user {current_user.id}")
        logger.info(f"  - Type: {document_type}")
        logger.info(f"  - File: {file.filename}")
        logger.info(f"  - Content-Type: {file.content_type}")
        
        # Verify user is a provider
        result = await db.execute(
            select(Provider).where(Provider.user_id == current_user.id)
        )
        provider = result.scalar_one_or_none()
        
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only providers can upload documents"
            )
        
        service = DocumentService(db)
        
        # Read file content
        file_bytes = await file.read()
        file_size = len(file_bytes)
        
        # Upload to Cloudinary via backend
        document = await service.upload_user_document(
            user_id=current_user.id,
            document_type=document_type,
            file_bytes=file_bytes,
            filename=file.filename or "document",
            mime_type=file.content_type or "application/octet-stream",
            file_size=file_size
        )
        
        logger.info(f"[UPLOAD_SIGNED_SUCCESS] Document saved: {document.id}")
        
        return UserDocumentResponse(
            id=document.id,
            user_id=document.user_id,
            document_type=document.document_type,
            cloudinary_public_id=document.cloudinary_public_id,
            cloudinary_url=document.cloudinary_url,
            file_size=document.file_size,
            mime_type=document.mime_type,
            uploaded_at=document.uploaded_at
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPLOAD_SIGNED_ERROR] Failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.post(
    "/save-document",
    response_model=UserDocumentResponse,
    summary="Save document reference after Cloudinary upload"
)
async def save_document_reference(
    document_type: str = Form(...),
    cloudinary_public_id: str = Form(...),
    cloudinary_url: str = Form(...),
    file_size: int = Form(...),
    mime_type: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    After successful direct upload to Cloudinary from frontend,
    call this endpoint to save the document reference in the database.
    
    Args:
        document_type: IDENTITY_DOCUMENT, SELFIE, or BACKGROUND_CHECK
        cloudinary_public_id: Public ID from Cloudinary response
        cloudinary_url: URL from Cloudinary response
        file_size: File size in bytes
        mime_type: MIME type (e.g., image/jpeg)
    """
    
    try:
        logger.info(f"[SAVE_DOCUMENT] Saving document for user {current_user.id}")
        logger.info(f"  - Type: {document_type}")
        logger.info(f"  - Cloudinary ID: {cloudinary_public_id}")
        logger.info(f"  - File size: {file_size} bytes")
        
        service = DocumentService(db)
        
        # Save document reference to database
        # The file is already on Cloudinary, we just save the reference
        document = await service.save_document_reference(
            user_id=current_user.id,
            document_type=document_type,
            cloudinary_public_id=cloudinary_public_id,
            cloudinary_url=cloudinary_url,
            file_size=file_size,
            mime_type=mime_type
        )
        
        await db.commit()
        await db.refresh(document)
        
        logger.info(f"[SAVE_DOCUMENT] Document saved successfully - ID: {document.id}")
        return document
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save document: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save document"
        )


# ============================================================
# VERIFICATION ENDPOINTS
# ============================================================

@router.post(
    "/initiate-verification",
    response_model=ProviderVerificationResponse,
    summary="Initiate face matching verification"
)
async def initiate_face_verification(
    request_data: InitiateVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Initiate face matching between selfie and ID document.
    Provider must have uploaded both documents first.
    
    This marks documents as ready for face matching verification.
    Admin will review and approve/reject.
    
    ARCHITECTURAL NOTE:
    This endpoint allows reinitiation with new documents. If a previous
    verification exists, it will be replaced. This supports:
    - Provider retries (rejected verification)
    - Document updates
    - Testing workflows
    
    Request body (JSON):
    {
        "selfie_document_id": 1,
        "id_document_id": 2
    }
    """
    
    logger.info(f"[INITIATE_VERIFICATION] Request from user {current_user.id}")
    logger.info(f"  - Selfie doc: {request_data.selfie_document_id}")
    logger.info(f"  - ID doc: {request_data.id_document_id}")
    
    # Check if user is a provider
    result = await db.execute(
        select(Provider).where(Provider.user_id == current_user.id)
    )
    provider = result.scalar_one_or_none()
    
    if not provider:
        logger.warning(f"[INITIATE_VERIFICATION] User {current_user.id} is not a provider")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can initiate verification"
        )
    
    try:
        service = DocumentService(db)
        verification = await service.initiate_face_verification(
            provider_id=provider.id,
            selfie_document_id=request_data.selfie_document_id,
            id_document_id=request_data.id_document_id
        )
        
        await db.commit()
        await db.refresh(verification)
        
        logger.info(f"[INITIATE_VERIFICATION_SUCCESS] Verification ID: {verification.id}")
        logger.info(f"  - Provider: {provider.id}")
        logger.info(f"  - Status: {verification.face_match_status}")
        
        return verification
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[INITIATE_VERIFICATION_ERROR] Failed: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate verification: {str(e)}"
        )


@router.post(
    "/face-preview",
    response_model=FacePreviewResponse,
    summary="Get face preview for verification"
)
async def get_face_preview(
    request: FacePreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Get preview of detected faces before verification.
    Returns base64 encoded cropped face images.
    
    This endpoint shows users what faces will be compared.
    
    Request body:
    {
      "selfie_document_id": 123,
      "id_document_id": 456
    }
    """
    try:
        import asyncio
        
        logger.info(f"[FACE_PREVIEW] ========== START ==========")
        logger.info(f"[FACE_PREVIEW] Request from user: {current_user.id}")
        logger.info(f"[FACE_PREVIEW] selfie_id={request.selfie_document_id}, id_id={request.id_document_id}")
        
        # Get documents
        service = DocumentService(db)
        logger.info(f"[FACE_PREVIEW] Step 1: Fetching documents from database...")
        selfie_doc = await service.get_document(request.selfie_document_id)
        id_doc = await service.get_document(request.id_document_id)
        logger.info(f"[FACE_PREVIEW] Step 1: ✓ Documents fetched")
        
        if not selfie_doc or not id_doc:
            logger.warning(f"[FACE_PREVIEW] Document not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        if not selfie_doc.cloudinary_url or not id_doc.cloudinary_url:
            logger.warning(f"[FACE_PREVIEW] Document URLs not available")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document URLs not available"
            )
        
        # Get face previews — AWS Rekognition (reemplaza DeepFace)
        from app.services.aws_rekognition_service import get_face_preview as rekognition_preview

        logger.info(f"[FACE_PREVIEW] Step 2: Starting face detection via AWS Rekognition...")
        logger.info(f"[FACE_PREVIEW]   - selfie_url: {selfie_doc.cloudinary_url[:50]}...")
        logger.info(f"[FACE_PREVIEW]   - id_url: {id_doc.cloudinary_url[:50]}...")

        try:
            # Rekognition es síncrono vía HTTP — timeout conservador de 20s
            preview = await asyncio.wait_for(
                rekognition_preview(
                    selfie_url=selfie_doc.cloudinary_url,
                    id_document_url=id_doc.cloudinary_url
                ),
                timeout=20.0
            )
            logger.info(f"[FACE_PREVIEW] Step 2: ✓ Face detection completed")
        except asyncio.TimeoutError:
            logger.error(f"[FACE_PREVIEW] Step 2: ✗ Rekognition TIMEOUT after 20 seconds")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Face detection took too long (timeout after 20s)"
            )
        
        logger.info(f"[FACE_PREVIEW] Step 3: Processing results...")
        logger.info(f"[FACE_PREVIEW]   - selfie_detected: {preview.get('selfie_detected')}")
        logger.info(f"[FACE_PREVIEW]   - id_detected: {preview.get('id_detected')}")
        logger.info(f"[FACE_PREVIEW]   - selfie_preview_size: {len(preview.get('selfie') or '')} bytes")
        logger.info(f"[FACE_PREVIEW]   - id_preview_size: {len(preview.get('id_document') or '')} bytes")
        
        response = FacePreviewResponse(
            success=True,
            selfie_preview=preview.get("selfie"),
            id_preview=preview.get("id_document"),
            selfie_detected=preview.get("selfie_detected"),
            id_detected=preview.get("id_detected"),
            selfie_count=preview.get("selfie_count"),
            id_count=preview.get("id_count"),
            error=preview.get("error")
        )
        logger.info(f"[FACE_PREVIEW] Step 3: ✓ Response created")
        logger.info(f"[FACE_PREVIEW] ========== END (SUCCESS) ==========")
        
        return response
    
    except HTTPException:
        logger.error(f"[FACE_PREVIEW] HTTP Exception - re-raising")
        raise
    except Exception as e:
        logger.error(f"[FACE_PREVIEW] ========== END (ERROR) ==========")
        logger.error(f"[FACE_PREVIEW] Exception: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate face preview: {str(e)}"
        )


@router.get(
    "/verification-status",
    response_model=Optional[ProviderVerificationResponse],
    summary="Get current verification status"
)
async def get_verification_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Get current face verification status for the provider"""
    
    try:
        logger.info(f"[DEBUG] verification_status called for user: {current_user.email}, ID: {current_user.id}")
        
        # Get provider
        result = await db.execute(
            select(Provider).where(Provider.user_id == current_user.id)
        )
        provider = result.scalar_one_or_none()
        
        if not provider:
            logger.warning(f"[DEBUG] No provider found for user_id={current_user.id}, email={current_user.email}")
            logger.warning(f"[DEBUG] Checking all providers in database...")
            all_providers = await db.execute(select(Provider))
            all_providers_list = all_providers.scalars().all()
            logger.warning(f"[DEBUG] Total providers in DB: {len(all_providers_list)}")
            for p in all_providers_list[:5]:
                logger.warning(f"[DEBUG] Provider: id={p.id}, user_id={p.user_id}")
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only providers can view verification status"
            )
        
        logger.info(f"[DEBUG] Found provider: id={provider.id}, user_id={provider.user_id}")
        
        service = DocumentService(db)
        verification = await service.get_provider_verification(
            provider_id=provider.id
        )
        
        # Don't try to serialize lazy-loaded relationships
        # Just return the verification object directly
        if verification:
            logger.info(f"[DEBUG] Verification found: status={verification.face_match_status}")
        else:
            logger.info(f"[DEBUG] No verification record found for provider {provider.id}")
        
        return verification
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Failed to get verification status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get verification status"
        )


@router.get(
    "/can-add-services",
    summary="Check if provider can add services"
)
async def can_add_services(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Check if provider meets all requirements to add services:
    1. Has uploaded identity documents
    2. Face matching approved
    3. Admin validated
    """
    
    # Get provider
    result = await db.execute(
        select(Provider).where(Provider.user_id == current_user.id)
    )
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only providers can check this"
        )
    
    service = DocumentService(db)
    can_add, reason = await service.can_provider_add_services(provider.id)
    
    return {
        "can_add_services": can_add,
        "reason": reason,
        "provider_id": provider.id
    }


# ============================================================
# ADMIN VERIFICATION ENDPOINTS
# ============================================================

@router.post(
    "/admin/approve/{verification_id}",
    response_model=ProviderVerificationResponse,
    summary="[ADMIN] Approve face verification"
)
async def admin_approve_verification(
    verification_id: int,
    admin_notes: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Admin approves face verification. Provider can now add services."""
    
    # Check admin role
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can approve verifications"
        )
    
    try:
        service = DocumentService(db)
        verification = await service.approve_verification(
            verification_id=verification_id,
            admin_id=current_user.id,
            admin_notes=admin_notes
        )
        
        await db.commit()
        await db.refresh(verification)
        
        logger.info(f"Verification approved by admin {current_user.id}")
        
        return verification
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve verification: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve verification"
        )


@router.post(
    "/admin/reject/{verification_id}",
    response_model=ProviderVerificationResponse,
    summary="[ADMIN] Reject face verification"
)
async def admin_reject_verification(
    verification_id: int,
    admin_notes: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Admin rejects face verification. Provider must upload new documents."""
    
    # Check admin role
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can reject verifications"
        )
    
    try:
        service = DocumentService(db)
        verification = await service.reject_verification(
            verification_id=verification_id,
            admin_id=current_user.id,
            admin_notes=admin_notes
        )
        
        await db.commit()
        await db.refresh(verification)
        
        logger.info(f"Verification rejected by admin {current_user.id}")
        
        return verification
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject verification: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject verification"
        )


@router.get(
    "/admin/pending-verifications",
    summary="[ADMIN] List pending verifications"
)
async def get_pending_verifications(
    skip: int = 0,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Get list of pending face verifications"""
    
    # Check admin role
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view this"
        )
    
    result = await db.execute(
        select(ProviderVerification)
        .where(ProviderVerification.face_match_status.in_(["PENDING", "PROCESSING"]))
        .offset(skip)
        .limit(limit)
    )
    verifications = result.scalars().all()
    
    return {
        "total": len(verifications),
        "items": verifications
    }


@router.post(
    "/verify-provider-manual",
    response_model=ProviderVerificationResponse,
    summary="[ADMIN] Manual verification override for provider face match"
)
async def verify_provider_manual(
    verification_id: int = Form(...),
    admin_decision: str = Form(...),  # "APPROVED" or "REJECTED"
    admin_notes: Optional[str] = Form(None),
    confidence_score: Optional[float] = Form(None),  # Optional manual confidence
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Manually override face verification status as admin.
    
    This allows admins to approve or reject a verification regardless of
    automated face matching results. Used when:
    1. Automated matching fails but images look valid
    2. Documents are genuine but face matching threshold not met
    3. Special cases or manual review needed
    
    Args:
        verification_id: ID of ProviderVerification record
        admin_decision: "APPROVED" or "REJECTED"
        admin_notes: Optional notes explaining the decision
        confidence_score: Optional manual confidence score (0-100)
    
    Returns:
        Updated ProviderVerification record
    """
    
    # Check admin role
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can manually override verifications"
        )
    
    # Validate decision
    if admin_decision not in ["APPROVED", "REJECTED"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="admin_decision must be 'APPROVED' or 'REJECTED'"
        )
    
    # Validate confidence score if provided
    if confidence_score is not None:
        if not (0 <= confidence_score <= 100):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="confidence_score must be between 0-100"
            )
    
    try:
        service = DocumentService(db)
        
        # Get verification record
        result = await db.execute(
            select(ProviderVerification).where(
                ProviderVerification.id == verification_id
            )
        )
        verification = result.scalar_one_or_none()
        
        if not verification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification record not found"
            )
        
        # Update verification with manual override
        verification.face_match_status = admin_decision
        if confidence_score is not None:
            verification.face_match_score = confidence_score
        verification.verified_by_admin_id = current_user.id
        verification.admin_notes = admin_notes or f"Manual override by {current_user.email}"
        verification.admin_verification_date = time.time()
        
        # If APPROVED, also update provider validation_status
        if admin_decision == "APPROVED":
            result = await db.execute(
                select(Provider).where(Provider.id == verification.provider_id)
            )
            provider = result.scalar_one_or_none()
            if provider:
                provider.validation_status = "approved"
                logger.info(
                    f"[VERIFICATION] Manual approval: Provider {provider.id} by admin {current_user.id}"
                )
        else:
            logger.info(
                f"[VERIFICATION] Manual rejection: Provider {verification.provider_id} by admin {current_user.id}"
            )
        
        db.add(verification)
        await db.commit()
        await db.refresh(verification)
        
        logger.info(
            f"[VERIFICATION] Manual override completed: verification_id={verification_id}, "
            f"decision={admin_decision}, admin_id={current_user.id}"
        )
        
        return verification
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VERIFICATION] Manual override failed: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process manual override"
        )


@router.get(
    "/verification-status/{verification_id}",
    response_model=ProviderVerificationResponse,
    summary="Get verification status by ID"
)
async def get_verification_status(
    verification_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """
    Get the current status of a face verification by ID.
    
    Used by frontend to poll and check if verification is complete.
    Returns current status: PENDING, PROCESSING, APPROVED, or REJECTED.
    
    Args:
        verification_id: ID of the ProviderVerification record
    
    Returns:
        ProviderVerification record with current status
    """
    try:
        result = await db.execute(
            select(ProviderVerification).where(
                ProviderVerification.id == verification_id
            )
        )
        verification = result.scalar_one_or_none()
        
        if not verification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Verification record not found"
            )
        
        logger.info(
            f"[VERIFICATION] Status check: verification_id={verification_id}, "
            f"status={verification.face_match_status}"
        )
        
        return verification
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VERIFICATION] Failed to get verification status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get verification status"
        )
