from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import time

from app.core.database import get_db_async
from app.models.service_category import MainCategory
from app.models.service_category import ServiceCategory
from app.schemas.main_category import MainCategoryResponse, MainCategoryWithServices
from app.schemas.service_category import ServiceCategoryResponse

router = APIRouter()

# ── In-memory cache para datos estáticos (categorías raramente cambian) ───────
# TTL de 10 minutos — sin invalidación manual, acepta eventual consistency.
_CACHE_TTL = 600  # segundos

_cache: dict = {}  # key → {"data": ..., "ts": float}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data) -> None:
    _cache[key] = {"data": data, "ts": time.monotonic()}

@router.get("/main-categories", response_model=List[MainCategoryResponse])
async def get_main_categories(db: AsyncSession = Depends(get_db_async)):
    """Obtener todas las categorías principales"""
    cached = _cache_get("main_categories")
    if cached is not None:
        return cached
    try:
        result = await db.execute(
            select(MainCategory)
            .where(MainCategory.is_active == True)
            .order_by(MainCategory.name)
        )
        main_categories = result.scalars().all()
        _cache_set("main_categories", main_categories)
        return main_categories
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving main categories: {str(e)}")

@router.get("/main-categories/{main_category_id}", response_model=MainCategoryWithServices)
async def get_main_category_with_services(
    main_category_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener una categoría principal con sus servicios"""
    try:
        # Obtener la categoría principal
        main_category_result = await db.execute(
            select(MainCategory).where(MainCategory.id == main_category_id)
        )
        main_category = main_category_result.scalar_one_or_none()
        
        if not main_category:
            raise HTTPException(status_code=404, detail="Main category not found")
        
        # Obtener los servicios de esta categoría
        services_result = await db.execute(
            select(ServiceCategory)
            .where(
                ServiceCategory.main_category_id == main_category_id,
                ServiceCategory.is_active == True
            )
            .order_by(ServiceCategory.name)
        )
        services = services_result.scalars().all()
        
        return MainCategoryWithServices(
            id=main_category.id,
            name=main_category.name,
            description=main_category.description,
            icon=main_category.icon,
            is_active=main_category.is_active,
            created_at=main_category.created_at,
            services=services
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving category: {str(e)}")

@router.get("/services/{service_id}", response_model=ServiceCategoryResponse)
async def get_service_category(
    service_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener un servicio específico"""
    try:
        result = await db.execute(
            select(ServiceCategory).where(ServiceCategory.id == service_id)
        )
        service = result.scalar_one_or_none()
        
        if not service:
            raise HTTPException(status_code=404, detail="Service category not found")
        
        return service
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving service: {str(e)}")

@router.get("/services", response_model=List[ServiceCategoryResponse])
async def get_all_services(db: AsyncSession = Depends(get_db_async)):
    """Obtener todos los servicios"""
    cached = _cache_get("all_services")
    if cached is not None:
        return cached
    try:
        result = await db.execute(
            select(ServiceCategory)
            .where(ServiceCategory.is_active == True)
            .order_by(ServiceCategory.name)
        )
        services = result.scalars().all()
        _cache_set("all_services", services)
        return services
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving services: {str(e)}")
