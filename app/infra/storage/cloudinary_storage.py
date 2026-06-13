"""
Cloudinary Storage Implementation
Concrete adapter for Cloudinary API
"""

import asyncio
import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary import CloudinaryResource
from datetime import datetime, timedelta, timezone
import hashlib
import time
from typing import Optional, Dict, Any
from app.infra.storage.adapter import (
    StorageAdapter,
    UploadResult,
    DeleteResult,
    SignatureResult
)
from app.core.config import settings


class CloudinaryStorage(StorageAdapter):
    """Cloudinary implementation of StorageAdapter"""
    
    def __init__(self):
        # Configure cloudinary
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True
        )
    
    async def generate_upload_signature(
        self,
        folder: str,
        resource_type: str = "auto",
        unsigned: bool = True,
        upload_preset: str = None
    ) -> SignatureResult:
        """
        Generate signed upload credentials for frontend direct upload.
        
        Frontend will use these to upload directly to Cloudinary without
        exposing sensitive credentials.
        
        IMPORTANT: For unsigned uploads, the upload_preset MUST exist in your
        Cloudinary account settings. Create an unsigned preset first!
        """
        try:
            # Generate timestamp
            timestamp = int(time.time())
            
            # Use provided preset or default from settings
            if upload_preset is None:
                upload_preset = getattr(settings, 'CLOUDINARY_UPLOAD_PRESET', 'ml_default')
            
            # For unsigned uploads, use upload_preset
            if unsigned:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[CLOUDINARY] Generating unsigned signature with preset: {upload_preset}")
                
                return SignatureResult(
                    signature="",  # Not needed for unsigned
                    timestamp=timestamp,
                    api_key=settings.CLOUDINARY_API_KEY,
                    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                    upload_preset=upload_preset,
                    folder=folder
                )
            
            # For signed uploads (if needed)
            params = {
                "timestamp": timestamp,
                "folder": folder,
            }
            
            # Create signature
            query_string = "&".join([
                f"{key}={params[key]}" 
                for key in sorted(params.keys())
            ]) + settings.CLOUDINARY_API_SECRET
            
            signature = hashlib.sha1(query_string.encode()).hexdigest()
            
            return SignatureResult(
                signature=signature,
                timestamp=timestamp,
                api_key=settings.CLOUDINARY_API_KEY,
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                upload_preset="",
                folder=folder
            )
        
        except Exception as e:
            raise RuntimeError(f"Failed to generate upload signature: {str(e)}")
    
    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        folder: str,
        resource_type: str = "auto",
        public_id: Optional[str] = None,
        overwrite: bool = True
    ) -> UploadResult:
        """Upload file from backend"""
        try:
            # Prepare upload options
            options = {
                "folder": folder,
                "resource_type": resource_type,
                "use_filename": True,
                "unique_filename": False,
                "overwrite": overwrite,
            }
            
            # Only set format for images, not auto
            if resource_type == "image":
                options["format"] = None  # Keep original format
            
            if public_id:
                options["public_id"] = public_id
            
            # Run blocking Cloudinary upload in executor to avoid blocking async event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: cloudinary.uploader.upload(file_bytes, **options)
            )
            
            return UploadResult(
                public_id=result.get("public_id"),
                url=result.get("url"),
                secure_url=result.get("secure_url"),
                file_size=result.get("bytes", 0),
                mime_type=result.get("resource_type", "auto"),
                created_at=datetime.now(timezone.utc),
                metadata={
                    "version": result.get("version"),
                    "width": result.get("width"),
                    "height": result.get("height"),
                }
            )
        
        except Exception as e:
            raise RuntimeError(f"Cloudinary upload failed: {str(e)}")
    
    async def delete_file(
        self,
        public_id: str,
        resource_type: str = "image"
    ) -> DeleteResult:
        """Delete file from Cloudinary"""
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type
            )
            
            success = result.get("result") == "ok"
            
            return DeleteResult(
                success=success,
                public_id=public_id,
                message=result.get("result", "Failed")
            )
        
        except Exception as e:
            return DeleteResult(
                success=False,
                public_id=public_id,
                message=str(e)
            )
    
    async def get_file_info(
        self,
        public_id: str
    ) -> Dict[str, Any]:
        """Get file metadata from Cloudinary"""
        try:
            result = cloudinary.api.resource(public_id)
            return result
        except Exception as e:
            raise RuntimeError(f"Failed to get file info: {str(e)}")
    
    async def optimize_url(
        self,
        public_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        quality: str = "auto",
        format: str = "auto"
    ) -> str:
        """
        Generate optimized URL with transformations.
        Useful for thumbnails, responsive images, etc.
        """
        try:
            url = cloudinary.CloudinaryResource(public_id).build_url(
                width=width,
                height=height,
                crop="fill",
                quality=quality,
                format=format,
                secure=True
            )
            return url
        except Exception as e:
            raise RuntimeError(f"Failed to generate optimized URL: {str(e)}")
