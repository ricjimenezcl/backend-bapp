import aiohttp
import json
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.core.config import settings

class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_payment_intent(
        self,
        booking_data: Dict,
        payment_method: str
    ) -> Dict[str, Any]:
        """Crear intento de pago con el gateway seleccionado"""
        if payment_method == "mercadopago":
            return await self.create_mercadopago_preference(booking_data)
        elif payment_method == "transbank":
            return await self.create_transbank_transaction(booking_data)
        elif payment_method == "webpay":
            return await self.create_webpay_transaction(booking_data)
        else:
            raise HTTPException(400, "Unsupported payment gateway")

    async def create_mercadopago_preference(self, booking_data: Dict) -> Dict:
        """Crear preferencia de pago en Mercado Pago"""
        preference = {
            "items": [
                {
                    "title": f"Servicio: {booking_data.get('service_name', 'Servicio')}",
                    "quantity": 1,
                    "currency_id": "CLP",
                    "unit_price": float(booking_data.get('amount', 0))
                }
            ],
            "back_urls": {
                "success": f"{settings.FRONTEND_URL}/payment/success",
                "failure": f"{settings.FRONTEND_URL}/payment/failure",
                "pending": f"{settings.FRONTEND_URL}/payment/pending"
            },
            "auto_return": "approved",
            "external_reference": str(booking_data.get('id')),
            "notification_url": f"{settings.BACKEND_URL}/api/v1/payments/webhook"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.mercadopago.com/checkout/preferences",
                json=preference,
                headers={
                    "Authorization": f"Bearer {settings.MERCADO_PAGO_ACCESS_TOKEN}",
                    "Content-Type": "application/json"
                }
            ) as response:
                data = await response.json()
                
                if response.status != 201:
                    raise HTTPException(500, "Error creating payment preference")
                
                return {
                    "payment_id": data["id"],
                    "init_point": data["init_point"],
                    "sandbox_init_point": data["sandbox_init_point"]
                }

    async def create_transbank_transaction(self, booking_data: Dict) -> Dict:
        """Crear transacción en Transbank"""
        # Implementar integración con Transbank
        transaction_data = {
            "buy_order": str(booking_data.get('id')),
            "session_id": f"session_{booking_data.get('id')}",
            "amount": float(booking_data.get('amount', 0)),
            "return_url": f"{settings.FRONTEND_URL}/payment/return"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://webpay3g.transbank.cl/rswebpaytransaction/api/webpay/v1.2/transactions",
                json=transaction_data,
                headers={
                    "Tbk-Api-Key-Id": settings.TRANSBANK_COMMERCE_CODE,
                    "Tbk-Api-Key-Secret": settings.TRANSBANK_API_KEY,
                    "Content-Type": "application/json"
                }
            ) as response:
                data = await response.json()
                return data

    async def create_webpay_transaction(self, booking_data: Dict) -> Dict:
        """Crear transacción en WebPay"""
        # Implementar integración con WebPay
        return {
            "token": "webpay_token",
            "url": "https://webpay.example.com"
        }

    async def confirm_payment(self, payment_intent_id: str):
        """Confirmar un pago completado"""
        # Implementar confirmación de pago
        return {"status": "success", "payment_id": payment_intent_id}

    async def handle_webhook(self, payload: dict):
        """Manejar webhooks de notificación de pagos"""
        # Implementar lógica de webhook
        print(f"Webhook received: {payload}")
        
        # Actualizar estado del pago en la base de datos
        # Enviar notificaciones, etc.
        
        return {"status": "processed"}