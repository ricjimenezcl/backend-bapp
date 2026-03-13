"""
Premium Access Validation Service
Centralizes logic for validating client access to providers
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Optional, List, Tuple
from datetime import datetime, timedelta

from app.models.user import User
from app.models.provider import Provider
from app.core.redis import cache_get, cache_set


class PremiumService:
    """Service for handling premium access validation"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def validate_provider_access(
        self, 
        client_id: int, 
        provider_id: int,
        user_lat: Optional[float] = None,
        user_lng: Optional[float] = None
    ) -> bool:
        """
        Valida si el cliente tiene acceso al proveedor solicitado.
        
        Reglas:
        - Si tiene premium activo → acceso completo
        - Si NO tiene premium → validar si está en primeros 5 por distancia
        
        Args:
            client_id: ID del cliente
            provider_id: ID del proveedor a acceder
            user_lat: Latitud del usuario (opcional, se intenta obtener del cache)
            user_lng: Longitud del usuario (opcional, se intenta obtener del cache)
        
        Returns:
            bool: True si tiene acceso
        
        Raises:
            HTTPException: 403 si no tiene acceso (PREMIUM_REQUIRED)
        """
        # Obtener usuario
        result = await self.db.execute(
            select(User).where(User.id == client_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Admin siempre tiene acceso
        if user.role == "ADMIN":
            return True
        
        # Cliente con premium activo
        if user.is_premium_active:
            return True
        
        # Cliente sin premium → validar primeros 5
        # Intentar obtener ubicación del cache si no se proporcionó
        if user_lat is None or user_lng is None:
            location = await self._get_user_last_location(client_id)
            if not location:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User location required for free tier access"
                )
            user_lat, user_lng = location
        
        # Obtener IDs de proveedores permitidos (primeros 5)
        allowed_provider_ids = await self._get_top_provider_ids(
            lat=user_lat,
            lng=user_lng,
            limit=5
        )
        
        # Verificar si provider_id está en los permitidos
        if provider_id not in allowed_provider_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="PREMIUM_REQUIRED",
                headers={"X-Premium-Required": "true"}
            )
        
        return True
    
    async def _get_user_last_location(self, user_id: int) -> Optional[Tuple[float, float]]:
        """
        Obtiene la última ubicación conocida del usuario desde cache
        
        Returns:
            Tuple[lat, lng] o None si no existe
        """
        cache_key = f"user_location:{user_id}"
        cached = cache_get(cache_key)
        
        if cached and isinstance(cached, dict):
            return (cached.get('latitude'), cached.get('longitude'))
        
        return None
    
    async def _get_top_provider_ids(
        self, 
        lat: float, 
        lng: float, 
        limit: int = 5
    ) -> List[int]:
        """
        Obtiene los IDs de los proveedores más cercanos (con cache)
        
        Args:
            lat: Latitud
            lng: Longitud
            limit: Número de proveedores (default 5)
        
        Returns:
            List[int]: IDs de proveedores ordenados por distancia
        """
        # Redondear coordenadas para mejorar hit rate del cache
        lat_rounded = round(lat, 2)
        lng_rounded = round(lng, 2)
        
        cache_key = f"top_providers:{lat_rounded}:{lng_rounded}:{limit}"
        cached = cache_get(cache_key)
        
        if cached:
            return cached
        
        # Query geoespacial con PostGIS
        query = text("""
            SELECT 
                sp.id,
                ST_Distance(
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(sp.longitude, sp.latitude), 4326)::geography
                ) AS distance_meters
            FROM service_providers sp
            WHERE sp.is_available = TRUE
            AND sp.validation_status = 'approved'
            ORDER BY distance_meters ASC
            LIMIT :limit
        """)
        
        result = await self.db.execute(
            query,
            {"lat": lat, "lng": lng, "limit": limit}
        )
        
        provider_ids = [row[0] for row in result.fetchall()]
        
        # Cachear por 30 segundos
        cache_set(cache_key, provider_ids, ttl=30)
        
        return provider_ids
    
    async def activate_premium(self, user_id: int) -> dict:
        """
        Activa acceso premium por 7 días
        
        Args:
            user_id: ID del usuario
        
        Returns:
            dict: Información de la activación
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if user.role != "CLIENT":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only clients can activate premium"
            )
        
        now = datetime.utcnow()
        expires_at = now + timedelta(days=7)
        
        user.has_premium = True
        user.premium_activated_at = now
        user.premium_expires_at = expires_at
        
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        return {
            "message": "Premium activated successfully",
            "activated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "days_remaining": 7
        }
    
    async def get_premium_status(self, user_id: int) -> dict:
        """
        Obtiene el estado premium del usuario
        
        Returns:
            dict: Estado premium
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        is_active = user.is_premium_active
        days_remaining = 0
        
        if is_active and user.premium_expires_at:
            delta = user.premium_expires_at - datetime.utcnow()
            days_remaining = max(0, delta.days)
        
        return {
            "has_premium": user.has_premium,
            "is_active": is_active,
            "activated_at": user.premium_activated_at.isoformat() if user.premium_activated_at else None,
            "expires_at": user.premium_expires_at.isoformat() if user.premium_expires_at else None,
            "days_remaining": days_remaining
        }
