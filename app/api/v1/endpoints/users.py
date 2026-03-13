from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User, UserProfile
from app.models.provider import Provider
from app.schemas.user import UserDetailResponse, UserProfileUpdate
from app.services.client_service import ClientService
from pydantic import BaseModel

router = APIRouter()

# ====================== SCHEMAS ======================
class AvatarUpdateRequest(BaseModel):
    avatar_url: str

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

# ====================== ENDPOINTS ======================

@router.get("/me", response_model=UserDetailResponse)
async def read_user_me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener perfil completo del usuario actual (Cliente)
    """
    if current_user.role == "CLIENT":
        client_service = ClientService(db)
        return await client_service.get_client_profile(current_user.id)
    
    return UserDetailResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        status=current_user.status,
        created_at=current_user.created_at,
        profile=None
    )

@router.patch("/me", response_model=UserDetailResponse)
async def update_user_me(
    profile_update: UserProfileUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Actualizar perfil del usuario actual (Solo Clientes por ahora)
    """
    if current_user.role != "CLIENT":
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only clients can update their profile via this endpoint"
        )
        
    client_service = ClientService(db)
    return await client_service.update_client_profile(current_user.id, profile_update)


# ====================== SETTINGS ENDPOINTS ======================

@router.put("/me/avatar")
async def update_avatar(
    request: AvatarUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Actualizar foto de perfil del usuario actual.
    Acepta URL de Cloudinary.
    """
    try:
        # Actualizar avatar en user_profiles
        if current_user.role == "CLIENT":
            stmt = update(UserProfile).where(
                UserProfile.user_id == current_user.id
            ).values(avatar=request.avatar_url)
        elif current_user.role == "PROVIDER":
            stmt = update(Provider).where(
                Provider.user_id == current_user.id
            ).values(avatar=request.avatar_url)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid user role"
            )
        
        await db.execute(stmt)
        await db.commit()
        
        return {
            "success": True,
            "message": "Avatar actualizado correctamente",
            "avatar_url": request.avatar_url
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al actualizar avatar: {str(e)}"
        )


@router.put("/me/password")
async def change_password(
    request: PasswordChangeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Cambiar contraseña del usuario actual.
    Requiere contraseña actual para validar.
    """
    from app.services.auth_service import AuthService
    
    if not request.current_password or not request.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requieren contraseña actual y nueva"
        )
    
    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña debe tener al menos 8 caracteres"
        )
    
    # Verificar contraseña actual
    auth_service = AuthService(db)
    if not auth_service.verify_password(request.current_password, current_user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta"
        )
    
    try:
        # Hash nueva contraseña
        new_hashed = auth_service.get_password_hash(request.new_password)
        
        # Actualizar en BD
        stmt = update(User).where(
            User.id == current_user.id
        ).values(password=new_hashed)
        
        await db.execute(stmt)
        await db.commit()
        
        return {
            "success": True,
            "message": "Contraseña actualizada correctamente. Por favor, inicia sesión nuevamente."
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al cambiar contraseña: {str(e)}"
        )
