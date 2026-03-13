from sqlalchemy.ext.asyncio import AsyncSession
from app.services.geolocation_service import GeolocationService
from app.services.provider_cache_service import (
    get_cached_providers,
    set_cached_providers,
)

async def search_providers(category: str, lat: float, lng: float, db: AsyncSession):
    # 1. Try Cache (Sync)
    cached = get_cached_providers(category, lat, lng)
    if cached:
        return {
            "source": "cache",
            "providers": cached
        }

    # 2. DB Search (Async)
    geo_service = GeolocationService(db)
    # Default radius 50km
    providers = await geo_service.find_nearby_providers(
        user_lat=lat, 
        user_lng=lng, 
        radius_km=50.0, 
        service_name=category
    )

    # 3. Cache Result (Sync)
    if providers:
        set_cached_providers(category, lat, lng, providers)

    return {
        "source": "db",
        "providers": providers
    }
