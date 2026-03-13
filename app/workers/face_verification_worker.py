"""
Face Verification Worker
Processes face matching jobs asynchronously using Celery + Redis
"""

import logging
import asyncio
from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime
import time

logger = logging.getLogger(__name__)

# Import Celery app from core configuration
try:
    from app.core.celery import celery_app
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    logger.warning("[WORKER] Celery not available - using synchronous fallback")
    celery_app = None


class FaceVerificationTask:
    """Wrapper for face verification task"""
    
    @staticmethod
    async def process_verification(
        verification_id: int,
        selfie_url: str,
        id_document_url: str,
        provider_id: int
    ) -> Dict[str, Any]:
        """
        Process face verification asynchronously.
        
        Args:
            verification_id: ID of ProviderVerification record
            selfie_url: Cloudinary URL of selfie
            id_document_url: Cloudinary URL of ID document
            provider_id: ID of provider
        
        Returns:
            Dict with results
        """
        try:
            logger.info(f"[VERIFICATION_TASK] Starting verification task for verification_id={verification_id}")
            
            # Import here to avoid circular imports
            from app.services.aws_rekognition_service import compare_faces as rekognition_compare

            # Perform face matching via AWS Rekognition
            is_match, confidence_score, metadata = await rekognition_compare(
                selfie_url=selfie_url,
                id_document_url=id_document_url
            )
            
            # Determine status
            status = "APPROVED" if is_match else "REJECTED"
            
            logger.info(f"[VERIFICATION_TASK] Task complete: verification_id={verification_id}, status={status}, confidence={confidence_score}")
            
            return {
                "verification_id": verification_id,
                "provider_id": provider_id,
                "status": status,
                "confidence_score": float(confidence_score),
                "is_match": is_match,
                "metadata": metadata,
                "processed_at": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"[VERIFICATION_TASK] Error processing verification: {str(e)}", exc_info=True)
            return {
                "verification_id": verification_id,
                "provider_id": provider_id,
                "status": "REJECTED",
                "confidence_score": 0.0,
                "is_match": False,
                "error": str(e),
                "processed_at": datetime.utcnow().isoformat()
            }


if CELERY_AVAILABLE:
    @celery_app.task(
        name='face_verification.process',
        bind=True,
        max_retries=3,
        default_retry_delay=60
    )
    def process_face_verification(
        self,
        verification_id: int,
        selfie_url: str,
        id_document_url: str,
        provider_id: int
    ) -> Dict[str, Any]:
        """
        Celery task for processing face verification.
        Retries up to 3 times if it fails.
        """
        try:
            logger.info(f"[CELERY_TASK] Processing verification {verification_id}")
            
            # Run async function in event loop
            result = asyncio.run(
                FaceVerificationTask.process_verification(
                    verification_id=verification_id,
                    selfie_url=selfie_url,
                    id_document_url=id_document_url,
                    provider_id=provider_id
                )
            )
            
            # TODO: Update database with result
            # This will be called by callback
            logger.info(f"[CELERY_TASK] Task result: {result}")
            
            return result
        
        except Exception as exc:
            logger.error(f"[CELERY_TASK] Task failed: {str(exc)}")
            # Retry with exponential backoff
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
