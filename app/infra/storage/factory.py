"""
Storage Factory Pattern
Single entry point for storage adapter instantiation.
Makes it easy to switch providers.
"""

from enum import Enum
from typing import Optional
from app.infra.storage.adapter import StorageAdapter
from app.infra.storage.cloudinary_storage import CloudinaryStorage


class StorageProvider(str, Enum):
    CLOUDINARY = "cloudinary"
    # Future: BACKBLAZE_B2 = "backblaze_b2"
    # Future: CLOUDFLARE_R2 = "cloudflare_r2"


class StorageFactory:
    """Factory for creating storage adapter instances"""
    
    _instances = {}  # Singleton cache
    
    @staticmethod
    def create(provider: StorageProvider = StorageProvider.CLOUDINARY) -> StorageAdapter:
        """
        Create or retrieve storage adapter instance.
        
        Args:
            provider: StorageProvider enum value
            
        Returns:
            StorageAdapter instance
            
        Raises:
            ValueError: If provider is not supported
        """
        
        # Return cached instance if exists
        if provider in StorageFactory._instances:
            return StorageFactory._instances[provider]
        
        # Create new instance
        if provider == StorageProvider.CLOUDINARY:
            instance = CloudinaryStorage()
        
        # Future implementations
        # elif provider == StorageProvider.BACKBLAZE_B2:
        #     instance = BackblazeB2Storage()
        # elif provider == StorageProvider.CLOUDFLARE_R2:
        #     instance = CloudflareR2Storage()
        
        else:
            raise ValueError(f"Unsupported storage provider: {provider}")
        
        # Cache and return
        StorageFactory._instances[provider] = instance
        return instance
    
    @staticmethod
    def get_default() -> StorageAdapter:
        """Get default configured storage provider"""
        return StorageFactory.create(StorageProvider.CLOUDINARY)


# Convenience function
def get_storage() -> StorageAdapter:
    """Get default storage adapter"""
    return StorageFactory.get_default()
