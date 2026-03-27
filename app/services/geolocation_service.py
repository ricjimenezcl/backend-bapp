import aiohttp
import math
import base64
import logging
import re
import unicodedata
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import HTTPException
from app.core.config import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Queries SQL
# ──────────────────────────────────────────────────────────────────────────────

# Columnas SELECT compartidas por ambas implementaciones
_SELECT_COLS = """
    sp.id,
    sp.provider_id,
    sp.service_id,
    sp.business_name,
    sp.description,
    sp.address,
    sp.latitude,
    sp.longitude,
    sp.phone,
    sp.hourly_rate,
    sp.is_available,
    sp.validation_status,
    sp.rating_avg,
    sp.total_reviews,
    sp.created_at,
    sp.updated_at,
    p.full_name,
    p.avatar,
    p.rating_avg   AS provider_rating,
    p.bio,
    p.user_id      AS provider_user_id,
    sc.name        AS service_category_name,
    sc.icon        AS service_icon
"""

_JOIN_CLAUSE = """
    FROM service_providers sp
    JOIN providers p ON sp.provider_id = p.id
    LEFT JOIN service_categories sc ON sp.service_id = sc.id
"""

_BASE_WHERE = """
    WHERE sp.validation_status = 'approved'
      AND sp.is_available = true
"""

# ── Haversine (sin PostGIS) ───────────────────────────────────────────────────

_HAVERSINE_DISTANCE = """
    (:earth_radius *
        acos(GREATEST(-1.0, LEAST(1.0,
            cos(radians(:user_lat)) *
            cos(radians(sp.latitude)) *
            cos(radians(sp.longitude) - radians(:user_lng)) +
            sin(radians(:user_lat)) *
            sin(radians(sp.latitude))
        )))
    ) AS distance
"""

# ── PostGIS (ST_DWithin + ST_Distance) ───────────────────────────────────────

_POSTGIS_DISTANCE = """
    ROUND(
        (ST_Distance(
            sp.location::geography,
            ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography
        ) / 1000.0)::numeric, 2
    ) AS distance
"""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_address(address: str) -> str:
    """Normalize address for cache key deduplication.

    Lowercases, removes accents, strips punctuation and extra whitespace.
    'Av. Providencia 1234, Santiago' == 'av providencia 1234 santiago'
    """
    # Remove accents
    nfkd = unicodedata.normalize("NFKD", address)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    # Lowercase, remove punctuation, collapse spaces
    cleaned = re.sub(r"[^\w\s]", " ", ascii_str.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


# ──────────────────────────────────────────────────────────────────────────────
# Servicio principal
# ──────────────────────────────────────────────────────────────────────────────

class GeolocationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.geoapify_key = settings.GEOAPIFY_API_KEY

    # ── find_nearby_providers ─────────────────────────────────────────────────

    async def find_nearby_providers(
        self,
        user_lat: float,
        user_lng: float,
        radius_km: float,
        service_name: str = None
    ):
        """Proveedores cercanos filtrados por nombre de categoría."""
        if settings.USE_POSTGIS:
            return await self._find_nearby_postgis(
                user_lat, user_lng, radius_km,
                service_name=service_name
            )
        return await self._find_nearby_haversine(
            user_lat, user_lng, radius_km,
            service_name=service_name
        )

    # ── find_nearby_providers_by_service_id ───────────────────────────────────

    async def find_nearby_providers_by_service_id(
        self,
        user_lat: float,
        user_lng: float,
        radius_km: float,
        service_id: int,
        skip: int = 0,
        limit: int = 10,
    ):
        """Proveedores cercanos filtrados por service_id."""
        if settings.USE_POSTGIS:
            return await self._find_nearby_postgis(
                user_lat, user_lng, radius_km,
                service_id=service_id,
                skip=skip, limit=limit
            )
        return await self._find_nearby_haversine(
            user_lat, user_lng, radius_km,
            service_id=service_id,
            skip=skip, limit=limit
        )

    # ── Implementación Haversine (fallback sin PostGIS) ───────────────────────

    async def _find_nearby_haversine(
        self,
        user_lat: float,
        user_lng: float,
        radius_km: float,
        service_name: str = None,
        service_id: int = None,
        skip: int = 0,
        limit: int = 50,
    ):
        """Búsqueda radial con fórmula Haversine en SQL puro.
        Funciona en cualquier PostgreSQL sin extensiones extra.
        Complejidad O(n) — full scan. Adecuado hasta ~5k proveedores.
        """
        inner = f"SELECT {_SELECT_COLS}, {_HAVERSINE_DISTANCE} {_JOIN_CLAUSE} {_BASE_WHERE}"

        params = {
            "earth_radius": 6371,
            "user_lat": user_lat,
            "user_lng": user_lng,
            "radius_km": radius_km,
            "limit": limit,
            "skip": skip,
        }

        if service_name:
            inner += " AND sc.name = :service_name"
            params["service_name"] = service_name
        elif service_id is not None:
            inner += " AND sp.service_id = :service_id"
            params["service_id"] = service_id

        query = (
            f"SELECT * FROM ({inner}) AS sub"
            f" WHERE sub.distance < :radius_km"
            f" ORDER BY sub.distance ASC LIMIT :limit OFFSET :skip"
        )

        return await self._execute_and_map(query, params)

    # ── Implementación PostGIS (ST_DWithin + GiST) ───────────────────────────

    async def _find_nearby_postgis(
        self,
        user_lat: float,
        user_lng: float,
        radius_km: float,
        service_name: str = None,
        service_id: int = None,
        skip: int = 0,
        limit: int = 50,
    ):
        """Búsqueda radial con PostGIS ST_DWithin.
        Usa índice GiST — complejidad O(log n). ~10-50x más rápido que Haversine.
        Requiere: migración 003_postgis_geolocation.sql + USE_POSTGIS=True.
        """
        radius_meters = radius_km * 1000.0

        query = f"""
        SELECT {_SELECT_COLS}, {_POSTGIS_DISTANCE}
        {_JOIN_CLAUSE}
        {_BASE_WHERE}
          AND sp.location IS NOT NULL
          AND ST_DWithin(
              sp.location::geography,
              ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
              :radius_meters
          )
        """

        params = {
            "user_lat": user_lat,
            "user_lng": user_lng,
            "radius_meters": radius_meters,
            "limit": limit,
            "skip": skip,
        }

        if service_name:
            query += " AND sc.name = :service_name"
            params["service_name"] = service_name
        elif service_id is not None:
            query += " AND sp.service_id = :service_id"
            params["service_id"] = service_id

        query += " ORDER BY distance ASC LIMIT :limit OFFSET :skip"

        return await self._execute_and_map(query, params)

    # ── Helpers comunes ───────────────────────────────────────────────────────

    async def _execute_and_map(self, query: str, params: dict) -> list:
        """Ejecuta una query geo y convierte rows → lista de dicts."""
        try:
            result = await self.db.execute(text(query), params)
            rows = result.fetchall()

            providers_list = []
            for row in rows:
                provider_dict = dict(row._mapping)
                provider_dict['service_provider_id'] = provider_dict.get('id')

                # Convertir avatar binario a base64 si llega como bytes
                if provider_dict.get('avatar') and isinstance(provider_dict['avatar'], bytes):
                    try:
                        provider_dict['avatar'] = base64.b64encode(
                            provider_dict['avatar']
                        ).decode('utf-8')
                    except Exception:
                        provider_dict['avatar'] = None

                if provider_dict.get('distance') is not None:
                    provider_dict['distance'] = round(float(provider_dict['distance']), 2)

                providers_list.append(provider_dict)

            return providers_list

        except Exception as e:
            engine = "PostGIS" if settings.USE_POSTGIS else "Haversine"
            logger.error(f"Error en búsqueda geoespacial ({engine}): {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Error al buscar proveedores: {str(e)}"
            )

    # ── Geocoding con cache (Geoapify) ────────────────────────────────────────

    async def geocode_address(
        self,
        address: str,
        country_code: str = "CL",
    ) -> dict:
        """Convierte dirección a coordenadas.

        Strategy:
        1. Normalize address → check geocode_cache table.
        2. Cache hit  → return immediately, update hit_count.
        3. Cache miss → call Geoapify → store in cache + address_index.

        This ensures each unique address is only geocoded once (ever).
        """
        normalized = _normalize_address(address)

        # 1. Cache lookup
        cached = await self._get_geocode_cache(country_code, normalized)
        if cached:
            logger.debug(f"Geocode cache HIT: {normalized[:60]}")
            await self._update_cache_hit(country_code, normalized)
            return cached

        # 2. External call
        logger.debug(f"Geocode cache MISS — calling Geoapify: {normalized[:60]}")
        result = await self._call_geoapify(address)

        # 3. Store in cache (best-effort — don't fail the request if this errors)
        try:
            await self._store_geocode_cache(country_code, normalized, result)
            await self._upsert_address_index(country_code, address, result)
        except Exception as e:
            logger.warning(f"Error storing geocode cache: {e}")

        return result

    async def _get_geocode_cache(
        self, country_code: str, address_normalized: str
    ) -> dict | None:
        """Return cached geocode result or None."""
        row = await self.db.execute(
            text("""
                SELECT lat, lng
                FROM geocode_cache
                WHERE country_code = :cc AND address_normalized = :addr
            """),
            {"cc": country_code, "addr": address_normalized},
        )
        r = row.fetchone()
        if r:
            return {"latitude": r.lat, "longitude": r.lng, "formatted_address": address_normalized}
        return None

    async def _update_cache_hit(self, country_code: str, address_normalized: str) -> None:
        """Increment hit_count and update last_used_at (fire-and-forget)."""
        try:
            await self.db.execute(
                text("""
                    UPDATE geocode_cache
                    SET hit_count = hit_count + 1, last_used_at = NOW()
                    WHERE country_code = :cc AND address_normalized = :addr
                """),
                {"cc": country_code, "addr": address_normalized},
            )
        except Exception as e:
            logger.warning(f"Error updating geocode cache hit count: {e}")

    async def _store_geocode_cache(
        self, country_code: str, address_normalized: str, result: dict
    ) -> None:
        """Persist a new geocode result to the cache table."""
        await self.db.execute(
            text("""
                INSERT INTO geocode_cache
                    (country_code, address_normalized, lat, lng)
                VALUES (:cc, :addr, :lat, :lng)
                ON CONFLICT (country_code, address_normalized) DO NOTHING
            """),
            {
                "cc": country_code,
                "addr": address_normalized,
                "lat": result["latitude"],
                "lng": result["longitude"],
            },
        )

    async def _upsert_address_index(
        self, country_code: str, display_text: str, result: dict
    ) -> None:
        """Add address to the autocomplete index, incrementing popularity."""
        await self.db.execute(
            text("""
                INSERT INTO address_index
                    (country_code, display_text, lat, lng, popularity, search_vector)
                VALUES (
                    :cc, :display, :lat, :lng, 1,
                    to_tsvector('simple', :display)
                )
                ON CONFLICT DO NOTHING
            """),
            {
                "cc": country_code,
                "display": display_text,
                "lat": result["latitude"],
                "lng": result["longitude"],
            },
        )

    async def _call_geoapify(self, address: str) -> dict:
        """Call Geoapify geocoding API. Raises HTTPException on failure."""
        if not self.geoapify_key:
            raise HTTPException(
                status_code=503,
                detail="Geocoding service not configured"
            )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.geoapify.com/v1/geocode/search",
                params={
                    "text": address,
                    "apiKey": self.geoapify_key,
                    "format": "json"
                }
            ) as response:
                data = await response.json()

        if data.get("results"):
            r = data["results"][0]
            return {
                "latitude": r["lat"],
                "longitude": r["lon"],
                "formatted_address": r.get("formatted", address),
            }

        raise HTTPException(status_code=400, detail="Address not found")

    # ── Autocomplete desde índice propio ──────────────────────────────────────

    async def autocomplete_address(
        self,
        query: str,
        country_code: str = "CL",
        limit: int = 5,
    ) -> list[dict]:
        """Full-text autocomplete from the local address_index table.

        Falls back to an empty list if the table is empty or the query
        returns no results (caller can then hit external API if desired).
        """
        if len(query.strip()) < 3:
            return []

        try:
            result = await self.db.execute(
                text("""
                    SELECT display_text, lat, lng, popularity
                    FROM address_index
                    WHERE country_code = :cc
                      AND search_vector @@ plainto_tsquery('simple', :q)
                    ORDER BY popularity DESC
                    LIMIT :limit
                """),
                {"cc": country_code, "q": query, "limit": limit},
            )
            rows = result.fetchall()
            return [
                {"display_text": r.display_text, "lat": r.lat, "lng": r.lng}
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"Autocomplete query error: {e}")
            return []

    # ── Distancia Haversine Python (utilidad) ─────────────────────────────────

    async def calculate_distance(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Distancia entre dos puntos en kilómetros (Haversine)."""
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2 +
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
            math.sin(dlon / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
