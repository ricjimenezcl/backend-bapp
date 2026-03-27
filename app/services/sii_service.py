import aiohttp
import hashlib
import hmac
import json
from datetime import datetime
from typing import Dict
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings

class SIIService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_electronic_receipt(
        self,
        booking_id: int,
        provider_rut: str,
        provider_business_name: str,
        provider_service_category: str,
        provider_address: str,
        client_rut: str,
        client_name: str,
        client_address: str,
        service_name: str,
        amount: float
    ) -> Dict:
        """Generar boleta electrónica para el SII Chile"""
        
        receipt_data = {
            "Encabezado": {
                "IdDoc": {
                    "TipoDTE": 39,  # Boleta electrónica
                    "FchEmis": datetime.now().strftime("%Y-%m-%d"),
                    "IndServicio": 3  # Servicios periódicos
                },
                "Emisor": {
                    "RUTEmisor": provider_rut,
                    "RznSoc": provider_business_name,
                    "GiroEmis": provider_service_category,
                    "Acteco": await self.get_acteco_code(provider_service_category),
                    "DirOrigen": provider_address,
                    "CmnaOrigen": await self.get_commune(provider_address)
                },
                "Receptor": {
                    "RUTRecep": client_rut or "66666666-6",  # RUT genérico si no tiene
                    "RznSocRecep": client_name,
                    "DirRecep": client_address,
                    "CmnaRecep": await self.get_commune(client_address)
                }
            },
            "Detalle": [
                {
                    "NmbItem": service_name,
                    "QtyItem": 1,
                    "PrcItem": amount,
                    "MontoItem": amount
                }
            ]
        }

        # Firmar documento digitalmente
        signed_receipt = await self.sign_receipt(receipt_data)

        # Enviar al SII
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{settings.SII_API_URL}/dte/document",
                json=signed_receipt,
                headers={
                    "Authorization": f"Bearer {await self.get_sii_token()}",
                    "Content-Type": "application/json"
                }
            ) as response:
                response_data = await response.json()
                await self.save_receipt_response(booking_id, response_data)
                return response_data

    async def sign_receipt(self, receipt_data: Dict) -> Dict:
        """Firmar digitalmente el documento para el SII"""
        message = json.dumps(receipt_data, sort_keys=True, ensure_ascii=False)
        
        # Usar HMAC para firma (en producción usar certificado digital)
        signature = hmac.new(
            settings.SII_SECRET_KEY.encode(),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return {
            **receipt_data,
            "Signature": signature,
            "Certificate": settings.SII_API_KEY
        }

    async def get_acteco_code(self, service_category: str) -> str:
        """Obtener código ACTECO según categoría de servicio"""
        acteco_codes = {
            "electricista": "432100",
            "mecanico": "452001", 
            "vulcanizacion": "452002",
            "gruas": "494100",
            "aseo": "812100",
            "jardineria": "813000",
            "costuras": "952100"
        }
        return acteco_codes.get(service_category, "999999")

    async def get_commune(self, address: str) -> str:
        """Extraer comuna desde la dirección"""
        # Implementar lógica para extraer comuna
        # Esto es una simplificación
        communes = ["SANTIAGO", "PROVIDENCIA", "LAS CONDES", "NUÑOA", "LA FLORIDA"]
        for commune in communes:
            if commune in address.upper():
                return commune
        return "SANTIAGO"

    async def get_sii_token(self) -> str:
        """Obtener token de autenticación del SII"""
        # Implementar autenticación con el SII
        return "sii-auth-token"

    async def save_receipt_response(self, booking_id: int, response_data: dict):
        """Guardar respuesta del SII en la base de datos"""
        # Implementar guardado en base de datos
        logger.info(f"SII Response for booking {booking_id}: {response_data}")


# ── Dispatcher desacoplado ────────────────────────────────────────────────────

import logging as _logging
logger = logging.getLogger(__name__)

_sii_logger = _logging.getLogger(__name__)


async def dispatch_sii_receipt_async(
    booking_id: int,
    provider_rut: str,
    provider_business_name: str,
    provider_service_category: str,
    provider_address: str,
    client_rut: str,
    client_name: str,
    client_address: str,
    service_name: str,
    amount: float,
    db: AsyncSession,
) -> None:
    """
    Genera y envía la boleta electrónica al SII de forma asíncrona y desacoplada.

    Llamar con asyncio.create_task() desde complete_booking para no bloquear la
    respuesta HTTP.  Cualquier error es logueado pero NO propaga excepciones.
    """
    try:
        sii = SIIService(db)
        await sii.generate_electronic_receipt(
            booking_id=booking_id,
            provider_rut=provider_rut,
            provider_business_name=provider_business_name,
            provider_service_category=provider_service_category,
            provider_address=provider_address,
            client_rut=client_rut,
            client_name=client_name,
            client_address=client_address,
            service_name=service_name,
            amount=amount,
        )
        _sii_logger.info(f"[SII] Boleta generada para booking {booking_id}")
    except Exception as exc:
        _sii_logger.warning(
            f"[SII] Error generando boleta para booking {booking_id} (non-critical): {exc}"
        )