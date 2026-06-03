from pydantic import BaseModel
from typing import List, Optional

class ChatMessage(BaseModel):
    role: str # 'user' o 'assistant'
    content: str

class AssistantRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None

class AssistantResponse(BaseModel):
    response: str
