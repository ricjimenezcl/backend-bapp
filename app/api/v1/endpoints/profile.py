from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db_async
from app.dependencies import get_current_active_user
from app.models.user import User, UserProfile
import cloudinary.uploader
from sqlalchemy.future import select

router = APIRouter()

@router.post("/upload-avatar")
async def upload_avatar(
    avatar: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_active_user)
):
    """
    Sube la foto de perfil a Cloudinary y actualiza el usuario y perfil.
    """
    try:
        upload_result = cloudinary.uploader.upload(avatar.file, folder="users/avatars", public_id=f"user_{current_user.id}_avatar")
        avatar_url = upload_result.get("secure_url")
        if not avatar_url:
            raise HTTPException(status_code=500, detail="Error al subir imagen a Cloudinary")
        # Actualizar User y UserProfile
        current_user.avatar = avatar_url
        await db.commit()
        await db.refresh(current_user)
        # UserProfile
        result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
        profile = result.scalar_one_or_none()
        if profile:
            profile.avatar = avatar_url
            await db.commit()
        return {"avatar_url": avatar_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir avatar: {str(e)}")

@router.post("/change-password")
async def change_password(
    old_password: str = Body(...),
    new_password: str = Body(...),
    db: AsyncSession = Depends(get_db_async),
    current_user: User = Depends(get_current_active_user)
):
    """
    Cambia la contraseña del usuario autenticado.
    """
    from app.services.auth_service import AuthService
    auth_service = AuthService(db)
    if not auth_service.verify_password(old_password, current_user.password):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")
    current_user.password = auth_service.get_password_hash(new_password)
    await db.commit()
    return {"message": "Contraseña actualizada correctamente"}
