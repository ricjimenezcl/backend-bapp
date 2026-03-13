from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.core.database import get_db_async, get_db
from app.core.config import settings
from app.models.user import User
from app.services.premium_service import PremiumService
from typing import Optional

security = HTTPBearer()



async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db_async)
) -> Optional[User]:
    """
    Devuelve el usuario si hay token válido.
    Si no hay token o es inválido, retorna None (NO lanza excepción).
    """
    if not credentials:
        return None

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        email: str = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None

    from sqlalchemy.future import select
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db_async)
) -> User:
    """Obtener usuario actual desde el token JWT"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception

        # JWT blacklist check — token invalidado en logout
        jti = payload.get("jti")
        if jti:
            try:
                from app.core.redis import cache_get
                if cache_get(f"blacklist:jwt:{jti}") is not None:
                    raise credentials_exception
            except HTTPException:
                raise
            except Exception:
                pass  # fail-open: si Redis falla no bloqueamos
    except JWTError:
        raise credentials_exception

    # Buscar usuario en la base de datos
    from sqlalchemy.future import select
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Verificar que el usuario está activo"""
    if current_user.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_provider(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Verificar que el usuario es un proveedor"""
    if current_user.role != "PROVIDER":
        raise HTTPException(status_code=403, detail="Provider access required")
    return current_user

async def get_current_admin(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Verificar que el usuario es un administrador"""
    if current_user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# =====================================================================
# VERSIONES SÍNCRONAS para BookingService y otros servicios síncronos
# =====================================================================

def get_current_user_sync(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Obtener usuario actual desde el token JWT (versión síncrona para servicios sincronos)
    
    Esta versión SÍ accede a la BD para obtener el ID del usuario.
    Así el BookingService puede usar current_user.id correctamente.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not credentials:
        raise credentials_exception
    
    try:
        payload = jwt.decode(
            credentials.credentials, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Buscar usuario en la BD para obtener su ID y datos completos
    user = db.query(User).filter(User.email == email).first()
    
    if user is None:
        raise credentials_exception
    
    return user

# Aliases para compatibilidad con endpoints
get_current_provider_user = get_current_provider


def validate_premium_access(provider_id: int, user_lat: Optional[float] = None, user_lng: Optional[float] = None):
    """
    Factory function para crear dependency que valida acceso premium.
    
    Uso:
        @router.post("/conversations")
        async def create_conversation(
            provider_id: int,
            current_user: User = Depends(get_current_user),
            _: bool = Depends(validate_premium_access(provider_id)),  # Valida acceso
            db: AsyncSession = Depends(get_db_async)
        ):
            # Solo se ejecuta si tiene acceso
    
    Args:
        provider_id: ID del proveedor a validar
        user_lat: Latitud del usuario (opcional)
        user_lng: Longitud del usuario (opcional)
    """
    async def _validate(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db_async)
    ) -> bool:
        # Solo validar para clientes
        if current_user.role != "CLIENT":
            return True
        
        premium_service = PremiumService(db)
        return await premium_service.validate_provider_access(
            client_id=current_user.id,
            provider_id=provider_id,
            user_lat=user_lat,
            user_lng=user_lng
        )
    
    return _validate

get_current_admin_user = get_current_admin