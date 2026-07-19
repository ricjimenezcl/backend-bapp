from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_async
from app.core.redis import rate_limit
from app.schemas.content_filter import ContentFilterPublicRequest, ContentFilterPublicResponse
from app.services.content_filter import ContentFilterService, normalize_text

router = APIRouter()


@router.post("/validate", response_model=ContentFilterPublicResponse)
async def validate_content_public(
    payload: ContentFilterPublicRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_async),
):
    """
    Endpoint publico para pre-validacion UX.

    Seguridad real sigue en los endpoints protegidos de escritura:
    este endpoint no expone la lista de palabras bloqueadas.
    """
    client_ip = request.client.host if request.client else "unknown"
    allowed = rate_limit(f"rate:content-filter:public:{client_ip}", 120, 60)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

    service = ContentFilterService(db=db)
    moderation = await service.validate_text(payload.text)

    severities = sorted({m.severity for m in moderation.matches})
    message = "Contenido no permitido" if moderation.blocked else None
    if moderation.flagged and not moderation.blocked:
        message = "Contenido potencialmente sensible"

    return ContentFilterPublicResponse(
        blocked=moderation.blocked,
        flagged=moderation.flagged,
        match_count=len(moderation.matches),
        severity_detected=severities,
        message=message,
        normalized_text=normalize_text(payload.text),
    )
