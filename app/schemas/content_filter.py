from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

class BannedWordCreateRequest(BaseModel):
    word: str = Field(..., min_length=1, max_length=120)
    severity: Literal["block", "flag"] = "block"


class BannedWordResponse(BaseModel):
    id: int
    word: str
    severity: Literal["block", "flag"]
    created_at: datetime

    model_config = {"from_attributes": True}


class ContentFilterMatch(BaseModel):
    word: str
    severity: Literal["block", "flag"]


class ContentFilterValidationResponse(BaseModel):
    blocked: bool
    flagged: bool
    matches: list[ContentFilterMatch]


class ContentFilterFieldError(BaseModel):
    field: str
    message: str
    blocked: bool = True
    matches: list[ContentFilterMatch]


class ContentFilterPublicRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    context: Literal["chat", "review", "profile", "service", "generic"] = "generic"


class ContentFilterPublicResponse(BaseModel):
    blocked: bool
    flagged: bool
    match_count: int
    severity_detected: list[Literal["block", "flag"]]
    message: str | None = None
    normalized_text: str
