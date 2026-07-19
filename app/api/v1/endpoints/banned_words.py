from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_async
from app.dependencies import get_current_admin
from app.models.user import User
from app.models.banned_word import BannedWordSeverity
from app.schemas.content_filter import BannedWordCreateRequest, BannedWordResponse
from app.services.content_filter import ContentFilterService

router = APIRouter()


@router.get("", response_model=list[BannedWordResponse])
async def list_banned_words(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_async),
):
    _ = current_user
    service = ContentFilterService(db)
    rows = await service.list_banned_words()
    return [BannedWordResponse.model_validate(row) for row in rows]


@router.post("", response_model=BannedWordResponse, status_code=status.HTTP_201_CREATED)
async def add_banned_word(
    payload: BannedWordCreateRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_async),
):
    _ = current_user
    service = ContentFilterService(db)
    row = await service.add_banned_word(payload.word, BannedWordSeverity(payload.severity))
    return BannedWordResponse.model_validate(row)


@router.delete("/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_banned_word(
    word_id: int,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db_async),
):
    _ = current_user
    service = ContentFilterService(db)
    await service.remove_banned_word(word_id)
    return None


@router.post("/invalidate-cache", status_code=status.HTTP_204_NO_CONTENT)
async def invalidate_banned_words_cache(
    current_user: User = Depends(get_current_admin),
):
    _ = current_user
    ContentFilterService.invalidate_cache()
    return None
