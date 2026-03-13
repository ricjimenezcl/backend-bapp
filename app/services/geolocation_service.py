import aiohttp
import math
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from fastapi import HTTPException
from app.core.config import settings


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

        Fix: PostgreSQL no permite referenciar aliases de columna calculados
        en HAVING ni en WHERE. Se usa subquery para resolver el alias primero.
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
        Radio real sobre esfera WGS84 — sin error de bounding box.
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
                # Campos explícitos para claridad en el frontend
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
            print(f"Error en búsqueda geoespacial ({engine}): {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error al buscar proveedores: {str(e)}"
            )

    # ── Geocoding (Geoapify — mantenido por compatibilidad) ───────────────────

    async def geocode_address(self, address: str):
        """Convierte dirección a coordenadas usando GeoApify."""
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
                    result = data["results"][0]
                    return {
                        "latitude": result["lat"],
                        "longitude": result["lon"],
                        "formatted_address": result["formatted"]
                    }

                raise HTTPException(
                    status_code=400,
                    detail="Address not found"
                )

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
