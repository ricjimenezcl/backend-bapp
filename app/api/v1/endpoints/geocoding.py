"""
Geocoding API Proxy Endpoints
Proxies requests to external geocoding services (Geoapify) 
to keep API keys secure on the backend.
"""

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
import aiohttp
import logging
from typing import Optional

from app.core.config import settings

router = APIRouter(prefix="/geocoding", tags=["geocoding"])
logger = logging.getLogger(__name__)


@router.get("/static-map")
async def get_static_map(
    lat: float = Query(..., description="Latitude of map center"),
    lng: float = Query(..., description="Longitude of map center"),
    zoom: int = Query(14, ge=1, le=20, description="Zoom level (1-20)"),
    width: int = Query(400, ge=100, le=1280, description="Map width in pixels"),
    height: int = Query(200, ge=100, le=1280, description="Map height in pixels"),
    style: str = Query("osm-bright", description="Map style (osm-bright, osm-carto, etc.)"),
    marker: bool = Query(True, description="Show marker at center")
):
    """
    Proxy endpoint for Geoapify Static Maps API.
    Returns a static map image as PNG.
    
    Free tier: 3,000 requests/day
    Keeps API key secure on the backend.
    
    Example: GET /api/v1/geocoding/static-map?lat=-33.4489&lng=-70.6693&zoom=14&width=400&height=200
    """
    
    if not settings.GEOAPIFY_API_KEY:
        logger.error("GEOAPIFY_API_KEY not configured in environment")
        raise HTTPException(
            status_code=500,
            detail="Geoapify API key not configured on server"
        )
    
    # Build Geoapify Static Maps URL
    base_url = "https://maps.geoapify.com/v1/staticmap"
    
    # Build marker parameter
    marker_param = ""
    if marker:
        marker_param = f"&marker=lonlat:{lng},{lat};type:material;color:%23ff4444;icontype:awesome;icon:map-marker"
    
    geoapify_url = (
        f"{base_url}"
        f"?center=lonlat:{lng},{lat}"
        f"&zoom={zoom}"
        f"&width={width}&height={height}"
        f"&style={style}"
        f"{marker_param}"
        f"&apiKey={settings.GEOAPIFY_API_KEY}"
    )
    
    try:
        # Make async HTTP request to Geoapify
        async with aiohttp.ClientSession() as session:
            async with session.get(geoapify_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Geoapify API error {response.status}: {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Geoapify API error: {error_text}"
                    )
                
                # Get image content
                image_data = await response.read()
                content_type = response.headers.get('Content-Type', 'image/png')
                
                # Return image as streaming response
                return Response(
                    content=image_data,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                        "X-Geoapify-Credits": "Map data © OpenStreetMap contributors"
                    }
                )
    
    except aiohttp.ClientError as e:
        logger.error(f"Network error calling Geoapify: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="Error connecting to map service"
        )
    except Exception as e:
        logger.exception("Unexpected error in static map proxy")
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )


@router.get("/reverse")
async def reverse_geocode(
    lat: float = Query(..., description="Latitud"),
    lon: float = Query(..., description="Longitud"),
    format: Optional[str] = Query("json"),
):
    """
    Proxy endpoint para geocodificación inversa de Geoapify.
    Convierte coordenadas a dirección formateada.
    """
    if not settings.GEOAPIFY_API_KEY:
        logger.error("GEOAPIFY_API_KEY not configured")
        raise HTTPException(status_code=500, detail="Geoapify API key not configured on server")

    geoapify_url = "https://api.geoapify.com/v1/geocode/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "lang": "es",
        "apiKey": settings.GEOAPIFY_API_KEY,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                geoapify_url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Geoapify reverse error {response.status}: {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Geoapify API error: {error_text}",
                    )
                data = await response.json()
                return data
    except aiohttp.ClientError as e:
        logger.error(f"Network error calling Geoapify reverse: {str(e)}")
        raise HTTPException(status_code=503, detail="Error connecting to geocoding service")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in reverse geocoding proxy")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/health")
async def geocoding_health():
    """
    Health check endpoint for geocoding service.
    Verifies that Geoapify API key is configured.
    """
    return {
        "status": "ok",
        "service": "geocoding-proxy",
        "geoapify_configured": bool(settings.GEOAPIFY_API_KEY)
    }
