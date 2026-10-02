"""
RevenueCat Webhook Endpoint

RevenueCat envía eventos server-to-server cada vez que ocurre un evento de
compra (INITIAL_PURCHASE, RENEWAL, CANCELLATION, EXPIRATION, etc.) para las
apps iOS/Android que usan el SDK de RevenueCat (ver
`frontend-bapp/src/app/services/apple-iap.service.ts`).

Este endpoint es el que faltaba para que esas compras nativas realmente
activen beneficios en el backend: hasta ahora el SDK compraba vía StoreKit
y RevenueCat registraba la compra, pero nada en `backend-bapp` se enteraba.

Modelo de negocio (confirmado con el usuario): NO hay renovación automática
real a nivel de negocio — los 3 planes de proveedor (7D/Mensual/Anual) son
compras únicas. El aviso de "tu plan está por vencer" ya existe vía el cron
`/transbank/internal/notify-plan-events` (genérico, no depende de la
pasarela), así que basta con crear la Transaction con `expires_at` correcto;
ese cron se encarga del resto.

Seguridad: RevenueCat reenvía en cada POST el valor exacto configurado en
Project settings > Integrations > Webhooks > "Authorization header value"
dentro del header `Authorization`. No es una firma HMAC, es comparación
directa de secreto compartido.

Docs: https://www.revenuecat.com/docs/integrations/webhooks
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
from typing import Optional
import json
import logging

from app.dependencies import get_db
from app.core.config import settings
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.services.product_service import ProductService
from app.services.transaction_service import TransactionService

logger = logging.getLogger(__name__)

router = APIRouter()

# Eventos de RevenueCat que representan una compra que debe activar beneficio.
# (Se excluyen deliberadamente CANCELLATION/EXPIRATION/BILLING_ISSUE/REFUND/
# TRANSFER: dado que los 3 planes de proveedor son compras únicas sin
# renovación automática real, no hay acción de beneficio que tomar en esos
# eventos; el cron de notificación de vencimiento ya avisa al usuario por
# fecha, no por evento de la tienda).
_BENEFIT_EVENT_TYPES = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "NON_RENEWING_PURCHASE",
    "UNCANCELLATION",
    "PRODUCT_CHANGE",
}

# RevenueCat "store" -> nuestro valor de `platform` (products/transactions)
_STORE_TO_PLATFORM = {
    "app_store": "apple_iap",
    "mac_app_store": "apple_iap",
    "play_store": "google_play",
}


def _record_webhook_event(db: Session, event: dict, raw_payload: dict) -> Optional[WebhookEvent]:
    """Inserta el evento para idempotencia. Retorna None si ya existía (duplicado)."""
    webhook_event = WebhookEvent(
        event_id=str(event.get("id", "")),
        provider="revenuecat",
        event_type=event.get("type"),
        payload=raw_payload,
    )
    db.add(webhook_event)
    try:
        db.commit()
        db.refresh(webhook_event)
        return webhook_event
    except IntegrityError:
        db.rollback()
        return None


@router.post("/revenuecat/webhook", include_in_schema=False)
async def revenuecat_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Webhook de RevenueCat. Siempre responde 200 (salvo auth inválida) para
    evitar que RevenueCat reintente indefinidamente; los errores de negocio
    quedan registrados en `webhook_events.error_message` para revisión manual.
    """
    # --- Autenticación: Authorization header con secreto compartido ---
    expected = settings.REVENUECAT_WEBHOOK_AUTH_HEADER
    provided = request.headers.get("authorization", "")
    if not expected:
        logger.warning("[RevenueCat webhook] REVENUECAT_WEBHOOK_AUTH_HEADER no configurado; rechazando por seguridad")
        raise HTTPException(status_code=403, detail="Webhook not configured")
    if provided != expected:
        logger.error("[RevenueCat webhook] Authorization header inválido")
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    body_bytes = await request.body()
    try:
        raw_payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        return {"status": "ignored", "reason": "invalid json"}

    event = raw_payload.get("event", {})
    event_id = str(event.get("id", ""))
    event_type = event.get("type")

    if not event_id:
        return {"status": "ignored", "reason": "missing event.id"}

    # --- Idempotencia: cada event.id se procesa exactamente una vez ---
    webhook_event = _record_webhook_event(db, event, raw_payload)
    if webhook_event is None:
        return {"status": "duplicate", "event_id": event_id}

    def _fail(reason: str) -> dict:
        webhook_event.error_message = reason
        db.commit()
        logger.warning(f"[RevenueCat webhook] {reason} (event_id={event_id}, type={event_type})")
        return {"status": "ignored", "reason": reason}

    # --- Solo procesar eventos que activan beneficio ---
    if event_type not in _BENEFIT_EVENT_TYPES:
        webhook_event.processed = True
        db.commit()
        return {"status": "ignored", "reason": f"event_type={event_type} no requiere acción"}

    # --- Resolver plataforma ---
    platform = _STORE_TO_PLATFORM.get(event.get("store", ""))
    if not platform:
        return _fail(f"store no soportado: {event.get('store')}")

    # --- Resolver usuario (app_user_id = User.id numérico, ver Purchases.configure appUserID) ---
    app_user_id = event.get("app_user_id", "")
    if not app_user_id.isdigit():
        return _fail(f"app_user_id no numérico (posible usuario anónimo): {app_user_id}")

    user = db.query(User).filter(User.id == int(app_user_id)).first()
    if not user:
        return _fail(f"user_id {app_user_id} no existe")

    # --- Resolver producto vía mapeo platform_products ---
    rc_product_id = event.get("product_id", "")
    platform_product = ProductService.get_platform_product_by_platform_id(
        db=db, platform=platform, platform_product_id=rc_product_id
    )
    if not platform_product:
        return _fail(f"product_id '{rc_product_id}' no mapeado en platform_products ({platform})")

    product = ProductService.get_product_by_id(db, platform_product.product_id)
    if not product:
        return _fail(f"Product id={platform_product.product_id} no existe")

    # --- Evitar doble activación si el mismo transaction_id de la tienda ya fue procesado ---
    store_transaction_id = str(event.get("transaction_id") or event_id)
    existing = TransactionService.check_duplicate_purchase(
        db=db, platform=platform, platform_transaction_id=store_transaction_id
    )
    if existing:
        webhook_event.processed = True
        webhook_event.transaction_id = existing.id
        db.commit()
        return {"status": "already_processed", "transaction_id": existing.id}

    # --- Crear transacción (ya pagada: la tienda/RevenueCat garantiza el cobro) ---
    transaction = TransactionService.create_transaction(
        db=db,
        user_id=user.id,
        product_id=product.id,
        platform=platform,
        amount=Decimal(str(product.price_clp)),
        currency="CLP",
        device_info={"source": "revenuecat", "store": event.get("store"), "environment": event.get("environment")},
    )

    TransactionService.mark_transaction_validated(
        db=db,
        transaction_id=transaction.id,
        platform_transaction_id=store_transaction_id,
        platform_order_id=event.get("original_transaction_id"),
        validation_response=json.dumps(event),
    )

    activated = TransactionService.activate_transaction_benefit(
        db=db,
        transaction_id=transaction.id,
        benefit_metadata={
            "source": "revenuecat",
            "event_id": event_id,
            "event_type": event_type,
            "store": event.get("store"),
            "product_id": rc_product_id,
        },
    )

    if not activated:
        return _fail(f"activate_transaction_benefit falló para transaction_id={transaction.id}")

    webhook_event.processed = True
    webhook_event.transaction_id = transaction.id
    db.commit()

    return {"status": "processed", "transaction_id": transaction.id}

