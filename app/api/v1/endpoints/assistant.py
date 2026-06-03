from fastapi import APIRouter, Depends, HTTPException
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.ai_service import AIService

router = APIRouter()

@router.post("/chat", response_model=AssistantResponse, responses={500: {"description": "Error interno del servidor de IA"}})
async def chat_with_assistant(request: AssistantRequest):
    """
    Endpoint para interactuar con Bappie IA.
    No requiere autenticación obligatoria para permitir ayuda antes del login.
    """
    try:
        service = AIService()
        # Convertir historial al formato que espera el servicio
        history_list = []
        if request.history:
            history_list = [{"role": m.role, "content": m.content} for m in request.history]
        
        ai_response = await service.get_response(request.message, history=history_list)
        return AssistantResponse(response=ai_response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
