"""
Storage Adapter Interface (Strategy Pattern)
Allows easy migration between Cloudinary, Backblaze B2, Cloudflare R2, etc.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class UploadResult:
    """Standard upload result across all adapters"""
    public_id: str
    url: str
    secure_url: str
    file_size: int
    mime_type: str
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.metadata is None:
            self.metadata = {}


@dataclass
class DeleteResult:
    """Standard delete result"""
    success: bool
    public_id: str
    message: str = ""


@dataclass
class SignatureResult:
    """Signed upload credentials for frontend"""
    signature: str
    timestamp: int
    api_key: str
    cloud_name: str
    upload_preset: str
    folder: str


class StorageAdapter(ABC):
    """Base adapter for cloud storage providers"""
    
    @abstractmethod
    async def generate_upload_signature(
        self,
        folder: str,
        resource_type: str = "auto"
    ) -> SignatureResult:
        """Generate signed upload credentials for frontend"""
        pass
    
    @abstractmethod
    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        folder: str,
        resource_type: str = "auto",
        public_id: Optional[str] = None
    ) -> UploadResult:
        """Upload file from backend"""
        pass
    
    @abstractmethod
    async def delete_file(
        self,
        public_id: str,
        resource_type: str = "image"
    ) -> DeleteResult:
        """Delete file by public_id"""
        pass
    
    @abstractmethod
    async def get_file_info(
        self,
        public_id: str
    ) -> Dict[str, Any]:
        """Get file metadata"""
        pass
    
    @abstractmethod
    async def optimize_url(
        self,
        public_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        quality: str = "auto",
        format: str = "auto"
    ) -> str:
        """Generate optimized URL with transformations"""
        pass
