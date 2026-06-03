import logging
import aiohttp
import json
from typing import List, Dict, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class AIService:
    """
    Servicio de IA para Bappie.
    Utiliza Google Gemini (Free Tier) como opción principal por costo cero.
    Incluye un fallback inteligente para cuando no hay API Key.
    """
    
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    
    SYSTEM_INSTRUCTION = (
        "Eres Bappie IA, el asistente experto oficial de Bappsearch. Tu misión es resolver dudas sobre cómo funciona nuestra plataforma. "
        "Bappsearch conecta clientes en Chile con proveedores de servicios verificados (Plomería, Electricidad, Climatización, etc.).\n\n"
        "INFORMACIÓN CLAVE PARA RESPONDER:\n"
        "1. ¿CÓMO FUNCIONA?: Los usuarios pueden buscar servicios por categoría o geolocalización, ver perfiles de proveedores con reseñas reales y solicitar servicios directamente.\n"
        "2. COSTOS: Para el cliente, el uso de la app es GRATUITO. Para los proveedores, Bappsearch trabaja con un modelo de CERO COMISIÓN por servicio realizado, cobrando solo una suscripción fija o por contacto según el plan.\n"
        "3. SEGURIDAD: Todos los proveedores pasan por un proceso de verificación de identidad y documentos. Los pagos pueden ser procesados de forma segura a través de la app mediante Transbank o Mercado Pago.\n"
        "4. DISPONIBILIDAD: Estamos disponibles en todo Chile, principalmente en Santiago y regiones clave, funcionando 24/7 tanto en la web como en la app móvil (iOS y Android).\n\n"
        "REGLAS DE RESPUESTA:\n"
        "- Sé muy específico sobre el funcionamiento.\n"
        "- Si te preguntan algo ajeno a Bappsearch, responde: 'Como experto en Bappsearch, mi propósito es ayudarte a entender nuestra plataforma. ¿Tienes alguna duda sobre cómo buscar un servicio o registrarte?'\n"
        "- Usa un tono amable, tecnológico y chileno (amigable pero profesional).\n"
        "- Mantén las respuestas concisas."
    )

    def __init__(self):
        self.api_key = getattr(settings, "GEMINI_API_KEY", None)

    async def get_response(self, user_message: str, history: List[Dict[str, str]] = None) -> str:
        """
        Obtiene una respuesta de la IA.
        """
        if not self.api_key:
            return self._get_mock_response(user_message)

        try:
            async with aiohttp.ClientSession() as session:
                # Construir el prompt con el historial si existe
                contents = []
                
                # Instrucción de sistema
                contents.append({
                    "role": "user",
                    "parts": [{"text": f"Sigue estas instrucciones: {self.SYSTEM_INSTRUCTION}"}]
                })
                contents.append({
                    "role": "model",
                    "parts": [{"text": "Entendido. Soy Bappie IA y estoy listo para ayudar."}]
                })

                if history:
                    for msg in history:
                        role = "user" if msg["role"] == "user" else "model"
                        contents.append({
                            "role": role,
                            "parts": [{"text": msg["content"]}]
                        })

                # Nuevo mensaje
                contents.append({
                    "role": "user",
                    "parts": [{"text": user_message}]
                })

                payload = {
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.7,
                        "topK": 40,
                        "topP": 0.95,
                        "maxOutputTokens": 256,
                    }
                }

                url = f"{self.GEMINI_URL}?key={self.api_key}"
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        try:
                            return result["candidates"][0]["content"]["parts"][0]["text"]
                        except (KeyError, IndexError):
                            logger.error(f"Error parseando respuesta de Gemini: {result}")
                            return self._get_mock_response(user_message)
                    else:
                        error_text = await response.text()
                        logger.error(f"Error en API de Gemini ({response.status}): {error_text}")
                        return self._get_mock_response(user_message)

        except Exception as e:
            logger.exception(f"Error contactando servicio de IA: {e}")
            return self._get_mock_response(user_message)

    def _get_mock_response(self, text: str) -> str:
        """
        Respuesta 'costo cero' basada en reglas cuando no hay IA activa o hay errores.
        """
        text = text.lower()
        
        # Filtro básico de temas permitidos para el Mock
        ALLOWED_KEYWORDS = ['hola', 'bapp', 'servicio', 'precio', 'costo', 'comision', 'pago', 'proveedor', 'ayuda', 'soporte']
        if not any(k in text for k in ALLOWED_KEYWORDS):
            return "Lo siento, como asistente de Bappsearch, solo puedo ayudarte con temas relacionados a nuestra plataforma y servicios."

        if "hola" in text or "buenos" in text:
            return "¡Hola! Soy Bappie. ¿En qué puedo ayudarte con respecto a Bappsearch?"
        if "precio" in text or "costo" in text or "comision" in text:
            return "¡Bappsearch no cobra comisiones por servicios! El trato es directo entre tú y el proveedor."
        if "registro" in text or "cuenta" in text or "perfil" in text:
            return "Puedes crear tu cuenta en segundos desde el botón de 'Registro'. Si eres profesional, elige 'Soy Proveedor'."
        if "pagar" in text or "pago" in text:
            return "Aceptamos tarjetas de crédito, débito y transferencias a través de Webpay."
        
        return "Disculpa, estoy aprendiendo. ¿Podrías darme más detalles o contactar a soporte@bappsearch.com?"
