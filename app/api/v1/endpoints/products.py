"""
Products API - Product catalog and platform mappings
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.dependencies import get_db
from app.services.product_service import ProductService
from app.schemas.monetization import (
    ProductResponse,
    ProductCatalogResponse,
    ProductCatalogItem
)

router = APIRouter()


@router.get("/catalog", response_model=ProductCatalogResponse)
def get_product_catalog(
    platform: Optional[str] = Query(None, regex="^(google_play|apple_iap|web)$"),
    target_role: Optional[str] = Query(None, regex="^(CLIENT|PROVIDER|ALL)$"),
    db: Session = Depends(get_db)
):
    """
    Get complete product catalog with platform mappings
    
    Query Parameters:
    - platform: Filter by platform (google_play, apple_iap, web)
    - target_role: Filter by target role (CLIENT, PROVIDER, ALL)
    
    Returns:
    - Complete product catalog with platform-specific information
    """
    try:
        # Validate platform if provided
        if platform and not ProductService.validate_platform(platform):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid platform. Must be one of: google_play, apple_iap, web"
            )
        
        # Validate role if provided
        if target_role and not ProductService.validate_role(target_role):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role. Must be one of: CLIENT, PROVIDER, ALL"
            )
        
        # Get catalog
        catalog = ProductService.get_product_catalog(
            db=db,
            platform=platform,
            target_role=target_role
        )
        
        return {
            "products": catalog,
            "total": len(catalog)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving product catalog: {str(e)}"
        )


@router.get("/{sku}", response_model=ProductResponse)
def get_product_by_sku(
    sku: str,
    db: Session = Depends(get_db)
):
    """
    Get product by SKU
    
    Path Parameters:
    - sku: Product SKU (e.g., premium_access_7days)
    
    Returns:
    - Product details
    """
    product = ProductService.get_product_by_sku(db=db, sku=sku)
    
    if not product:
        raise HTTPException(
            status_code=404,
            detail=f"Product with SKU '{sku}' not found"
        )
    
    return product


@router.get("", response_model=List[ProductResponse])
def get_products(
    target_role: Optional[str] = Query(None, regex="^(CLIENT|PROVIDER|ALL)$"),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    Get all products
    
    Query Parameters:
    - target_role: Filter by target role (CLIENT, PROVIDER, ALL)
    - include_inactive: Include inactive products (default: False)
    
    Returns:
    - List of products
    """
    try:
        # Validate role if provided
        if target_role and not ProductService.validate_role(target_role):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role. Must be one of: CLIENT, PROVIDER, ALL"
            )
        
        products = ProductService.get_all_products(
            db=db,
            include_inactive=include_inactive,
            target_role=target_role
        )
        
        return products
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving products: {str(e)}"
        )
