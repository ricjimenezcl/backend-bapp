from enum import Enum

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class BannedWordSeverity(str, Enum):
    BLOCK = "block"
    FLAG = "flag"


class BannedWord(Base):
    __tablename__ = "banned_words"

    id = Column(Integer, primary_key=True, index=True)
    word = Column(String(120), nullable=False, unique=True, index=True)
    severity = Column(
        SQLEnum(BannedWordSeverity, name="banned_word_severity", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=BannedWordSeverity.BLOCK,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
