"""
app/services/aws_rekognition_service.py

Reemplaza DeepFace/Celery con AWS Rekognition (Free Tier, síncrono, sin Celery).

- DetectFaces   → verifica si hay rostros en selfie e ID, devuelve bounding boxes
- CompareFaces  → mide similitud entre rostro de selfie y rostro de ID document

Autenticación: AWS Signature V4 implementada con stdlib (hmac + hashlib).
Sin boto3. Sin TensorFlow. Sin modelos locales pesados.

Variables de entorno requeridas:
  AWS_ACCESS_KEY_ID      — clave de acceso IAM
  AWS_SECRET_ACCESS_KEY  — clave secreta IAM
  AWS_REGION             — región (default: us-east-1)
"""

import base64
import datetime
import hashlib
import hmac
import io
import json
import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import aiohttp
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# Usar settings en lugar de os.getenv para asegurar que se lean del .env
_AWS_ACCESS_KEY = settings.AWS_ACCESS_KEY_ID or ""
_AWS_SECRET_KEY = settings.AWS_SECRET_ACCESS_KEY or ""
_AWS_REGION = settings.AWS_REGION or "us-east-1"
_SERVICE = "rekognition"
_HOST = f"rekognition.{_AWS_REGION}.amazonaws.com"
_ENDPOINT = f"https://{_HOST}/"

# Similitud mínima para considerar coincidencia (80 = Rekognition default razonable)
SIMILARITY_THRESHOLD = 80.0
# Tamaño máximo de imagen enviada a Rekognition (en bytes) — límite API: 5 MB
_MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 4 MB conservador


# ── AWS Signature V4 ─────────────────────────────────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signing_key(secret_key: str, date_stamp: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, _AWS_REGION)
    k_service = _sign(k_region, _SERVICE)
    return _sign(k_service, "aws4_request")


def _build_headers(target: str, payload_bytes: bytes) -> dict:
    """Construye headers con AWS Sig V4 para una request a Rekognition."""
    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(payload_bytes).hexdigest()

    canonical_headers = (
        f"content-type:application/x-amz-json-1.1\n"
        f"host:{_HOST}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{target}\n"
    )
    signed_headers = "content-type;host;x-amz-date;x-amz-target"

    canonical_request = "\n".join([
        "POST", "/", "",
        canonical_headers, signed_headers, payload_hash,
    ])

    credential_scope = f"{date_stamp}/{_AWS_REGION}/{_SERVICE}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _get_signing_key(_AWS_SECRET_KEY, date_stamp)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={_AWS_ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Date": amz_date,
        "X-Amz-Target": target,
        "Authorization": authorization,
    }


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def _download_image_bytes(url: str) -> bytes:
    """Descarga una imagen desde una URL y retorna sus bytes."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                raise ValueError(f"Error descargando imagen ({resp.status}): {url[:60]}")
            return await resp.read()


async def _call_rekognition(target: str, payload: dict) -> dict:
    """Llama a la API de Rekognition con Sig V4 y retorna el JSON de respuesta."""
    if not _AWS_ACCESS_KEY or not _AWS_SECRET_KEY:
        raise RuntimeError(
            "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY no configurados. "
            "Agregar variables de entorno para habilitar Rekognition."
        )

    body = json.dumps(payload).encode("utf-8")
    headers = _build_headers(target, body)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            _ENDPOINT,
            headers=headers,
            data=body,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            response_text = await resp.text()
            if resp.status != 200:
                raise ValueError(
                    f"Rekognition {target} error {resp.status}: {response_text[:200]}"
                )
            return json.loads(response_text)


def _prepare_image_bytes(raw: bytes) -> str:
    """
    Comprime/redimensiona si supera el límite, luego codifica a base64.
    Usa PIL si disponible; si no, usa los bytes raw.
    """
    if len(raw) <= _MAX_IMAGE_BYTES:
        return base64.b64encode(raw).decode("utf-8")

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        quality = 85
        while quality >= 50:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            compressed = buf.getvalue()
            if len(compressed) <= _MAX_IMAGE_BYTES:
                return base64.b64encode(compressed).decode("utf-8")
            quality -= 10
    except Exception:
        pass  # PIL no disponible o error — usar raw truncado (Rekognition rechazará si >5MB)

    return base64.b64encode(raw[:_MAX_IMAGE_BYTES]).decode("utf-8")


def _crop_face_to_base64(image_bytes: bytes, bounding_box: dict) -> Optional[str]:
    """
    Recorta el rostro desde la imagen usando el BoundingBox de Rekognition.
    Retorna base64 del recorte, o None si PIL no está disponible.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size

        left = int(bounding_box["Left"] * w)
        top = int(bounding_box["Top"] * h)
        right = int((bounding_box["Left"] + bounding_box["Width"]) * w)
        bottom = int((bounding_box["Top"] + bounding_box["Height"]) * h)

        # Añadir margen del 20%
        margin_x = int((right - left) * 0.2)
        margin_y = int((bottom - top) * 0.2)
        left = max(0, left - margin_x)
        top = max(0, top - margin_y)
        right = min(w, right + margin_x)
        bottom = min(h, bottom + margin_y)

        cropped = img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=90)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        logger.debug(f"[REKOGNITION] crop_face_to_base64 error: {exc}")
        return None


# ── API pública ───────────────────────────────────────────────────────────────

async def get_face_preview(selfie_url: str, id_document_url: str) -> dict:
    """
    Interfaz compatible con FaceMatchingService.get_face_preview().
    Detecta rostros en selfie e ID document, retorna previsualización recortada.

    Retorna dict:
      selfie          → base64 JPEG del rostro recortado (None si no hay)
      id_document     → base64 JPEG del rostro recortado (None si no hay)
      selfie_detected → bool
      id_detected     → bool
      selfie_count    → int
      id_count        → int
      error           → str | None
    """
    result: Dict[str, Any] = {
        "selfie": None,
        "id_document": None,
        "selfie_detected": False,
        "id_detected": False,
        "selfie_count": 0,
        "id_count": 0,
        "error": None,
    }

    try:
        logger.info("[REKOGNITION] Descargando imágenes...")
        selfie_bytes, id_bytes = await _download_image_bytes(selfie_url), None
        id_bytes = await _download_image_bytes(id_document_url)

        selfie_b64 = _prepare_image_bytes(selfie_bytes)
        id_b64 = _prepare_image_bytes(id_bytes)

        logger.info("[REKOGNITION] Detectando rostros en selfie...")
        selfie_resp = await _call_rekognition(
            "RekognitionService.DetectFaces",
            {"Image": {"Bytes": selfie_b64}, "Attributes": ["DEFAULT"]},
        )
        selfie_faces = selfie_resp.get("FaceDetails", [])

        logger.info("[REKOGNITION] Detectando rostros en documento ID...")
        id_resp = await _call_rekognition(
            "RekognitionService.DetectFaces",
            {"Image": {"Bytes": id_b64}, "Attributes": ["DEFAULT"]},
        )
        id_faces = id_resp.get("FaceDetails", [])

        result["selfie_count"] = len(selfie_faces)
        result["id_count"] = len(id_faces)
        result["selfie_detected"] = len(selfie_faces) > 0
        result["id_detected"] = len(id_faces) > 0

        if selfie_faces:
            bb = selfie_faces[0].get("BoundingBox", {})
            cropped = _crop_face_to_base64(selfie_bytes, bb)
            result["selfie"] = cropped or selfie_b64  # fallback: imagen completa

        if id_faces:
            bb = id_faces[0].get("BoundingBox", {})
            cropped = _crop_face_to_base64(id_bytes, bb)
            result["id_document"] = cropped or id_b64

        logger.info(
            f"[REKOGNITION] get_face_preview OK — selfie:{result['selfie_count']} faces, "
            f"id:{result['id_count']} faces"
        )

    except RuntimeError as exc:
        # Credenciales no configuradas
        logger.warning(f"[REKOGNITION] Credenciales no disponibles: {exc}")
        result["error"] = str(exc)
    except Exception as exc:
        logger.error(f"[REKOGNITION] get_face_preview error: {exc}", exc_info=True)
        result["error"] = str(exc)

    return result


async def compare_faces(
    selfie_url: str, id_document_url: str
) -> Tuple[bool, Decimal, Dict[str, Any]]:
    """
    Interfaz compatible con FaceMatchingService.compare_faces().
    Compara el rostro de la selfie con el del documento ID.

    Retorna: (is_match, confidence_score, metadata)
    """
    try:
        logger.info("[REKOGNITION] Descargando imágenes para comparación...")
        selfie_bytes = await _download_image_bytes(selfie_url)
        id_bytes = await _download_image_bytes(id_document_url)

        selfie_b64 = _prepare_image_bytes(selfie_bytes)
        id_b64 = _prepare_image_bytes(id_bytes)

        logger.info("[REKOGNITION] Llamando CompareFaces...")
        resp = await _call_rekognition(
            "RekognitionService.CompareFaces",
            {
                "SourceImage": {"Bytes": selfie_b64},
                "TargetImage": {"Bytes": id_b64},
                "SimilarityThreshold": SIMILARITY_THRESHOLD,
            },
        )

        face_matches = resp.get("FaceMatches", [])
        unmatched = resp.get("UnmatchedFaces", [])

        if face_matches:
            similarity = face_matches[0].get("Similarity", 0.0)
            is_match = similarity >= SIMILARITY_THRESHOLD
            confidence = round(similarity, 2)
        else:
            similarity = 0.0
            is_match = False
            confidence = 0.0

        logger.info(
            f"[REKOGNITION] CompareFaces — similarity={similarity:.1f}%, "
            f"match={is_match}, unmatched_faces={len(unmatched)}"
        )

        metadata = {
            "similarity": float(similarity),
            "confidence_score": confidence,
            "threshold": SIMILARITY_THRESHOLD,
            "is_match": is_match,
            "model_used": "AWS Rekognition",
            "face_matches": len(face_matches),
            "unmatched_faces": len(unmatched),
        }
        return is_match, Decimal(str(confidence)), metadata

    except Exception as exc:
        logger.error(f"[REKOGNITION] compare_faces error: {exc}", exc_info=True)
        return False, Decimal("0"), {"error": str(exc), "model_used": "AWS Rekognition"}


def is_configured() -> bool:
    """Retorna True si las credenciales AWS están configuradas."""
    return bool(_AWS_ACCESS_KEY and _AWS_SECRET_KEY)
