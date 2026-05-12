from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies import get_current_user
from app.core.cloudinary_client import upload_image
from app.models.user import User, UserProfile

router = APIRouter(prefix="/client/images", tags=["client-images"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE_MB = 5


@router.post("/avatar")
async def upload_client_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sube o reemplaza el avatar del perfil de cliente en Cloudinary."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Formato no permitido. Usa JPG, PNG o WEBP.")

    contents = await file.read()
    if len(contents) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera los {MAX_SIZE_MB} MB permitidos.")

    result = upload_image(
        file_bytes=contents,
        folder=f"bappsearch/clients/{current_user.id}/avatar",
        public_id=f"avatar_{current_user.id}",
        transformation=[{"width": 400, "height": 400, "crop": "fill", "gravity": "face"}],
    )

    profile: UserProfile | None = (
        db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    )
    if not profile:
        raise HTTPException(404, "Perfil de cliente no encontrado.")

    profile.avatar = result["secure_url"]
    db.commit()
    db.refresh(profile)

    return {"avatar_url": result["secure_url"], "public_id": result["public_id"]}
