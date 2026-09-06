from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text
from typing import List, Optional
import time

from app.core.database import get_db_async
from app.models.service_category import MainCategory
from app.schemas.main_category import MainCategoryResponse, MainCategoryWithServices
from app.schemas.service_category import ServiceCategoryResponse
from app.schemas.subcategory import SubcategoryResponse, ServiceNewResponse

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
    """Obtener una categoría principal con sus servicios.

    Nueva taxonomía: servicios obtenidos vía subcategories → services
    (ya no se consulta la tabla legacy service_categories).
    """
    try:
        # Obtener la categoría principal
        main_category_result = await db.execute(
            select(MainCategory).where(MainCategory.id == main_category_id)
        )
        main_category = main_category_result.scalar_one_or_none()
        
        if not main_category:
            raise HTTPException(status_code=404, detail="Main category not found")
        
        # Obtener los servicios de esta categoría (subcategories → services)
        services_result = await db.execute(
            text(
                "SELECT s.id, s.name, s.description, s.icon, s.created_at, "
                "       sub.name AS parent_category, sub.main_category_id "
                "FROM services s "
                "JOIN subcategories sub ON sub.id = s.subcategory_id "
                "WHERE sub.main_category_id = :mcid "
                "ORDER BY s.name"
            ),
            {"mcid": main_category_id}
        )
        services = [
            ServiceCategoryResponse(
                id=row.id,
                name=row.name,
                description=row.description,
                icon=row.icon,
                parent_category=row.parent_category,
                is_active=True,
                main_category_id=row.main_category_id,
                created_at=row.created_at,
            )
            for row in services_result
        ]
        
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
    """Obtener un servicio específico.

    Nueva taxonomía: se busca en la tabla services (ya no en la tabla
    legacy service_categories). service_id corresponde a services.id.
    """
    try:
        result = await db.execute(
            text(
                "SELECT s.id, s.name, s.description, s.icon, s.created_at, "
                "       sub.name AS parent_category, sub.main_category_id "
                "FROM services s "
                "JOIN subcategories sub ON sub.id = s.subcategory_id "
                "WHERE s.id = :sid"
            ),
            {"sid": service_id}
        )
        row = result.first()
        
        if not row:
            raise HTTPException(status_code=404, detail="Service category not found")
        
        return ServiceCategoryResponse(
            id=row.id,
            name=row.name,
            description=row.description,
            icon=row.icon,
            parent_category=row.parent_category,
            is_active=True,
            main_category_id=row.main_category_id,
            created_at=row.created_at,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving service: {str(e)}")


@router.get("/services-catalog", response_model=List[ServiceNewResponse])
async def get_service_catalog(
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener el catálogo completo de servicios desde la tabla services.

    La respuesta incluye service_category_id para que el frontend siga
    navegando con los IDs que consume el buscador de proveedores.
    """
    normalized_query = (q or "").strip()
    cache_key = f"service_catalog::{normalized_query.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        query = text(
            "SELECT s.id, s.name, s.description, s.icon, s.subcategory_id, "
            "       s.id AS service_category_id "
            "FROM services s"
        )
        params = {}

        if normalized_query:
            query = text(
                "SELECT s.id, s.name, s.description, s.icon, s.subcategory_id, "
                "       s.id AS service_category_id "
                "FROM services s "
                "WHERE LOWER(s.name) LIKE :pattern OR LOWER(COALESCE(s.description, '')) LIKE :pattern"
            )
            params["pattern"] = f"%{normalized_query.lower()}%"

        result = await db.execute(query, params)
        rows = [dict(row._mapping) for row in result]
        _cache_set(cache_key, rows)
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving service catalog: {str(e)}")

@router.get("/services", response_model=List[ServiceCategoryResponse])
async def get_all_services(db: AsyncSession = Depends(get_db_async)):
    """Obtener todos los servicios.

    Nueva taxonomía: services + subcategories (ya no la tabla legacy
    service_categories).
    """
    cached = _cache_get("all_services")
    if cached is not None:
        return cached
    try:
        result = await db.execute(
            text(
                "SELECT s.id, s.name, s.description, s.icon, s.created_at, "
                "       sub.name AS parent_category, sub.main_category_id "
                "FROM services s "
                "JOIN subcategories sub ON sub.id = s.subcategory_id "
                "ORDER BY s.name"
            )
        )
        services = [
            ServiceCategoryResponse(
                id=row.id,
                name=row.name,
                description=row.description,
                icon=row.icon,
                parent_category=row.parent_category,
                is_active=True,
                main_category_id=row.main_category_id,
                created_at=row.created_at,
            )
            for row in result
        ]
        _cache_set("all_services", services)
        return services
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving services: {str(e)}")


@router.get("/main-categories/{main_category_id}/subcategories", response_model=List[SubcategoryResponse])
async def get_subcategories_by_main_category(
    main_category_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """Subcategorías de una categoría principal (tabla subcategories)."""
    cache_key = f"subcategories_{main_category_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        result = await db.execute(
            text(
                "SELECT id, name, description, icon, main_category_id "
                "FROM subcategories "
                "WHERE main_category_id = :mcid "
                "ORDER BY name"
            ),
            {"mcid": main_category_id}
        )
        rows = [dict(r._mapping) for r in result]
        _cache_set(cache_key, rows)
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving subcategories: {str(e)}")


@router.get("/subcategories/{subcategory_id}/services", response_model=List[ServiceNewResponse])
async def get_services_by_subcategory(
    subcategory_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """Servicios de una subcategoría.
    Incluye service_category_id = s.id (services.id), que es el mismo valor
    que consume el buscador de proveedores para service_providers.service_id.
    """
    cache_key = f"services_sub_{subcategory_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        result = await db.execute(
            text(
                "SELECT s.id, s.name, s.description, s.icon, s.subcategory_id, "
                "       s.id AS service_category_id "
                "FROM services s "
                "WHERE s.subcategory_id = :subid "
                "ORDER BY s.name"
            ),
            {"subid": subcategory_id}
        )
        rows = [dict(r._mapping) for r in result]
        _cache_set(cache_key, rows)
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving services: {str(e)}")
