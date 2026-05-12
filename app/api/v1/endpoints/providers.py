
from fastapi import APIRouter, Depends, HTTPException, Query, status, Path, File, UploadFile, Form, Body, Request
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import func
from sqlalchemy import or_, and_, update as sa_update, text
from typing import List, Optional
from datetime import datetime, timezone
import base64
import cloudinary.uploader

from app.core.database import get_db_async
from app.models.provider import Provider, ServiceProvider
from app.models.user import User
import logging
logger = logging.getLogger(__name__)

from app.schemas.provider import (
    ServiceProviderResponse,
    ServiceProviderCreateRequest,
    ServiceProviderCreateResponse,
    ServiceProviderCreate,
    ProviderRegister,
    ProviderResponse,
    ProviderUpdateRequest,
    ServiceProviderUpdateRequest
)
from app.services.provider_service import ProviderService
from app.services.geolocation_service import GeolocationService
from app.services.provider_search_service import search_providers
from app.infra.redis import (
    get_provider_profile_cache, set_provider_profile_cache,
    get_nearby_providers_cache, set_nearby_providers_cache,
    get_provider_detailed_cache, set_provider_detailed_cache,
    invalidate_provider_detailed_cache, invalidate_provider_cache
)
from app.core.redis import rate_limit
from app.dependencies import get_current_active_user, get_viewer_user

# Constantes globales para evitar duplicación de literales
PROVIDER_NOT_FOUND = "Provider not found"
NO_REGISTRADO = "No registrado"
SERVICE_NOT_FOUND = "Service not found or does not belong to this provider"

router = APIRouter()


# Endpoint para validación biométrica de proveedor
@router.post("/validate-identity", response_model=ProviderResponse)
async def validate_identity(
    provider_id: int = Form(...),
    identity_document: UploadFile = File(...),
    selfie: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Recibe documento y selfie, sube a Cloudinary y actualiza el estado del proveedor a 'pending'.
    Solo el proveedor dueño del perfil puede ejecutar esta acción.
    """
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail=PROVIDER_NOT_FOUND)

    if provider.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to validate this provider")

    doc_upload = cloudinary.uploader.upload(identity_document.file, folder="providers/docs", public_id=f"provider_{provider_id}_doc")
    selfie_upload = cloudinary.uploader.upload(selfie.file, folder="providers/selfies", public_id=f"provider_{provider_id}_selfie")

    provider.identity_document_url = doc_upload.get("secure_url")
    provider.selfie_url = selfie_upload.get("secure_url")
    provider.validation_status = "pending"
    provider.validation_notes = None
    await db.commit()
    await db.refresh(provider)

    user_result = await db.execute(select(User).where(User.id == provider.user_id))
    user = user_result.scalar_one_or_none()
    return ProviderResponse(
        id=provider.id,
        user_id=provider.user_id,
        run=provider.run or NO_REGISTRADO,
        full_name=provider.full_name,
        phone=provider.phone or NO_REGISTRADO,
        avatar=provider.avatar,
        bio=provider.bio or "",
        rating_avg=provider.rating_avg,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
        email=user.email if user else "",
        status=user.status if user else "",
        identity_document_url=provider.identity_document_url,
        selfie_url=provider.selfie_url,
        validation_status=provider.validation_status,
        validation_notes=provider.validation_notes
    )


@router.get("/search", response_model=dict)
async def search_providers_endpoint(
    category: str = Query(..., description="Categoría de servicio"),
    lat: float = Query(..., description="Latitud del usuario"),
    lng: float = Query(..., description="Longitud del usuario"),
    db: AsyncSession = Depends(get_db_async)
):
    """Buscar proveedores por categoría y ubicación, con cache best-effort (TTL 45s) y rate limiting"""
    rl_key = f"rate:providers:search:{category}:{round(lat,2)}:{round(lng,2)}"
    if not rate_limit(rl_key, 30, 60):
        raise HTTPException(status_code=429, detail="Demasiadas búsquedas. Intenta en 1 minuto.")
    result = await search_providers(category, lat, lng, db)
    return result

@router.get("/me", response_model=ProviderResponse)
async def read_provider_me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
                raise HTTPException(status_code=404, detail=PROVIDER_NOT_FOUND)
    """
    if current_user.role != "PROVIDER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a provider"
        )
        
    provider_service = ProviderService(db)
    return await provider_service.get_provider_profile(current_user.id)

@router.patch("/me", response_model=ProviderResponse)
async def update_provider_me(
    update_data: ProviderUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Actualizar perfil del proveedor actual
    """
    if current_user.role != "PROVIDER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a provider"
        )
        
    provider_service = ProviderService(db)
    return await provider_service.update_provider_profile(current_user.id, update_data)


@router.get("/stats")
async def get_my_provider_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Estadísticas del proveedor autenticado."""
    if current_user.role != "PROVIDER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a provider")
    result = await db.execute(select(Provider).where(Provider.user_id == current_user.id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail=PROVIDER_NOT_FOUND)
    from app.models.booking import Booking as _Booking
    from sqlalchemy import func as _func
    from sqlalchemy import case as _case
    stats_result = await db.execute(
        select(
            _func.count().label("total"),
            _func.sum(_case((_Booking.status == "PENDING", 1), else_=0)).label("pending"),
            _func.sum(_case((_Booking.status == "COMPLETED", 1), else_=0)).label("completed"),
        ).where(_Booking.provider_id == provider.id)
    )
    row = stats_result.one()
    return {
        "total_bookings": row.total or 0,
        "pending_bookings": row.pending or 0,
        "completed_bookings": row.completed or 0,
        "total_earnings": 0.0,
        "rating_avg": float(provider.rating_avg) if provider.rating_avg else 0.0,
    }


@router.get("/validation/status")
async def get_my_validation_status(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Estado de validación de identidad del proveedor autenticado."""
    if current_user.role != "PROVIDER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a provider")
    result = await db.execute(select(Provider).where(Provider.user_id == current_user.id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail=PROVIDER_NOT_FOUND)
    return {
        "status": provider.validation_status or "not_submitted",
        "notes": provider.validation_notes,
    }


@router.post("/validate-identity/me", response_model=ProviderResponse)
async def validate_identity_me(
    identity_document: UploadFile = File(...),
    selfie: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Validación de identidad del proveedor autenticado (sin requerir provider_id en form)."""
    if current_user.role != "PROVIDER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a provider")
    result = await db.execute(select(Provider).where(Provider.user_id == current_user.id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail=PROVIDER_NOT_FOUND)
    doc_upload = cloudinary.uploader.upload(identity_document.file, folder="providers/docs", public_id=f"provider_{provider.id}_doc")
    selfie_upload = cloudinary.uploader.upload(selfie.file, folder="providers/selfies", public_id=f"provider_{provider.id}_selfie")
    provider.identity_document_url = doc_upload.get("secure_url")
    provider.selfie_url = selfie_upload.get("secure_url")
    provider.validation_status = "pending"
    provider.validation_notes = None
    await db.commit()
    await db.refresh(provider)
    user_result = await db.execute(select(User).where(User.id == provider.user_id))
    user = user_result.scalar_one_or_none()
    return ProviderResponse(
        id=provider.id, user_id=provider.user_id,
        run=provider.run or NO_REGISTRADO, full_name=provider.full_name,
        phone=provider.phone or NO_REGISTRADO, avatar=provider.avatar,
        bio=provider.bio or "", rating_avg=provider.rating_avg,
        created_at=provider.created_at, updated_at=provider.updated_at,
        email=user.email if user else "", status=user.status if user else "",
        identity_document_url=provider.identity_document_url,
        selfie_url=provider.selfie_url,
        validation_status=provider.validation_status,
        validation_notes=provider.validation_notes
    )


@router.get("/nearby", response_model=List[ServiceProviderResponse])
async def get_nearby_providers(
    lat: float = Query(..., description="Latitud del usuario"),
    lng: float = Query(..., description="Longitud del usuario"),
    radius: float = Query(10, description="Radio en kilómetros"),
    service_name: Optional[str] = Query(None, description="Nombre del servicio"),
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener proveedores cercanos a la ubicación del usuario (con cache best-effort)"""
    # Usar service_name como categoría para la key de cache (si no hay, usar 0)
    category_id = hash(service_name) if service_name else 0
    cached = get_nearby_providers_cache(category_id, lat, lng)
    if cached:
        logger.info(f"✅ [CACHE] Proveedores cercanos hit ({category_id}, {lat}, {lng})")
        return cached
    geolocation_service = GeolocationService(db)
    providers = await geolocation_service.find_nearby_providers(
        user_lat=lat,
        user_lng=lng,
        radius_km=radius,
        service_name=service_name
    )
    set_nearby_providers_cache(category_id, lat, lng, providers)
    logger.info(f"✅ [CACHE] Guardado proveedores cercanos ({category_id}, {lat}, {lng})")
    return providers

@router.get("/nearby/service/{service_id}", response_model=List[ServiceProviderResponse])
async def get_nearby_providers_by_service_id(
    lat: float = Query(..., description="Latitud del usuario"),
    lng: float = Query(..., description="Longitud del usuario"),
    radius: float = Query(10, description="Radio en kilómetros"),
    service_id: int = Path(..., description="ID del servicio"),
    skip: int = Query(0, ge=0, description="Registros a omitir (paginación)"),
    limit: int = Query(10, ge=1, le=50, description="Máximo de registros a devolver"),
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener proveedores cercanos por ID de servicio (paginado)"""
    geolocation_service = GeolocationService(db)
    providers = await geolocation_service.find_nearby_providers_by_service_id(
        user_lat=lat,
        user_lng=lng,
        radius_km=radius,
        service_id=service_id,
        skip=skip,
        limit=limit,
    )
    return providers

@router.get("/geocoding/search")
async def geocoding_search(
    request: Request,
    q: str = Query(..., min_length=3, max_length=200, description="Dirección o lugar"),
    country: str = Query("cl", description="Código de país ISO 3166-1 alpha-2")
):
    """
    Proxy Nominatim (OpenStreetMap) con cache Redis 7 días.
    - Devuelve formato compatible con Mapbox: {text, address, place_name, center, place_type}
    - place_name = "Calle Número, Comuna, Ciudad" (limpio, sin región ni código postal)
    - Fallback: si el query termina en número y no hay resultados, busca solo la calle
      e inyecta el número del usuario → el dropdown nunca desaparece al escribir numeración
    """
    import hashlib
    import re
    import aiohttp as _aiohttp
    from app.core.redis import cache_get, cache_set

    # ── Cache check PRIMERO — los hits nunca tocan rate limit ni Nominatim ──
    q_normalized = q.lower().strip()
    key_hash = hashlib.sha256(q_normalized.encode()).hexdigest()[:20]
    cache_key = f"geo:nominatim:{key_hash}:{country}"

    cached = cache_get(cache_key)
    if cached:
        return {"source": "cache", "results": cached}

    # ── Rate limit solo en cache misses (llamadas reales a Nominatim) ────────
    # Por IP: máx 3 búsquedas nuevas/s por usuario (no bloquea a otros usuarios)
    client_ip = (request.client.host if request.client else "unknown").replace(":", "_")
    if not rate_limit(f"rate:geo:ip:{client_ip}", 3, 1):
        raise HTTPException(
            status_code=429,
            detail="Geocoding rate limit. Reintenta en 1 segundo."
        )
    # Global: respetar política de Nominatim desde nuestro servidor (1 req/s por IP pública)
    # Relajado a 5 porque con cache 7 días los misses reales son infrecuentes
    if not rate_limit("rate:nominatim:global", 5, 1):
        raise HTTPException(
            status_code=429,
            detail="Servicio de geocoding saturado. Reintenta en 1 segundo."
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    async def _fetch_nominatim(session: _aiohttp.ClientSession, query_str: str) -> list:
        """Llama a Nominatim y retorna lista raw (puede ser vacía)."""
        try:
            async with session.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": query_str,
                    "countrycodes": country,
                    "format": "json",
                    "addressdetails": 1,
                    "limit": 8,
                    "accept-language": "es",
                },
                headers={
                    "User-Agent": "BappSearch/1.0 (soporte@bappsearch.com)",
                    "Accept": "application/json",
                },
                timeout=_aiohttp.ClientTimeout(total=5),
            ) as resp:
                return await resp.json()
        except Exception:
            return []

    def _build_result(r: dict, forced_number: str = "") -> dict:
        """
        Construye un objeto compatible con Mapbox a partir de un resultado Nominatim.
        - text   = nombre de la calle (sin número) → getSuggestionDisplayText usa text + address
        - address = número (house_number)            → igual que Mapbox
        - place_name = "Calle Número, Comuna, Ciudad" → getSuggestionContext extrae la parte tras la primera coma
        - place_type = lista de tipos para el ícono
        """
        addr = r.get("address", {})

        # Nombre de la calle (varios alias posibles en OSM)
        road = (
            addr.get("road")
            or addr.get("pedestrian")
            or addr.get("footway")
            or addr.get("path")
            or addr.get("cycleway")
            or ""
        )

        # Número: forzado (fallback) o el que trae Nominatim
        house_number = forced_number or addr.get("house_number", "")

        # Comuna / barrio
        suburb = (
            addr.get("suburb")
            or addr.get("city_district")
            or addr.get("neighbourhood")
            or addr.get("quarter")
            or ""
        )

        # Ciudad
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("county")
            or ""
        )

        # Armar place_name limpio: "Calle 123, Ñuñoa, Santiago"
        street_part = f"{road} {house_number}".strip() if road else house_number
        label_parts = [p for p in [street_part, suburb, city if city != suburb else ""] if p]
        place_name = ", ".join(label_parts) if label_parts else r.get("display_name", "").split(",")[0].strip()

        return {
            "place_name": place_name,
            "text": road,                          # Solo nombre de calle → getSuggestionDisplayText
            "address": house_number,               # Solo número          → getSuggestionDisplayText
            "center": [float(r["lon"]), float(r["lat"])],
            "relevance": float(r.get("importance", 0)),
            "place_type": [r.get("type", "address")],
        }

    # ── Llamada principal ──────────────────────────────────────────────────

    try:
        async with _aiohttp.ClientSession() as session:
            raw = await _fetch_nominatim(session, q)

            # Fallback: query sin resultados que termina en número
            # → Nominatim no tiene numeración casa a casa en Chile
            # → Buscar solo la calle e inyectar el número del usuario
            forced_number = ""
            if not raw:
                number_match = re.search(r'^(.+?)\s+(\d+)\s*$', q.strip())
                if number_match:
                    street_only = number_match.group(1).strip()
                    forced_number = number_match.group(2)
                    if len(street_only) >= 3:
                        raw = await _fetch_nominatim(session, street_only)

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Servicio de geocoding no disponible: {str(e)}"
        )

    results = [
        _build_result(r, forced_number=forced_number)
        for r in raw
        if "lat" in r and "lon" in r
    ]

    cache_set(cache_key, results, ttl=604800)  # 7 días
    return {"source": "api", "results": results}


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener información detallada de un proveedor (con cache best-effort)"""
    # Incrementar contador de vistas al perfil (fail-open, no bloquea respuesta)
    try:
        from app.infra.redis.cache import incr_profile_views
        incr_profile_views(provider_id)
    except Exception:
        pass

    # 1. Intentar cache
    cached = get_provider_profile_cache(provider_id)
    if cached:
        logger.info(f"✅ [CACHE] Provider {provider_id} hit")
        return ProviderResponse(**cached)

    from app.models.user import User
    try:
        logger.info(f"🔍 [DB] Consultando provider con ID: {provider_id}")
        result = await db.execute(
            select(Provider, User.email, User.status)
            .join(User, Provider.user_id == User.id)
            .where(Provider.id == provider_id)
        )
        row = result.first()
        if not row:
            logger.error(f"❌ Provider no encontrado: {provider_id}")
            raise HTTPException(status_code=404, detail="Provider not found")
        provider, user_email, user_status = row
        run_value = provider.run if provider.run is not None else "No registrado"
        email = user_email if user_email else "No disponible"
        status = user_status if user_status else "ACTIVE"
        bio = provider.bio if provider.bio else ""
        phone = provider.phone if provider.phone else "No registrado"
        response_data = ProviderResponse(
            id=provider.id,
            user_id=provider.user_id,
            run=run_value,
            full_name=provider.full_name,
            phone=phone,
            avatar=provider.avatar,
            bio=bio,
            rating_avg=provider.rating_avg,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
            email=email,
            status=status
        )
        # Guardar en cache (best-effort)
        set_provider_profile_cache(provider_id, response_data.dict())
        logger.info(f"✅ [CACHE] Guardado provider {provider_id}")
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en get_provider: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback completo: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving provider: {str(e)}"
        )

@router.get("/{provider_id}/detailed")
async def get_provider_detailed(
    provider_id: int,
    db: AsyncSession = Depends(get_db_async),
    viewer: User = Depends(get_viewer_user)
):
    """
    Obtener información detallada del proveedor CON todos sus servicios asociados.
    Retorna: Provider info + List of services + Reviews count
    """
    # --- Registrar visita antes del cache (fail-open) ---
    try:
        from app.infra.redis.cache import incr_service_views
        incr_service_views(provider_id)
        logger.info(f"[tracking] /detailed provider={provider_id} viewer={'id='+str(viewer.id) if viewer else 'NONE (anónimo)'}")
        if viewer:
            from app.models.service_view_event import ServiceViewEvent
            import traceback as _tb
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            # Obtener primer servicio del proveedor (puede ser None)
            from app.models.provider import ServiceProvider as _SP
            sp_result = await db.execute(
                select(_SP.id).where(_SP.provider_id == provider_id).limit(1)
            )
            first_sp_id = sp_result.scalar_one_or_none()
            logger.info(f"[tracking] provider={provider_id} first_sp_id={first_sp_id}")
            # Deduplicar: máximo 1 evento por usuario por proveedor por día
            existing = await db.execute(
                select(ServiceViewEvent.id).where(
                    ServiceViewEvent.provider_id == provider_id,
                    ServiceViewEvent.viewer_user_id == viewer.id,
                    ServiceViewEvent.viewed_at >= today_start,
                )
            )
            if not existing.scalar_one_or_none():
                evt = ServiceViewEvent(
                    provider_id=provider_id,
                    service_provider_id=first_sp_id,  # puede ser None
                    viewer_user_id=viewer.id,
                )
                db.add(evt)
                await db.commit()
                logger.info(f"✅ ServiceViewEvent registrado: provider={provider_id} viewer={viewer.id} sp={first_sp_id}")
            else:
                logger.info(f"[tracking] visita ya registrada hoy: provider={provider_id} viewer={viewer.id}")
        else:
            logger.info(f"[tracking] visita anónima a provider={provider_id} — token no recibido o inválido")
    except Exception as e:
        import traceback as _tb
        logger.warning(f"⚠️ Error registrando visita en /detailed: {e}\n{_tb.format_exc()}")

    # --- Cache first ---
    cached = get_provider_detailed_cache(provider_id)
    if cached:
        logger.info(f"[CACHE] provider:detailed:{provider_id} HIT")
        return cached

    try:
        logger.info(f"🔍 [DB] Consultando provider detallado con ID: {provider_id}")
        
        # 1. Obtener datos del provider
        result = await db.execute(
            select(Provider, User.email, User.status)
            .join(User, Provider.user_id == User.id)
            .where(Provider.id == provider_id)
        )
        row = result.first()
        
        if not row:
            logger.error(f"❌ Provider no encontrado: {provider_id}")
            raise HTTPException(status_code=404, detail="Provider not found")
        
        provider, user_email, user_status = row
        
        logger.info(f"✅ Provider encontrado: {provider.id}")
        
        # 2. Obtener servicios del provider
        from app.models.provider import ServiceProvider
        services_result = await db.execute(
            select(ServiceProvider)
            .options(selectinload(ServiceProvider.service_category))
            .where(ServiceProvider.provider_id == provider_id)
        )
        services = services_result.scalars().all()
        
        logger.info(f"✅ Servicios encontrados: {len(services)}")
        
        # 3. Obtener conteo de reviews
        from app.models.review import Review
        reviews_result = await db.execute(
            select(func.count(Review.id))
            .where(Review.provider_id == provider_id)
        )
        total_reviews = reviews_result.scalar() or 0
        
        logger.info(f"✅ Total de reviews: {total_reviews}")
        
        # 4. avatar es VARCHAR(500) con URL de Cloudinary
        avatar_value = provider.avatar
        
        # 5. Mapear servicios a respuesta
        services_list = []
        for service in services:
            service_dict = {
                'id': service.id,
                'service_provider_id': service.id,
                'provider_user_id': provider.user_id,
                'avatar': avatar_value,
                'provider_id': service.provider_id,
                'user_id': provider.user_id,  # ✅ AGREGADO: User ID para chat
                'service_id': service.service_id,
                'business_name': service.business_name,
                'full_name': provider.full_name,
                'description': service.description,
                'address': service.address,
                'latitude': service.latitude,
                'longitude': service.longitude,
                'distance': 0,  # Se calcula en frontend si es necesario
                'phone': service.phone,
                'hourly_rate': service.hourly_rate,
                'is_available': service.is_available,
                'validation_status': service.validation_status,
                'rating_avg': provider.rating_avg,
                'total_reviews': total_reviews,
                'created_at': service.created_at,
                'service_category': None
            }
            
            # Agregar categoría si existe
            if service.service_category:
                service_dict['service_category'] = {
                    'id': service.service_category.id,
                    'name': service.service_category.name,
                    'description': service.service_category.description,
                    'icon': service.service_category.icon,
                    'parent_category': service.service_category.parent_category,
                    'is_active': service.service_category.is_active,
                    'main_category_id': service.service_category.main_category_id,
                    'created_at': service.service_category.created_at
                }
            
            services_list.append(service_dict)
        
        # 6. Construir respuesta final
        from app.schemas.provider import ProviderDetailedResponse
        
        response = {
            'id': provider.id,
            'user_id': provider.user_id,
            'run': provider.run or "No registrado",
            'full_name': provider.full_name,
            'phone': provider.phone or "No registrado",
            'avatar': avatar_value,
            'bio': provider.bio or "",
            'rating_avg': provider.rating_avg,
            'total_reviews': total_reviews,
            'email': user_email or "No disponible",
            'status': user_status or "ACTIVE",
            'business_name': None,  # Provider no tiene business_name; está en cada ServiceProvider
            'services': services_list,
            'created_at': provider.created_at,
            'updated_at': provider.updated_at
        }
        
        logger.info(f"✅ Respuesta detallada preparada para provider {provider_id}")

        # --- Cache the result ---
        try:
            import json
            json.dumps(response, default=str)  # test serializable
            set_provider_detailed_cache(provider_id, response)
        except Exception:
            pass  # fail-open: no romper respuesta si cache falla
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en get_provider_detailed: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving provider details: {str(e)}"
        )

@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int,
    provider_data: ProviderUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Actualizar información del proveedor"""
    try:
        logger.info(f"🔍 Actualizando provider con ID: {provider_id}")
        
        # Primero obtener el provider existente
        result = await db.execute(
            select(Provider)
            .join(User, Provider.user_id == User.id)
            .where(Provider.id == provider_id)
        )
        row = result.first()
        
        if not row:
            logger.error(f"❌ Provider no encontrado: {provider_id}")
            raise HTTPException(status_code=404, detail="Provider not found")
        
        provider, user = row[0], None
        if len(row) > 1:
            user = row[1]

        # Verificar ownership: el provider debe pertenecer al usuario autenticado
        if provider.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this provider profile"
            )

        # Si no obtuvimos el user en la consulta, lo buscamos por separado
        if not user:
            user_result = await db.execute(
                select(User).where(User.id == provider.user_id)
            )
            user = user_result.scalar_one_or_none()
        
        if not user:
            logger.error(f"❌ User no encontrado para provider: {provider_id}")
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"✅ Provider y User encontrados para actualización")

        # Actualizar campos del Provider
        if provider_data.full_name is not None:
            provider.full_name = provider_data.full_name
        if provider_data.phone is not None:
            provider.phone = provider_data.phone
        if provider_data.run is not None:
            provider.run = provider_data.run
        if provider_data.bio is not None:
            provider.bio = provider_data.bio
        
        # Procesar avatar si se proporciona: subir a Cloudinary
        if provider_data.avatar is not None:
            if provider_data.avatar == "":  # Si es string vacío, eliminar avatar
                provider.avatar = None
                logger.info("🗑️ Avatar eliminado")
            else:
                try:
                    from app.infra.storage.cloudinary_storage import CloudinaryStorage
                    storage = CloudinaryStorage()
                    
                    # Decodificar base64 a bytes
                    if provider_data.avatar.startswith('data:image'):
                        base64_data = provider_data.avatar.split(',', 1)[1]
                    else:
                        base64_data = provider_data.avatar
                    
                    padding = 4 - (len(base64_data) % 4)
                    if padding != 4:
                        base64_data += '=' * padding
                    
                    file_bytes = base64.b64decode(base64_data)
                    
                    # Subir a Cloudinary
                    upload_result = await storage.upload_file(
                        file_bytes=file_bytes,
                        filename=f"avatar_{provider_id}.jpg",
                        folder=f"providers/{provider_id}/avatar",
                        resource_type="image",
                        public_id=f"provider_{provider_id}_avatar"
                    )
                    
                    provider.avatar = upload_result.secure_url
                    logger.info(f"✅ Avatar subido a Cloudinary: {provider.avatar}")
                    
                except Exception as e:
                    logger.error(f"❌ Error subiendo avatar a Cloudinary: {e}")
                    import traceback
                    logger.error(f"❌ Traceback: {traceback.format_exc()}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Error uploading avatar"
                    )
        
        # Actualizar campos del User
        if provider_data.email is not None:
            # Verificar que el email no esté en uso por otro usuario
            if provider_data.email != user.email:
                email_check = await db.execute(
                    select(User).where(
                        User.email == provider_data.email,
                        User.id != user.id
                    )
                )
                existing_user = email_check.scalar_one_or_none()
                if existing_user:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already in use by another user"
                    )
            user.email = provider_data.email
        
        if provider_data.status is not None:
            user.status = provider_data.status
        
        # Actualizar timestamps
        provider.updated_at = func.now()
        user.updated_at = func.now()
        
        await db.commit()
        
        # Invalidar cache del proveedor tras actualización
        try:
            invalidate_provider_cache(provider_id)
            invalidate_provider_detailed_cache(provider_id)
            logger.info(f"[CACHE] Invalidated provider:{provider_id} caches")
        except Exception:
            pass  # fail-open
        
        # Refrescar los datos
        await db.refresh(provider)
        await db.refresh(user)
        
        logger.info(f"✅ Provider actualizado exitosamente: {provider_id}")
        
        # Retornar respuesta actualizada
        return ProviderResponse(
            id=provider.id,
            user_id=provider.user_id,
            run=provider.run or "No registrado",
            full_name=provider.full_name,
            phone=provider.phone or "No registrado",
            avatar=provider.avatar,
            bio=provider.bio or "",
            rating_avg=provider.rating_avg,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
            email=user.email,
            status=user.status
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error en update_provider: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback completo: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating provider: {str(e)}"
        )
    
@router.put("/{provider_id}/availability")
async def update_provider_availability(
    provider_id: int,
    is_available: bool,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Actualizar disponibilidad de todos los servicios del proveedor"""
    # Verificar que el provider pertenece al usuario autenticado
    provider_result = await db.execute(
        select(Provider).where(
            Provider.id == provider_id,
            Provider.user_id == current_user.id
        )
    )
    if not provider_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=PROVIDER_NOT_FOUND)

    # Actualizar is_available en todos los servicios del proveedor
    await db.execute(
        sa_update(ServiceProvider)
        .where(ServiceProvider.provider_id == provider_id)
        .values(is_available=is_available)
    )
    await db.commit()
    try:
        invalidate_provider_detailed_cache(provider_id)
    except Exception:
        pass  # fail-open
    return {"message": "Availability updated successfully"}

@router.get("/{provider_id}/reviews")
async def get_provider_reviews(
    provider_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener reseñas de un proveedor"""
    # Implementar lógica para obtener reseñas
    return {"reviews": []}

@router.post("/services", response_model=ServiceProviderCreateResponse)
async def create_service_provider(
    service_data: ServiceProviderCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Crear un nuevo servicio para un proveedor
    """
    try:
        logger.info(f"🔍 Datos recibidos en el backend: {service_data}")
        
        # Obtener el provider directamente
        from sqlalchemy.future import select
        from sqlalchemy import text
        from app.models.provider import Provider
        
        # Buscar el provider del usuario autenticado (no confiar en id_contacto del body)
        logger.info(f"🎯 Buscando provider para current_user.id: {current_user.id}")

        result = await db.execute(
            select(Provider).where(Provider.user_id == current_user.id)
        )
        provider = result.scalar_one_or_none()

        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider profile not found for this user"
            )
        
        # DEPURACIÓN: Verificar qué provider se encontró
        logger.info(f"✅ Provider encontrado:")
        logger.info(f"   - Provider ID: {provider.id}")
        logger.info(f"   - User ID: {provider.user_id}")
        logger.info(f"   - Full Name: {provider.full_name}")
        logger.info(f"🎯 Usando provider_id={provider.id} para crear el servicio")

        # 2.6 ── Validar que el proveedor haya completado la verificación de identidad
        from app.models.document import ProviderVerification
        verification_result = await db.execute(
            select(ProviderVerification).where(
                ProviderVerification.provider_id == provider.id
            )
        )
        verification = verification_result.scalar_one_or_none()
        
        if not verification or verification.face_match_status != "APPROVED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Debes completar y aprobar la verificación de identidad antes de agregar servicios. Por favor, sube tu selfie y documento de identidad en la sección de verificación."
            )

        # 2.7 ── Contar servicios existentes del proveedor
        # Los primeros 2 se crean con "approved" (gratuitos), los siguientes con "pending"
        count_result = await db.execute(
            text("SELECT COUNT(*) FROM service_providers WHERE provider_id = :pid"),
            {"pid": provider.id}
        )
        service_count = count_result.scalar() or 0

        # Los primeros 2 servicios se aprueban automáticamente; los demás quedan pendientes
        new_validation_status = "approved" if service_count < 2 else "pending"

        # Crear el servicio via raw SQL para evitar el type mismatch de asyncpg
        # con columnas geometry(Point,4326) de PostGIS/geoalchemy2.
        # La columna `location` se omite intencionalmente: el trigger
        # trg_sync_provider_location la calcula desde latitude/longitude.

        insert_result = await db.execute(
            text("""
                INSERT INTO service_providers
                    (provider_id, service_id, business_name, description, address,
                     latitude, longitude, phone, hourly_rate, is_available,
                     validation_status, rating_avg, total_reviews,
                     created_at, updated_at)
                VALUES
                    (:provider_id, :service_id, :business_name, :description, :address,
                     :latitude, :longitude, :phone, :hourly_rate, :is_available,
                     :validation_status, 0.0, 0,
                     now(), now())
                RETURNING id, created_at, updated_at
            """),
            {
                "provider_id":    provider.id,
                "service_id":     int(service_data.categoria),
                "business_name":  service_data.nombre_prestador,
                "description":    service_data.detalle or "",
                "address":        service_data.direccion,
                "latitude":       float(service_data.lat),
                "longitude":      float(service_data.lng),
                "phone":          service_data.fono,
                "hourly_rate":    None,
                "is_available":   new_validation_status == "approved",
                "validation_status": new_validation_status,
            }
        )
        row = insert_result.fetchone()
        new_service_id = row.id
        new_created_at = row.created_at

        await db.commit()

        logger.info(f"✅ Servicio creado exitosamente:")
        logger.info(f"   - Service ID: {new_service_id}")
        logger.info(f"   - Provider ID: {provider.id}")

        return ServiceProviderCreateResponse(
            id=new_service_id,
            provider_id=provider.id,
            service_id=int(service_data.categoria),
            business_name=service_data.nombre_prestador,
            description=service_data.detalle or "",
            address=service_data.direccion,
            latitude=service_data.lat,
            longitude=service_data.lng,
            phone=service_data.fono,
            hourly_rate=None,
            is_available=new_validation_status == "approved",
            validation_status=new_validation_status,
            created_at=new_created_at
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error en create_service_provider: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback completo: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating service: {str(e)}"
        )

# ⚠️ IMPORTANTE: Poner rutas MÁS ESPECÍFICAS PRIMERO (con más parámetros)
# Esto va ANTES de /providers/services/{provider_id} porque es más específica

@router.patch("/provider-services/{service_id}")
async def toggle_service_availability(
    service_id: int,
    is_available: bool = Body(..., embed=True),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Habilitar / deshabilitar un servicio.
    - Deshabilitar (is_available=false): pone validation_status="pending"
    - Habilitar (is_available=true):
        * Si el proveedor tiene < 2 servicios "approved" → aprueba directamente
        * Si tiene >= 2 → verifica slot de pago activo en provider_service_slots
          · Con slot activo → aprueba
          · Sin slot activo → HTTP 402 para que el frontend muestre la oferta
    """
    try:
        from sqlalchemy.future import select
        from app.models.provider import ServiceProvider, Provider, ValidationStatus

        # Verificar que el servicio pertenece al proveedor del usuario autenticado
        provider_result = await db.execute(
            select(Provider).where(Provider.user_id == current_user.id)
        )
        provider = provider_result.scalar_one_or_none()
        if not provider:
            raise HTTPException(status_code=404, detail="Provider no encontrado")

        sp_result = await db.execute(
            select(ServiceProvider).where(
                ServiceProvider.id == service_id,
                ServiceProvider.provider_id == provider.id
            )
        )
        service_provider = sp_result.scalar_one_or_none()
        if not service_provider:
            raise HTTPException(status_code=404, detail="Servicio no encontrado")

        if not is_available:
            # ── Deshabilitar: SQL directo para garantizar el UPDATE ──────────
            await db.execute(
                text(
                    "UPDATE service_providers "
                    "SET is_available = FALSE, validation_status = 'pending' "
                    "WHERE id = :sid AND provider_id = :pid"
                ),
                {"sid": service_id, "pid": provider.id}
            )
            new_is_available = False
            new_validation_status = "pending"
        else:
            # ── Habilitar: verificar límite gratuito o plan activo ───────────

            # Contar servicios activos del proveedor (excluir el propio)
            approved_result = await db.execute(
                text(
                    "SELECT COUNT(*) FROM service_providers "
                    "WHERE provider_id = :pid AND is_available = TRUE AND id != :sid"
                ),
                {"pid": provider.id, "sid": service_id}
            )
            approved_count = approved_result.scalar() or 0

            if approved_count < 2:
                # Tiene cupo gratuito disponible
                await db.execute(
                    text(
                        "UPDATE service_providers "
                        "SET is_available = TRUE, validation_status = 'approved' "
                        "WHERE id = :sid AND provider_id = :pid"
                    ),
                    {"sid": service_id, "pid": provider.id}
                )
                new_is_available = True
                new_validation_status = "approved"
            else:
                # Necesita plan activo — verificar provider_service_slots
                slot_result = await db.execute(
                    text(
                        "SELECT id FROM provider_service_slots "
                        "WHERE provider_id = :pid "
                        "  AND service_provider_id = :sid "
                        "  AND is_active = TRUE "
                        "  AND (expires_at IS NULL OR expires_at > now()) "
                        "LIMIT 1"
                    ),
                    {"pid": provider.id, "sid": service_id}
                )
                active_slot = slot_result.fetchone()

                if not active_slot:
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail="PLAN_REQUIRED"
                    )

                await db.execute(
                    text(
                        "UPDATE service_providers "
                        "SET is_available = TRUE, validation_status = 'approved' "
                        "WHERE id = :sid AND provider_id = :pid"
                    ),
                    {"sid": service_id, "pid": provider.id}
                )
                new_is_available = True
                new_validation_status = "approved"

        await db.commit()

        logger.info(
            f"✅ Servicio {service_id} → is_available={new_is_available} "
            f"validation_status={new_validation_status}"
        )

        return {
            "id": service_id,
            "is_available": new_is_available,
            "validation_status": new_validation_status,
            "business_name": service_provider.business_name,
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error toggle_service_availability: {e}")
        raise HTTPException(status_code=500, detail=f"Error actualizando disponibilidad: {str(e)}")


@router.get("/{provider_id}/services/{service_id}", response_model=ServiceProviderResponse)
async def get_provider_service(
    provider_id: int,
    service_id: int,
    db: AsyncSession = Depends(get_db_async),
    viewer: User = Depends(get_viewer_user),
):
    """
    Obtener un servicio específico de un proveedor CON información de contacto del provider
    Retorna: datos del servicio + información de contacto + avatar + rating + reviews del provider
    """
    try:
        from sqlalchemy.future import select
        
        logger.info(f"🔍 Consultando servicio {service_id} del proveedor {provider_id}")
        
        # 1. Obtener el servicio — service_id es el PK de service_providers (ServiceProvider.id)
        result = await db.execute(
            select(ServiceProvider)
            .options(selectinload(ServiceProvider.service_category))
            .where(
                ServiceProvider.id == service_id,
                ServiceProvider.provider_id == provider_id
            )
        )
        service_provider = result.scalars().first()
        
        if not service_provider:
            logger.error(f"❌ Servicio {service_id} no encontrado para proveedor {provider_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service not found or does not belong to this provider"
            )
        
        logger.info(f"✅ Servicio encontrado: {service_provider.business_name}")

        # Incrementar contador Redis (fail-open)
        try:
            from app.infra.redis.cache import incr_service_views
            incr_service_views(service_provider.provider_id)
        except Exception:
            pass

        # Registrar evento de visita en BD (fail-open, deduplicado por día)
        if viewer is not None:
            try:
                from app.models.service_view_event import ServiceViewEvent
                from sqlalchemy import and_ as _and, cast as _cast, Date as _Date, func as _func
                # Evitar duplicados: un usuario genera un evento por servicio por día
                today_start = _func.date_trunc("day", _func.now())
                dup = await db.execute(
                    select(ServiceViewEvent.id).where(
                        _and(
                            ServiceViewEvent.service_provider_id == service_provider.id,
                            ServiceViewEvent.viewer_user_id == viewer.id,
                            ServiceViewEvent.viewed_at >= today_start,
                        )
                    )
                )
                if dup.scalar_one_or_none() is None:
                    evt = ServiceViewEvent(
                        provider_id=service_provider.provider_id,
                        service_provider_id=service_provider.id,
                        viewer_user_id=viewer.id,
                    )
                    db.add(evt)
                    await db.flush()   # no commit aquí, se hace al final del request
            except Exception:
                pass

        # 2. Obtener datos del proveedor (Provider)
        provider_result = await db.execute(
            select(Provider, User.email, User.status)
            .join(User, Provider.user_id == User.id)
            .where(Provider.id == provider_id)
        )
        provider_row = provider_result.first()
        
        if not provider_row:
            logger.warning(f"⚠️ Provider {provider_id} no encontrado, retornando solo datos del servicio")
            # Si no encontramos el provider, retornamos solo el servicio
            return service_provider
        
        provider, user_email, user_status = provider_row
        logger.info(f"✅ Provider encontrado: {provider.full_name}")
        
        # 3. Obtener conteo de reviews del provider
        from app.models.review import Review
        reviews_result = await db.execute(
            select(func.count(Review.id))
            .where(Review.provider_id == provider_id)
        )
        total_reviews = reviews_result.scalar() or 0
        logger.info(f"📊 Total reviews: {total_reviews}")
        
        # 4. avatar es VARCHAR(500) con URL de Cloudinary
        
        # 5. Construir respuesta enriquecida con datos del provider
        response_dict = {
            'id': service_provider.id,
            'avatar': provider.avatar,
            'provider_id': service_provider.provider_id,
            'user_id': provider.user_id,  # ✅ AGREGADO: User ID del proveedor para chat
            'service_id': service_provider.service_id,
            'business_name': service_provider.business_name,
            'full_name': provider.full_name,  # Nombre del proveedor
            'description': service_provider.description,
            'address': service_provider.address,
            'latitude': service_provider.latitude,
            'longitude': service_provider.longitude,
            'distance': 0,  # Se calcula en frontend si es necesario
            'phone': service_provider.phone,  # Teléfono del servicio
            'hourly_rate': service_provider.hourly_rate,
            'is_available': service_provider.is_available,
            'validation_status': service_provider.validation_status,
            'rating_avg': provider.rating_avg,  # Rating del provider
            'total_reviews': total_reviews,  # Reviews del provider
            'created_at': service_provider.created_at,
            'service_category': None
        }
        
        # 6. Agregar categoría si existe
        if service_provider.service_category:
            response_dict['service_category'] = {
                'id': service_provider.service_category.id,
                'name': service_provider.service_category.name,
                'description': service_provider.service_category.description,
                'icon': service_provider.service_category.icon,
                'parent_category': service_provider.service_category.parent_category,
                'is_active': service_provider.service_category.is_active,
                'main_category_id': service_provider.service_category.main_category_id,
                'created_at': service_provider.service_category.created_at
            }
        
        # 7. Retornar respuesta enriquecida
        logger.info(f"✅ Respuesta completa lista para servicio {service_id}")
        return ServiceProviderResponse(**response_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en get_provider_service: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting service: {str(e)}"
        )


@router.get("/services/{provider_id}", response_model=List[ServiceProviderResponse])
async def get_provider_services(
    provider_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener todos los servicios de un proveedor
    """
    from sqlalchemy.future import select
    
    # FIXED: Use eager loading to avoid lazy loading issues
    result = await db.execute(
        select(ServiceProvider)
        .options(selectinload(ServiceProvider.service_category))
        .where(ServiceProvider.provider_id == provider_id)
    )
    services = result.scalars().all()
    
    return services

# Agrega este endpoint en providers.py (antes o después del endpoint GET similar)

@router.put("/{provider_id}/services/{service_id}", response_model=ServiceProviderResponse)
async def update_service_provider(
    provider_id: int,
    service_id: int,  # PK de service_providers (ServiceProvider.id), no FK de service_categories
    update_data: ServiceProviderUpdateRequest,
    db: AsyncSession = Depends(get_db_async)
):
    """
    Actualizar un servicio específico de un proveedor.
    service_id en la URL corresponde al PK de service_providers (ServiceProvider.id).
    """
    try:
        logger.info(f"🔍 Actualizando servicio {service_id} del proveedor {provider_id}")

        result = await db.execute(
            select(ServiceProvider)
            .options(selectinload(ServiceProvider.service_category))
            .where(
                ServiceProvider.id == service_id,
                ServiceProvider.provider_id == provider_id
            )
        )
        service_provider = result.scalar_one_or_none()

        if not service_provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=SERVICE_NOT_FOUND
            )

        logger.info(f"✅ Servicio encontrado: {service_provider.business_name}")
        
        # Actualizar solo los campos proporcionados
        if update_data.business_name is not None:
            service_provider.business_name = update_data.business_name
        
        if update_data.description is not None:
            service_provider.description = update_data.description
        
        if update_data.address is not None:
            service_provider.address = update_data.address
        
        if update_data.latitude is not None:
            service_provider.latitude = update_data.latitude
        
        if update_data.longitude is not None:
            service_provider.longitude = update_data.longitude
        
        if update_data.phone is not None:
            service_provider.phone = update_data.phone
        
        # Actualizar timestamp
        service_provider.updated_at = func.now()
        
        await db.commit()
        await db.refresh(service_provider)
        
        logger.info(f"✅ Servicio actualizado exitosamente: {service_id}")

        return service_provider

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error en update_service_provider: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback completo: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating service: {str(e)}"
        )

@router.delete("/{provider_id}/services/{service_id}")
async def delete_service_provider(
    provider_id: int,
    service_id: int,  # PK de service_providers (ServiceProvider.id)
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Eliminar un servicio específico de un proveedor.
    service_id en la URL corresponde al PK de service_providers (ServiceProvider.id).
    """
    try:
        logger.info(f"🗑️  Eliminando servicio {service_id} del proveedor {provider_id}")

        # 0. Verificar ownership: el provider debe pertenecer al usuario autenticado
        owner_result = await db.execute(
            select(Provider).where(
                Provider.id == provider_id,
                Provider.user_id == current_user.id
            )
        )
        if not owner_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete services from this provider"
            )

        # 1. Verificar que el servicio pertenece al proveedor
        check_query = text("""
            SELECT business_name 
            FROM service_providers 
            WHERE id = :service_id AND provider_id = :provider_id
        """)
        
        check_result = await db.execute(
            check_query,
            {"service_id": service_id, "provider_id": provider_id}
        )
        
        service = check_result.fetchone()
        
        if not service:
            logger.error(f"❌ Servicio {service_id} no encontrado para el proveedor {provider_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service not found or does not belong to this provider"
            )
        
        logger.info(f"✅ Servicio encontrado: {service[0]}")
        
        # 2. Contar reviews del proveedor (reviews.provider_id es FK a providers.id)
        review_check = text("""
            SELECT COUNT(*)
            FROM reviews
            WHERE provider_id = :provider_id
        """)

        review_result = await db.execute(
            review_check,
            {"provider_id": provider_id}
        )
        
        review_count = review_result.scalar()
        logger.info(f"📊 Reviews asociadas: {review_count}")
        
        # 3. Eliminar el servicio (cascade debería manejar las reviews)
        delete_query = text("""
            DELETE FROM service_providers 
            WHERE id = :service_id AND provider_id = :provider_id
        """)
        
        result = await db.execute(
            delete_query,
            {"service_id": service_id, "provider_id": provider_id}
        )
        
        await db.commit()
        
        rows_deleted = result.rowcount
        logger.info(f"✅ Eliminación completada. Filas afectadas: {rows_deleted}")
        
        if rows_deleted == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No rows were deleted - possible database constraint"
            )
        
        return {
            "message": "Service deleted successfully",
            "service_id": service_id,
            "reviews_deleted": review_count
        }
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Error crítico: {str(e)}")
        import traceback
        logger.info(f"🔍 Traceback completo:\n{traceback.format_exc()}")
        
        # Verificar si es error de foreign key
        if "foreign key constraint" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete service because it has related records (bookings or reviews)"
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting service: {str(e)}"
        )

@router.get("/user/{user_id}/services", response_model=List[ServiceProviderResponse])
async def get_provider_services_by_user_id(
    user_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener servicios de un proveedor por user_id
    """
    from sqlalchemy.future import select
    
    logger.info(f"\n🔍 GET /user/{user_id}/services")
    logger.info(f"   - User ID solicitado: {user_id}")
    
    # Primero obtener el provider_id
    provider_service = ProviderService(db)
    provider = await provider_service.get_provider_by_user_id(user_id)
    
    logger.info(f"   - Provider encontrado: {provider}")
    
    if not provider:
        logger.error(f"   - ❌ Provider no encontrado para user_id {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found"
        )
    
    logger.info(f"   - ✅ Provider ID: {provider.id}, User ID: {provider.user_id}")
    
    # FIXED: Use eager loading
    result = await db.execute(
        select(ServiceProvider)
        .options(selectinload(ServiceProvider.service_category))
        .where(ServiceProvider.provider_id == provider.id)
    )
    services = result.scalars().all()
    
    logger.info(f"   - 📊 Servicios encontrados: {len(services)}")
    for svc in services:
        logger.info(f"      • Service ID: {svc.id}, Provider ID: {svc.provider_id}, Business: {svc.business_name}")
    
    return services

@router.get("/{provider_id}/stats")
async def get_provider_stats(
    provider_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Estadísticas del proveedor para el dashboard:
    - Servicios: total, activos (approved), pendientes (pending)
    - Reservas: total, completadas, pendientes
    - Rating promedio
    - Vistas al perfil y a servicios (contadores Redis)
    """
    from app.infra.redis.cache import get_profile_views, get_service_views

    try:
        # ── Servicios ─────────────────────────────────────────────────────────
        svc_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE validation_status = 'approved') AS active,
                    COUNT(*) FILTER (WHERE validation_status = 'pending')  AS pending
                FROM service_providers
                WHERE provider_id = :pid
            """),
            {"pid": provider_id}
        )
        svc_row = svc_result.fetchone()
        total_services  = svc_row.total  if svc_row else 0
        active_services = svc_row.active if svc_row else 0
        pending_services = svc_row.pending if svc_row else 0

        # ── Reservas ──────────────────────────────────────────────────────────
        bk_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED') AS completed,
                    COUNT(*) FILTER (WHERE status = 'PENDING')   AS pending
                FROM bookings
                WHERE provider_id = :pid
            """),
            {"pid": provider_id}
        )
        bk_row = bk_result.fetchone()
        total_bookings     = bk_row.total     if bk_row else 0
        completed_bookings = bk_row.completed if bk_row else 0
        pending_bookings   = bk_row.pending   if bk_row else 0

        # ── Rating promedio ───────────────────────────────────────────────────
        rating_result = await db.execute(
            text("SELECT rating_avg FROM providers WHERE id = :pid"),
            {"pid": provider_id}
        )
        rating_row = rating_result.fetchone()
        average_rating = float(rating_row.rating_avg) if rating_row and rating_row.rating_avg else 0.0

        # ── Vistas (contadores Redis) ─────────────────────────────────────────
        profile_views = get_profile_views(provider_id)
        service_views = get_service_views(provider_id)

        return {
            "total_services":     int(total_services),
            "active_services":    int(active_services),
            "pending_services":   int(pending_services),
            "total_bookings":     int(total_bookings),
            "completed_bookings": int(completed_bookings),
            "pending_bookings":   int(pending_bookings),
            "total_earnings":     0,   # se calculará cuando haya sistema de pagos finalizado
            "average_rating":     average_rating,
            "profile_views":      profile_views,
            "service_views":      service_views,
            "zone_searches":      0,   # requiere instrumentación adicional de búsquedas
        }

    except Exception as e:
        logger.error(f"❌ Error en get_provider_stats: {e}")
        import traceback
        logger.info(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error obteniendo estadísticas: {str(e)}")


@router.get("/{provider_id}/avatar")
async def get_provider_avatar(
    provider_id: int,
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener avatar de un proveedor"""
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    
    if not provider or not provider.avatar:
        raise HTTPException(status_code=404, detail="Avatar no encontrado")
    
    # avatar es VARCHAR(500) con URL de Cloudinary
    return {
        "avatar": provider.avatar,
        "provider_id": provider_id
    }

# ─── Búsqueda por texto libre ──────────────────────────────────────────────

from sqlalchemy import or_, and_
from app.models.service_category import ServiceCategory


@router.get("/text-search", response_model=List[ServiceProviderResponse])
async def text_search_providers(
    q: str = Query(..., min_length=2, max_length=100, description="Término de búsqueda"),
    page: int = Query(1, ge=1, description="Página"),
    limit: int = Query(20, ge=1, le=50, description="Resultados por página"),
    db: AsyncSession = Depends(get_db_async),
):
    """Búsqueda de proveedores por texto libre.

    Busca en: nombre del negocio, descripción del servicio, nombre del proveedor
    y nombre de categoría. Case-insensitive, match parcial (ILIKE).
    Soporta paginación con page/limit.
    """
    offset = (page - 1) * limit
    search_term = f"%{q}%"

    stmt = (
        select(ServiceProvider)
        .join(Provider, ServiceProvider.provider_id == Provider.id)
        .outerjoin(ServiceCategory, ServiceProvider.service_id == ServiceCategory.id)
        .where(
            and_(
                ServiceProvider.validation_status == "approved",
                ServiceProvider.is_available == True,
                or_(
                    ServiceProvider.business_name.ilike(search_term),
                    ServiceProvider.description.ilike(search_term),
                    Provider.full_name.ilike(search_term),
                    ServiceCategory.name.ilike(search_term),
                ),
            )
        )
        .options(
            selectinload(ServiceProvider.provider),
            selectinload(ServiceProvider.service_category),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(stmt)
    service_providers = result.scalars().all()

    from datetime import datetime as _dt
    response = []
    for sp in service_providers:
        provider = sp.provider
        sc = sp.service_category

        sc_resp = None
        if sc:
            from app.schemas.provider import ServiceCategoryResponse
            sc_resp = ServiceCategoryResponse(
                id=sc.id,
                name=sc.name,
                description=sc.description,
                icon=sc.icon,
                parent_category=getattr(sc, "parent_category", None),
                is_active=sc.is_active,
                main_category_id=sc.main_category_id,
                created_at=sc.created_at or _dt.utcnow(),
            )

        response.append(
            ServiceProviderResponse(
                id=sp.id,
                provider_id=sp.provider_id,
                service_id=sp.service_id,
                business_name=sp.business_name,
                description=sp.description or "",
                address=sp.address,
                latitude=sp.latitude or 0,
                longitude=sp.longitude or 0,
                phone=sp.phone,
                hourly_rate=sp.hourly_rate,
                is_available=sp.is_available,
                validation_status=str(sp.validation_status.value if hasattr(sp.validation_status, 'value') else sp.validation_status),
                rating_avg=sp.rating_avg or 0,
                total_reviews=sp.total_reviews or 0,
                created_at=sp.created_at or _dt.utcnow(),
                full_name=provider.full_name if provider else "",
                avatar=provider.avatar if provider else None,
                service_category=sc_resp,
                distance=None,  # text-search no filtra por ubicación
            )
        )

    return response


# ============================================================================
# DISPONIBILIDAD DE HORARIOS POR SERVICIO PUBLICADO (service_availability)
# ============================================================================

DAY_NAMES_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


@router.post("/{provider_id}/services/{service_id}/schedules", status_code=status.HTTP_201_CREATED)
async def upsert_service_schedule(
    provider_id: int,
    service_id: int,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async),
):
    """Crea o actualiza el horario de un día para un servicio publicado.

    Solo el proveedor dueño del servicio puede ejecutar esta acción.
    - provider_id: providers.id
    - service_id: service_providers.id
    - payload: { day_of_week, start_time (HH:MM), end_time (HH:MM), is_available }
    """
    from datetime import time as _time
    from app.models.booking import ServiceAvailability

    # Verificar que el proveedor autenticado es el dueño
    prov_result = await db.execute(select(Provider).where(Provider.user_id == current_user.id))
    provider = prov_result.scalar_one_or_none()
    if not provider or provider.id != provider_id:
        raise HTTPException(status_code=403, detail="No autorizado para gestionar este servicio")

    # Verificar que el service_provider pertenece al proveedor
    sp_result = await db.execute(
        select(ServiceProvider).where(
            ServiceProvider.id == service_id,
            ServiceProvider.provider_id == provider_id,
        )
    )
    sp = sp_result.scalar_one_or_none()
    if not sp:
        raise HTTPException(status_code=404, detail=SERVICE_NOT_FOUND)

    day_of_week = int(payload.get("day_of_week", -1))
    if not 0 <= day_of_week <= 6:
        raise HTTPException(status_code=422, detail="day_of_week debe estar entre 0 y 6")

    start_str = payload.get("start_time", "")
    end_str = payload.get("end_time", "")
    try:
        start_t = _time.fromisoformat(start_str)
        end_t = _time.fromisoformat(end_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="Formato de hora inválido. Use HH:MM")
    if end_t <= start_t:
        raise HTTPException(status_code=422, detail="end_time debe ser posterior a start_time")

    is_available = bool(payload.get("is_available", True))
    timezone = payload.get("timezone", "America/Santiago")

    # Upsert
    existing_result = await db.execute(
        select(ServiceAvailability).where(
            ServiceAvailability.provider_id == provider_id,
            ServiceAvailability.service_id == service_id,
            ServiceAvailability.day_of_week == day_of_week,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.start_time = start_t
        existing.end_time = end_t
        existing.is_available = is_available
        existing.timezone = timezone
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        record = existing
    else:
        record = ServiceAvailability(
            provider_id=provider_id,
            service_id=service_id,
            day_of_week=day_of_week,
            start_time=start_t,
            end_time=end_t,
            is_available=is_available,
            timezone=timezone,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

    return {
        "id": record.id,
        "provider_id": record.provider_id,
        "service_id": record.service_id,
        "day_of_week": record.day_of_week,
        "day_name": DAY_NAMES_ES[record.day_of_week],
        "start_time": record.start_time.strftime("%H:%M"),
        "end_time": record.end_time.strftime("%H:%M"),
        "is_available": record.is_available,
        "timezone": record.timezone,
    }


@router.get("/{provider_id}/services/{service_id}/schedules")
async def get_service_schedules(
    provider_id: int,
    service_id: int,
    db: AsyncSession = Depends(get_db_async),
):
    """Lista los horarios configurados para un servicio publicado (público).

    - provider_id: providers.id
    - service_id:  service_providers.id
    """
    from app.models.booking import ServiceAvailability

    result = await db.execute(
        select(ServiceAvailability).where(
            ServiceAvailability.provider_id == provider_id,
            ServiceAvailability.service_id == service_id,
        ).order_by(ServiceAvailability.day_of_week)
    )
    records = result.scalars().all()

    return [
        {
            "id": r.id,
            "provider_id": r.provider_id,
            "service_id": r.service_id,
            "day_of_week": r.day_of_week,
            "day_name": DAY_NAMES_ES[r.day_of_week],
            "start_time": r.start_time.strftime("%H:%M"),
            "end_time": r.end_time.strftime("%H:%M"),
            "is_available": r.is_available,
            "timezone": r.timezone,
        }
        for r in records
    ]


@router.get("/{provider_id}/services/{service_id}/available-slots")
async def get_available_slots(
    provider_id: int,
    service_id: int,
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Fecha YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db_async),
):
    """Devuelve los slots de 60 min disponibles para una fecha concreta.

    Un slot está bloqueado si existe un Booking (PENDING o CONFIRMED) del proveedor
    en esa misma fecha y hora.

    - provider_id: providers.id
    - service_id:  service_providers.id
    - date:        YYYY-MM-DD
    """
    from datetime import date as _date, time as _time, datetime as _dt, timedelta
    from app.models.booking import ServiceAvailability, Booking
    from app.infra.redis import get_slots_cache, set_slots_cache

    # Cache hit — TTL 60s
    cached_slots = get_slots_cache(provider_id, service_id, date)
    if cached_slots is not None:
        return cached_slots

    try:
        target_date = _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    # day_of_week: Python weekday() → 0=Lunes … 6=Domingo (igual que backend)
    dow = target_date.weekday()

    # Buscar horario del servicio para ese día
    sched_result = await db.execute(
        select(ServiceAvailability).where(
            ServiceAvailability.provider_id == provider_id,
            ServiceAvailability.service_id == service_id,
            ServiceAvailability.day_of_week == dow,
            ServiceAvailability.is_available == True,
        )
    )
    schedule = sched_result.scalar_one_or_none()

    if not schedule:
        return {"date": date, "service_provider_id": service_id, "slots": []}

    # Generar slots de 60 min entre start_time y end_time
    slots_times: list[str] = []
    cursor = _dt.combine(target_date, schedule.start_time)
    end_dt = _dt.combine(target_date, schedule.end_time)
    while cursor < end_dt:
        slots_times.append(cursor.strftime("%H:%M"))
        cursor += timedelta(hours=1)

    # Obtener bookings existentes (PENDING o CONFIRMED) del proveedor en esa fecha
    booked_result = await db.execute(
        select(Booking.scheduled_time).where(
            Booking.provider_id == provider_id,
            Booking.scheduled_date == target_date,
            Booking.status.in_(["PENDING", "CONFIRMED"]),
        )
    )
    booked_times = {
        t.strftime("%H:%M") for (t,) in booked_result.fetchall() if t is not None
    }

    slots = [
        {"time": t, "available": t not in booked_times}
        for t in slots_times
    ]

    response_payload = {"date": date, "service_provider_id": service_id, "slots": slots}
    set_slots_cache(provider_id, service_id, date, response_payload)
    return response_payload


# ============ FIN DEL ARCHIVO ======================
