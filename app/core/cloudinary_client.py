import cloudinary
import cloudinary.uploader
from app.core.config import settings


def _init():
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


def upload_image(
    file_bytes: bytes,
    folder: str,
    public_id: str | None = None,
    transformation: list | None = None,
) -> dict:
    """Sube una imagen a Cloudinary y retorna la respuesta completa."""
    _init()
    options: dict = {
        "folder": folder,
        "resource_type": "image",
        "overwrite": True,
    }
    if public_id:
        options["public_id"] = public_id
    if transformation:
        options["transformation"] = transformation
    return cloudinary.uploader.upload(file_bytes, **options)


def delete_image(public_id: str) -> dict:
    """Elimina una imagen de Cloudinary por su public_id."""
    _init()
    return cloudinary.uploader.destroy(public_id)
