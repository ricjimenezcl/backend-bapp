from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db_async
from app.models.user import User, UserProfile
from app.dependencies import get_current_active_user

router = APIRouter()


class ClientUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    avatar: Optional[str] = None


class ClientPublicResponse(BaseModel):
    id: int
    user_id: int
    run: Optional[str] = None
    full_name: str
    phone: Optional[str] = None
    avatar: Optional[str] = None
    bio: Optional[str] = None
    rating_avg: Optional[float] = None
    email: str

    class Config:
        from_attributes = True


@router.get("/me", response_model=ClientPublicResponse)
async def get_client_me(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """Obtener perfil del cliente autenticado."""
    query = (
        select(User)
        .options(selectinload(User.client_profile))
        .where(User.id == current_user.id)
        .where(User.role == "CLIENT")
    )
    result = await db.execute(query)
    user = result.unique().scalar_one_or_none()

    if not user or not user.client_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client profile not found"
        )

    profile = user.client_profile
    return ClientPublicResponse(
        id=profile.id,
        user_id=user.id,
        run=None,
        full_name=profile.full_name,
        phone=profile.phone,
        avatar=profile.avatar,
        bio=profile.bio,
        rating_avg=float(profile.rating_avg) if profile.rating_avg else None,
        email=user.email
    )


@router.patch("/me", response_model=ClientPublicResponse)
async def update_client_me(
    update_data: ClientUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Actualizar perfil del cliente autenticado.
    Acepta: full_name, phone, bio, avatar.
    """
    query = (
        select(User)
        .options(selectinload(User.client_profile))
        .where(User.id == current_user.id)
        .where(User.role == "CLIENT")
    )
    result = await db.execute(query)
    user = result.unique().scalar_one_or_none()

    if not user or not user.client_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client profile not found"
        )

    profile = user.client_profile

    if update_data.full_name is not None:
        profile.full_name = update_data.full_name
    if update_data.phone is not None:
        profile.phone = update_data.phone
    if update_data.bio is not None:
        profile.bio = update_data.bio
    if update_data.avatar is not None:
        if update_data.avatar.startswith('data:image') or (
            not update_data.avatar.startswith('http') and len(update_data.avatar) > 100
        ):
            # Es base64 → subir a Cloudinary y guardar URL en user_profiles.avatar
            try:
                import base64 as b64
                import traceback
                from app.infra.storage.cloudinary_storage import CloudinaryStorage
                storage = CloudinaryStorage()

                if update_data.avatar.startswith('data:image'):
                    base64_data = update_data.avatar.split(',', 1)[1]
                else:
                    base64_data = update_data.avatar

                # Corregir padding base64
                padding = 4 - (len(base64_data) % 4)
                if padding != 4:
                    base64_data += '=' * padding

                file_bytes = b64.b64decode(base64_data)

                upload_result = await storage.upload_file(
                    file_bytes=file_bytes,
                    filename=f"avatar_{user.id}.jpg",
                    folder=f"clients/{user.id}/avatar",
                    resource_type="image",
                    public_id=f"client_{user.id}_avatar"
                )

                profile.avatar = upload_result.secure_url
                print(f"✅ Avatar de cliente subido a Cloudinary: {profile.avatar}")

            except HTTPException:
                raise
            except Exception as e:
                import traceback
                print(f"❌ Error subiendo avatar de cliente a Cloudinary: {e}")
                print(f"❌ Traceback: {traceback.format_exc()}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Error uploading avatar"
                )
        else:
            # Es URL directa (Cloudinary u otro) → guardar tal cual
            profile.avatar = update_data.avatar

    await db.commit()
    await db.refresh(profile)

    return ClientPublicResponse(
        id=profile.id,
        user_id=user.id,
        run=None,
        full_name=profile.full_name,
        phone=profile.phone,
        avatar=profile.avatar,
        bio=profile.bio,
        rating_avg=float(profile.rating_avg) if profile.rating_avg else None,
        email=user.email
    )


@router.get("/{client_id}", response_model=ClientPublicResponse)
async def get_client_by_id(
    client_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Obtener perfil público de un cliente por su user_id.
    Devuelve: id (UserProfile.id), user_id, run, full_name, phone, avatar, bio, rating_avg, email.
    """
    query = (
        select(User)
        .options(selectinload(User.client_profile))
        .where(User.id == client_id)
        .where(User.role == "CLIENT")
    )
    result = await db.execute(query)
    user = result.unique().scalar_one_or_none()

    if not user or not user.client_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    profile = user.client_profile
    return ClientPublicResponse(
        id=profile.id,
        user_id=user.id,
        run=None,
        full_name=profile.full_name,
        phone=profile.phone,
        avatar=profile.avatar,
        bio=profile.bio,
        rating_avg=float(profile.rating_avg) if profile.rating_avg else None,
        email=user.email
    )
