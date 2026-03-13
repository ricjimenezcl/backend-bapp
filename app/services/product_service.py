"""
Product Service - Manages product catalog and platform mappings
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_

from app.models.product import Product
from app.models.platform_product import PlatformProduct
from app.schemas.monetization import (
    ProductResponse,
    ProductCatalogItem,
    PlatformProductResponse
)


class ProductService:
    """Service for managing products and platform mappings"""

    @staticmethod
    def get_all_products(
        db: Session,
        include_inactive: bool = False,
        target_role: Optional[str] = None
    ) -> List[Product]:
        """
        Get all products from catalog
        
        Args:
            db: Database session
            include_inactive: Include inactive products
            target_role: Filter by target role (CLIENT, PROVIDER, ALL)
            
        Returns:
            List of products
        """
        query = db.query(Product)
        
        if not include_inactive:
            query = query.filter(Product.is_active == True)
            
        if target_role:
            query = query.filter(
                (Product.target_role == target_role) | 
                (Product.target_role == "ALL")
            )
            
        return query.order_by(Product.id).all()

    @staticmethod
    def get_product_by_id(db: Session, product_id: int) -> Optional[Product]:
        """
        Get product by ID
        
        Args:
            db: Database session
            product_id: Product ID
            
        Returns:
            Product or None
        """
        return db.query(Product).filter(Product.id == product_id).first()

    @staticmethod
    def get_product_by_sku(db: Session, sku: str) -> Optional[Product]:
        """
        Get product by SKU
        
        Args:
            db: Database session
            sku: Product SKU
            
        Returns:
            Product or None
        """
        return db.query(Product).filter(Product.sku == sku).first()

    @staticmethod
    def get_platform_product(
        db: Session,
        product_id: int,
        platform: str
    ) -> Optional[PlatformProduct]:
        """
        Get platform-specific product mapping
        
        Args:
            db: Database session
            product_id: Product ID
            platform: Platform (google_play, apple_iap, web)
            
        Returns:
            PlatformProduct or None
        """
        return db.query(PlatformProduct).filter(
            and_(
                PlatformProduct.product_id == product_id,
                PlatformProduct.platform == platform,
                PlatformProduct.is_active == True
            )
        ).first()

    @staticmethod
    def get_platform_product_by_platform_id(
        db: Session,
        platform: str,
        platform_product_id: str
    ) -> Optional[PlatformProduct]:
        """
        Get platform product by platform-specific ID
        
        Args:
            db: Database session
            platform: Platform (google_play, apple_iap, web)
            platform_product_id: Platform-specific product ID
            
        Returns:
            PlatformProduct or None
        """
        return db.query(PlatformProduct).filter(
            and_(
                PlatformProduct.platform == platform,
                PlatformProduct.platform_product_id == platform_product_id,
                PlatformProduct.is_active == True
            )
        ).first()

    @staticmethod
    def get_product_catalog(
        db: Session,
        platform: Optional[str] = None,
        target_role: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get complete product catalog with platform mappings
        
        Args:
            db: Database session
            platform: Filter by platform (google_play, apple_iap, web)
            target_role: Filter by target role (CLIENT, PROVIDER, ALL)
            
        Returns:
            List of products with platform information
        """
        # Build base query with eager loading
        query = db.query(Product).options(
            joinedload(Product.platform_products)
        ).filter(Product.is_active == True)
        
        # Apply role filter
        if target_role:
            query = query.filter(
                (Product.target_role == target_role) | 
                (Product.target_role == "ALL")
            )
        
        products = query.order_by(Product.id).all()
        
        # Build catalog response
        catalog = []
        for product in products:
            # Filter platform products if needed
            platform_products = product.platform_products
            if platform:
                platform_products = [
                    pp for pp in platform_products 
                    if pp.platform == platform and pp.is_active
                ]
            else:
                platform_products = [
                    pp for pp in platform_products 
                    if pp.is_active
                ]
            
            catalog.append({
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "description": product.description,
                "target_role": product.target_role,
                "duration_days": product.duration_days,
                "price_usd": float(product.price_usd),
                "price_clp": float(product.price_clp),
                "free_limit": product.free_limit,
                "is_active": product.is_active,
                "metadata": product.product_metadata,
                "platforms": [
                    {
                        "id": pp.id,
                        "platform": pp.platform,
                        "platform_product_id": pp.platform_product_id,
                        "platform_price": pp.platform_price,
                        "is_active": pp.is_active
                    }
                    for pp in platform_products
                ]
            })
        
        return catalog

    @staticmethod
    def get_products_by_role(
        db: Session,
        role: str,
        include_inactive: bool = False
    ) -> List[Product]:
        """
        Get products available for a specific role
        
        Args:
            db: Database session
            role: User role (CLIENT or PROVIDER)
            include_inactive: Include inactive products
            
        Returns:
            List of products
        """
        query = db.query(Product)
        
        if not include_inactive:
            query = query.filter(Product.is_active == True)
        
        # Products matching role or ALL
        query = query.filter(
            (Product.target_role == role) | 
            (Product.target_role == "ALL")
        )
        
        return query.order_by(Product.id).all()

    @staticmethod
    def validate_platform(platform: str) -> bool:
        """
        Validate platform value
        
        Args:
            platform: Platform string
            
        Returns:
            True if valid, False otherwise
        """
        valid_platforms = ["google_play", "apple_iap", "web"]
        return platform in valid_platforms

    @staticmethod
    def validate_role(role: str) -> bool:
        """
        Validate role value
        
        Args:
            role: Role string
            
        Returns:
            True if valid, False otherwise
        """
        valid_roles = ["CLIENT", "PROVIDER", "ALL"]
        return role in valid_roles
