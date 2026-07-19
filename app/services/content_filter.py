import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banned_word import BannedWord, BannedWordSeverity
from app.schemas.content_filter import ContentFilterMatch


LEETSPEAK_TRANSLATION = str.maketrans({
    "1": "i",
    "3": "e",
    "0": "o",
    "5": "s",
    "@": "a",
})


def normalize_text(raw_text: str) -> str:
    text = (raw_text or "").lower().translate(LEETSPEAK_TRANSLATION)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # Mantener solo caracteres de palabra para que \b sea consistente.
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class ContentFilterResult:
    blocked: bool
    flagged: bool
    matches: list[ContentFilterMatch]


class _BannedWordsCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._expires_at = 0.0
        self._rows: list[BannedWord] = []

    @property
    def is_valid(self) -> bool:
        return self._expires_at > time.monotonic()

    @property
    def rows(self) -> list[BannedWord]:
        return self._rows

    def set_rows(self, rows: list[BannedWord]) -> None:
        self._rows = rows
        self._expires_at = time.monotonic() + self.ttl_seconds

    def invalidate(self) -> None:
        self._rows = []
        self._expires_at = 0.0


_GLOBAL_BANNED_WORDS_CACHE = _BannedWordsCache(ttl_seconds=300)


class ContentFilterService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_banned_words(self) -> list[BannedWord]:
        result = await self.db.execute(select(BannedWord).order_by(BannedWord.word.asc()))
        return list(result.scalars().all())

    async def add_banned_word(self, word: str, severity: BannedWordSeverity) -> BannedWord:
        normalized_word = normalize_text(word)
        if not normalized_word:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Word cannot be empty")

        existing = await self.db.execute(select(BannedWord).where(BannedWord.word == normalized_word))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Word already exists")

        row = BannedWord(word=normalized_word, severity=severity)
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        self.invalidate_cache()
        return row

    async def remove_banned_word(self, word_id: int) -> None:
        existing = await self.db.execute(select(BannedWord).where(BannedWord.id == word_id))
        row = existing.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")

        await self.db.execute(delete(BannedWord).where(BannedWord.id == word_id))
        await self.db.commit()
        self.invalidate_cache()

    async def validate_text(self, text: str) -> ContentFilterResult:
        normalized = normalize_text(text)
        if not normalized:
            return ContentFilterResult(blocked=False, flagged=False, matches=[])

        rows = await self._get_cached_words()
        matches: list[ContentFilterMatch] = []

        for row in rows:
            normalized_word = normalize_text(row.word)
            if not normalized_word:
                continue

            pattern = rf"\b{re.escape(normalized_word)}\b"
            if re.search(pattern, normalized):
                matches.append(ContentFilterMatch(word=row.word, severity=row.severity.value))

        blocked = any(m.severity == "block" for m in matches)
        flagged = any(m.severity == "flag" for m in matches)

        return ContentFilterResult(blocked=blocked, flagged=flagged, matches=matches)

    async def validate_or_raise(self, field_name: str, text: Optional[str]) -> None:
        if text is None:
            return

        result = await self.validate_text(text)
        if not result.blocked:
            return

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "OFFENSIVE_CONTENT_BLOCKED",
                "field": field_name,
                "message": f"El campo '{field_name}' contiene terminos no permitidos.",
                "matches": [m.model_dump() for m in result.matches],
            },
        )

    async def _get_cached_words(self) -> list[BannedWord]:
        if _GLOBAL_BANNED_WORDS_CACHE.is_valid:
            return _GLOBAL_BANNED_WORDS_CACHE.rows

        rows = await self.list_banned_words()
        _GLOBAL_BANNED_WORDS_CACHE.set_rows(rows)
        return rows

    @staticmethod
    def invalidate_cache() -> None:
        _GLOBAL_BANNED_WORDS_CACHE.invalidate()
