from typing import List
from app.core.redis import cache_get, cache_set
from app.utils.geo import geo_grid

CACHE_TTL = 45  # segundos

def build_cache_key(category: str, lat: float, lng: float) -> str:
    lat_g = geo_grid(lat)
    lng_g = geo_grid(lng)
    return f"cache:providers:{category}:{lat_g}:{lng_g}"


def get_cached_providers(category: str, lat: float, lng: float):
    key = build_cache_key(category, lat, lng)
    return cache_get(key)


def set_cached_providers(category: str, lat: float, lng: float, providers: List[dict]):
    key = build_cache_key(category, lat, lng)
    cache_set(key, providers, ttl=CACHE_TTL)
