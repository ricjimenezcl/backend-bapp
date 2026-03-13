"""
Documents module init
"""

from .service import DocumentService
from .endpoints import router

__all__ = ["DocumentService", "router"]
