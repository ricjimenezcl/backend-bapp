from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
import uuid

from app.core.database import get_db
from app.dependencies import get_current_user
from app.core.cloudinary_client import upload_image, delete_image
from app.models.provider import Provider, ServiceProvider
from app.models.user import User

router = APIRouter(prefix="/provider/images", tags=["provider-images"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE_MB = 8
MAX_PORTFOLIO = 10
ERR_FORMAT = "Formato no permitido. Usa JPG, PNG o WEBP."

# Annotated aliases para DI (FastAPI moderno)
DbSession   = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_RESPONSES_UPLOAD = {
    400: {"description": "Formato inválido o archivo demasiado grande"},
    403: {"description": "No autorizado"},
    404: {"description": "Recurso no encontrado"},
}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_provider(user_id: int, db: Session) -> Provider:
    provider = db.query(Provider).filter(Provider.user_id == user_id).first()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de proveedor no encontrado.",
        )
    return provider


def _get_service_provider(sp_id: int, user_id: int, db: Session) -> ServiceProvider:
    sp = db.query(ServiceProvider).filter(ServiceProvider.id == sp_id).first()
    if not sp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servicio no encontrado.",
        )
    if sp.provider.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado.",
        )
    return sp


def _validate_file(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ERR_FORMAT)


async def _read_and_check_size(file: UploadFile) -> bytes:
    contents = await file.read()
    if len(contents) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo supera los {MAX_SIZE_MB} MB permitidos.",
        )
    return contents


# ─── Avatar del proveedor ─────────────────────────────────────────────────────

@router.post("/avatar", responses=_RESPONSES_UPLOAD)
async def upload_provider_avatar(
    file: UploadFile = File(...),
    db: DbSession = None,
    current_user: CurrentUser = None,
):
    """Sube o reemplaza el avatar del proveedor en Cloudinary."""
    provider = _get_provider(current_user.id, db)
    _validate_file(file)
    contents = await _read_and_check_size(file)

    result = upload_image(
        file_bytes=contents,
        folder=f"bappsearch/providers/{provider.id}/avatar",
        public_id=f"avatar_{provider.id}",
        transformation=[{"width": 500, "height": 500, "crop": "fill", "gravity": "face"}],
    )

    provider.avatar = result["secure_url"]
    db.commit()
    db.refresh(provider)

    return {"avatar_url": result["secure_url"], "public_id": result["public_id"]}


# ─── Portafolio por servicio (/portfolio/{service_provider_id}) ───────────────

@router.get(
    "/portfolio/{service_provider_id}",
    responses={403: {"description": "No autorizado"}, 404: {"description": "Servicio no encontrado"}},
)
async def list_portfolio_images(
    service_provider_id: int,
    db: DbSession = None,
    current_user: CurrentUser = None,
):
    """Retorna las imágenes del portafolio de un servicio específico."""
    sp = _get_service_provider(service_provider_id, current_user.id, db)
    images = sp.portfolio_images or []
    return {"images": images, "total": len(images)}


@router.post("/portfolio/{service_provider_id}", responses=_RESPONSES_UPLOAD)
async def upload_portfolio_image(
    service_provider_id: int,
    file: UploadFile = File(...),
    db: DbSession = None,
    current_user: CurrentUser = None,
):
    """Agrega una imagen al portafolio de un servicio (máximo MAX_PORTFOLIO)."""
    sp = _get_service_provider(service_provider_id, current_user.id, db)
    _validate_file(file)
    contents = await _read_and_check_size(file)

    current_portfolio: list = list(sp.portfolio_images or [])
    if len(current_portfolio) >= MAX_PORTFOLIO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Límite de {MAX_PORTFOLIO} imágenes alcanzado para este servicio.",
        )

    image_id = str(uuid.uuid4())[:8]
    result = upload_image(
        file_bytes=contents,
        folder=f"bappsearch/service_providers/{service_provider_id}/portfolio",
        public_id=f"portfolio_{service_provider_id}_{image_id}",
        transformation=[{"width": 1200, "height": 900, "crop": "fill"}],
    )

    current_portfolio.append({
        "id": image_id,
        "url": result["secure_url"],
        "public_id": result["public_id"],
    })
    sp.portfolio_images = current_portfolio
    db.commit()
    db.refresh(sp)

    return {
        "image": {"id": image_id, "url": result["secure_url"], "public_id": result["public_id"]},
        "total": len(current_portfolio),
    }


@router.delete(
    "/portfolio/{service_provider_id}/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "No autorizado"},
        404: {"description": "Servicio o imagen no encontrada"},
    },
)
async def delete_portfolio_image(
    service_provider_id: int,
    image_id: str,
    db: DbSession = None,
    current_user: CurrentUser = None,
):
    """Elimina una imagen del portafolio de un servicio y la borra de Cloudinary."""
    sp = _get_service_provider(service_provider_id, current_user.id, db)
    current_portfolio: list = list(sp.portfolio_images or [])

    image_data = next((img for img in current_portfolio if img["id"] == image_id), None)
    if not image_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Imagen no encontrada en el portafolio.",
        )

    delete_image(image_data["public_id"])
    sp.portfolio_images = [img for img in current_portfolio if img["id"] != image_id]
    db.commit()


@router.put("/portfolio/{service_provider_id}/{image_id}", responses=_RESPONSES_UPLOAD)
async def replace_portfolio_image(
    service_provider_id: int,
    image_id: str,
    file: UploadFile = File(...),
    db: DbSession = None,
    current_user: CurrentUser = None,
):
    """Reemplaza una imagen existente del portafolio de un servicio."""
    sp = _get_service_provider(service_provider_id, current_user.id, db)
    _validate_file(file)
    contents = await _read_and_check_size(file)

    current_portfolio: list = list(sp.portfolio_images or [])
    image_data = next((img for img in current_portfolio if img["id"] == image_id), None)
    if not image_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Imagen no encontrada en el portafolio.",
        )

    delete_image(image_data["public_id"])

    result = upload_image(
        file_bytes=contents,
        folder=f"bappsearch/service_providers/{service_provider_id}/portfolio",
        public_id=f"portfolio_{service_provider_id}_{image_id}",
        transformation=[{"width": 1200, "height": 900, "crop": "fill"}],
    )

    for img in current_portfolio:
        if img["id"] == image_id:
            img["url"] = result["secure_url"]
            img["public_id"] = result["public_id"]
            break

    sp.portfolio_images = current_portfolio
    db.commit()

    return {
        "image": {"id": image_id, "url": result["secure_url"], "public_id": result["public_id"]}
    }
