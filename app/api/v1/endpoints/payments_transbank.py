"""Webpay Plus endpoints for web checkout flow."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models.provider import Provider
from app.models.provider_service_slot import ProviderServiceSlot
from app.models.service_view_unlock import ServiceViewUnlock
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.schemas.payment import (
    WebpayCommitTransactionRequest,
    WebpayCommitTransactionResponse,
    WebpayCreateTransactionRequest,
    WebpayCreateTransactionResponse,
    WebpayStatusResponse,
)
from app.services.product_service import ProductService
from app.services.transbank_service import TransbankService

router = APIRouter(tags=["payments-transbank"])

_DEFAULT_PLAN_NAME = "Plan Premium"

# Tope de filas procesadas por bloque en cada corrida del cron de notificaciones
# de plan. Evita que un backlog grande (ej. primera corrida tras un deploy, o
# un pico puntual) bloquee la request por minutos: lo no procesado en esta
# corrida queda pendiente (columna *_notified_at sigue NULL) y se recoge en la
# siguiente corrida programada, sin riesgo de duplicados.
_PLAN_CRON_BATCH_LIMIT = 300


PRODUCT_TYPE_CONFIG: Dict[str, Dict[str, Any]] = {
    "CLIENT_UNLOCK_7": {
        "amount": 1490,
        "duration_days": 7,
        "skus": ["premium_access_7days", "client_unlock_7days"],
    },
    "CLIENT_UNLOCK_30": {
        "amount": 4990,
        "duration_days": 30,
        "skus": ["client_unlock_30days", "premium_access_30days"],
    },
    "PROVIDER_SERVICE_30": {
        "amount": 1990,
        "duration_days": 30,
        "skus": ["provider_service_30days", "service_publication_30days"],
    },
    "PROVIDER_SERVICE_YEAR": {
        "amount": 17990,
        "duration_days": 365,
        "skus": ["provider_service_1year"],
    },
    "PROVIDER_LEADS_7": {
        "amount": 1490,
        "duration_days": 7,
        "skus": ["provider_leads_unlock_7days"],
    },
    "PROVIDER_LEADS_30": {
        "amount": 4990,
        "duration_days": 30,
        "skus": ["provider_leads_unlock_30days"],
    },
    "PROVIDER_PREMIUM_MONTHLY": {
        "amount": 5990,
        "duration_days": 30,
        "skus": ["provider_premium_monthly"],
    },
    "PROVIDER_PREMIUM_ANNUAL": {
        "amount": 49990,
        "duration_days": 365,
        "skus": ["provider_premium_annual"],
    },
    # Planes bundle de proveedor (3 planes únicos, cada uno otorga TODOS los
    # beneficios juntos: premium + hasta 7 servicios activos + leads
    # desbloqueados). Reemplazan a los 6 productos granulares anteriores
    # para compras NUEVAS; los tipos anteriores se mantienen arriba solo
    # para no romper transacciones ya existentes/en curso.
    "PROVIDER_PLAN_7D": {
        "amount": 1490,
        "duration_days": 7,
        "skus": ["provider_plan_7days"],
    },
    "PROVIDER_PLAN_MONTHLY": {
        "amount": 5990,
        "duration_days": 30,
        "skus": ["provider_plan_monthly"],
    },
    "PROVIDER_PLAN_ANNUAL": {
        "amount": 49990,
        "duration_days": 365,
        "skus": ["provider_plan_annual"],
    },
}


def _get_product_for_type(db: Session, product_type: str):
    cfg = PRODUCT_TYPE_CONFIG.get(product_type)
    if not cfg:
        return None
    for sku in cfg["skus"]:
        product = ProductService.get_product_by_sku(db, sku)
        if product:
            return product
    return None


def _expected_amount(product_type: str, product) -> int:
    if product is not None and product.price_clp is not None:
        return int(product.price_clp)
    cfg = PRODUCT_TYPE_CONFIG.get(product_type)
    if not cfg:
        raise HTTPException(status_code=400, detail="Invalid product_type")
    return int(cfg["amount"])


def _is_allowed_base_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False

    normalized = f"{parsed.scheme}://{parsed.netloc}"
    allowed = {o.rstrip("/") for o in settings.ALLOWED_ORIGINS}
    allowed.add(settings.FRONTEND_URL.rstrip("/"))
    return normalized in allowed


def _is_local_origin(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return True

    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1"}


def _default_frontend_origin() -> str:
    configured = settings.FRONTEND_URL.rstrip("/")
    if not _is_local_origin(configured):
        return configured

    for origin in settings.ALLOWED_ORIGINS:
        normalized = origin.rstrip("/")
        if not _is_local_origin(normalized):
            return normalized

    return configured


def _resolve_frontend_origin(request: Request, preferred_return_url: str | None = None) -> str:
    """Determina el origin (scheme+host) del frontend al que se debe volver
    tras el pago, validando contra ALLOWED_ORIGINS/FRONTEND_URL."""

    # 1) URL explícita enviada por frontend web/móvil webview
    if preferred_return_url and _is_allowed_base_url(preferred_return_url):
        parsed = urlparse(preferred_return_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    # 2) Origin del request actual
    origin = request.headers.get("origin")
    if origin and _is_allowed_base_url(origin):
        return origin.rstrip("/")

    # 3) Referer como fallback
    referer = request.headers.get("referer")
    if referer:
        try:
            parsed_ref = urlparse(referer)
            ref_base = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
            if _is_allowed_base_url(ref_base):
                return ref_base
        except Exception:
            pass

    # 4) Configuración global por defecto
    return _default_frontend_origin()


def _extract_frontend_return_path(preferred_return_url: str | None = None) -> str:
    # Siempre se redirige a /payment/callback tras el retorno de Webpay,
    # independientemente de cualquier query param adicional que venga en
    # preferred_return_url. Esto garantiza que el frontend SIEMPRE ejecute
    # el commit() de la transacción antes de navegar a cualquier otra
    # pantalla (perfil, home, etc.). El destino final post-commit lo decide
    # el propio frontend (ver PaymentComponent.commit()).
    return "/payment/callback"


def _build_return_url(request: Request, buy_order: str) -> str:
    """Construye la return_url que se envía a Transbank.

    Transbank Webpay Plus retorna al comercio mediante un POST (form-encoded,
    con token_ws en el body) hacia esta return_url. Como el frontend es una
    SPA estática, no puede leer parámetros enviados por POST. Por eso la
    return_url apunta a un endpoint puente en este backend
    (`/transbank/return`), que recibe el POST de Transbank, resuelve la
    transacción y redirige (303) al frontend con un buy_order y estado de
    pago, evitando exponer token_ws en la URL final.
    """
    backend_base = str(request.base_url).rstrip("/")
    query = urlencode({"buy_order": buy_order})
    return f"{backend_base}/api/v1/payments/transbank/return?{query}"


def _get_transaction_redirect_context(tx: Transaction | None) -> tuple[str, str]:
    default_origin = _default_frontend_origin()
    default_path = "/payment/callback"
    if not tx or not isinstance(tx.device_info, dict):
        return default_origin, default_path

    origin = tx.device_info.get("frontend_origin")
    if not isinstance(origin, str) or not _is_allowed_base_url(origin):
        origin = default_origin

    path = tx.device_info.get("frontend_return_path")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        path = default_path

    return origin.rstrip("/"), path


def _apply_benefit(db: Session, tx: Transaction) -> None:
    product_type = tx.product_type
    if not product_type:
        return

    duration_days = PRODUCT_TYPE_CONFIG.get(product_type, {}).get("duration_days", 7)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = now + timedelta(days=duration_days)
    tx.activated_at = now

    user = db.query(User).filter(User.id == tx.user_id).first()
    if not user:
        return

    if product_type in (
        "CLIENT_UNLOCK_7",
        "CLIENT_UNLOCK_30",
        "PROVIDER_PREMIUM_MONTHLY",
        "PROVIDER_PREMIUM_ANNUAL",
        "PROVIDER_PLAN_7D",
        "PROVIDER_PLAN_MONTHLY",
        "PROVIDER_PLAN_ANNUAL",
    ):
        user.has_premium = True
        user.premium_activated_at = now
        user.premium_expires_at = expires_at
        tx.expires_at = expires_at

        if product_type in (
            "PROVIDER_PREMIUM_MONTHLY",
            "PROVIDER_PREMIUM_ANNUAL",
            "PROVIDER_PLAN_7D",
            "PROVIDER_PLAN_MONTHLY",
            "PROVIDER_PLAN_ANNUAL",
        ):
            # Premium Proveedor / Planes bundle otorgan hasta 7 servicios
            # activos en total (2 gratis + 5 adicionales, slots 3-7).
            provider = db.query(Provider).filter(Provider.user_id == user.id).first()
            if provider:
                _activate_premium_service_slots(db, provider, tx, now, expires_at)

                if product_type in ("PROVIDER_PLAN_7D", "PROVIDER_PLAN_MONTHLY", "PROVIDER_PLAN_ANNUAL"):
                    # Los 3 planes bundle además desbloquean el acceso a
                    # leads (clientes interesados) durante toda su vigencia,
                    # a diferencia de PROVIDER_PREMIUM_* (legacy) que no lo
                    # incluía.
                    unlock = ServiceViewUnlock(
                        provider_id=provider.id,
                        payment_reference=f"TBK-{tx.buy_order}",
                        amount=Decimal(tx.amount),
                        currency="CLP",
                        status="active",
                        unlocked_at=now,
                        expires_at=expires_at,
                    )
                    db.add(unlock)

    elif product_type in ("PROVIDER_LEADS_7", "PROVIDER_LEADS_30"):
        provider = db.query(Provider).filter(Provider.user_id == user.id).first()
        if provider:
            unlock = ServiceViewUnlock(
                provider_id=provider.id,
                payment_reference=f"TBK-{tx.buy_order}",
                amount=Decimal(tx.amount),
                currency="CLP",
                status="active",
                unlocked_at=now,
                expires_at=expires_at,
            )
            db.add(unlock)
            tx.expires_at = expires_at

    elif product_type in ("PROVIDER_SERVICE_30", "PROVIDER_SERVICE_YEAR"):
        tx.expires_at = expires_at
        provider = db.query(Provider).filter(Provider.user_id == user.id).first()
        if provider:
            occupied_numbers = [
                s.slot_number
                for s in db.query(ProviderServiceSlot.slot_number)
                .filter(
                    ProviderServiceSlot.provider_id == provider.id,
                    ProviderServiceSlot.is_active.is_(True),
                )
                .all()
            ]
            next_slot_number = 3  # Slots 1 y 2 son gratuitos
            while next_slot_number in occupied_numbers:
                next_slot_number += 1

            slot = (
                db.query(ProviderServiceSlot)
                .filter(
                    ProviderServiceSlot.provider_id == provider.id,
                    ProviderServiceSlot.slot_number == next_slot_number,
                )
                .first()
            )
            if not slot:
                slot = ProviderServiceSlot(
                    provider_id=provider.id,
                    slot_number=next_slot_number,
                    is_free=False,
                )
                db.add(slot)

            slot.transaction_id = tx.id
            slot.activated_at = now
            slot.expires_at = expires_at
            slot.is_active = True


def _activate_premium_service_slots(
    db: Session,
    provider: Provider,
    tx: Transaction,
    now: datetime,
    expires_at: datetime,
) -> None:
    """Crea o reactiva los slots 3 a 7 (5 servicios adicionales) para un
    proveedor con Premium activo. Slots 1-2 son gratis y no se tocan aquí."""
    for slot_number in range(3, 8):
        slot = (
            db.query(ProviderServiceSlot)
            .filter(
                ProviderServiceSlot.provider_id == provider.id,
                ProviderServiceSlot.slot_number == slot_number,
            )
            .first()
        )
        if not slot:
            slot = ProviderServiceSlot(
                provider_id=provider.id,
                slot_number=slot_number,
                is_free=False,
            )
            db.add(slot)

        slot.transaction_id = tx.id
        slot.activated_at = now
        slot.expires_at = expires_at
        slot.is_active = True


def _make_buy_order() -> str:
    # Formato: BAPP{timestamp_short}{random_hex} = ~18-20 chars (max 26 for Transbank)
    ts = int(time.time()) % 1000000  # últimos 6 dígitos del timestamp
    rand = uuid.uuid4().hex[:4].upper()
    return f"BAPP{ts}{rand}"


@router.api_route("/transbank/return", methods=["GET", "POST"], include_in_schema=False)
async def transbank_return_bridge(request: Request):
    """Endpoint puente que recibe el retorno de Transbank.

    Transbank Webpay Plus redirige al comercio con un POST form-encoded
    (token_ws si el pago fue autorizado, o TBK_TOKEN si el usuario canceló/
    abortó en Webpay). Este endpoint extrae esos valores, busca el contexto
    guardado de la transacción y redirige (303, GET) al frontend SPA con un
    estado y buy_order, sin exponer token_ws en la URL final.
    """
    token_ws: str | None = None
    tbk_token: str | None = None
    buy_order: str | None = request.query_params.get("buy_order")

    if request.method == "POST":
        try:
            form = await request.form()
        except Exception:
            form = {}
        token_ws = form.get("token_ws") or None
        tbk_token = form.get("TBK_TOKEN") or None

    # Fallback / soporte para pruebas manuales vía GET
    if not token_ws:
        token_ws = request.query_params.get("token_ws")
    if not tbk_token:
        tbk_token = request.query_params.get("TBK_TOKEN")

    db = next(get_db())
    try:
        tx = None
        if token_ws:
            tx = (
                db.query(Transaction)
                .filter(Transaction.tbk_token == token_ws)
                .order_by(Transaction.id.desc())
                .first()
            )
        if not tx and buy_order:
            tx = (
                db.query(Transaction)
                .filter(Transaction.buy_order == buy_order)
                .order_by(Transaction.id.desc())
                .first()
            )

        frontend_origin, return_path = _get_transaction_redirect_context(tx)
        resolved_buy_order = tx.buy_order if tx and tx.buy_order else buy_order

        callback_params: Dict[str, str] = {"provider": "transbank"}
        callback_params["status"] = "cancelled" if tbk_token else "success"
        if resolved_buy_order:
            callback_params["buy_order"] = resolved_buy_order

        separator = "&" if "?" in return_path else "?"
        query = urlencode(callback_params)
        redirect_url = f"{frontend_origin}{return_path}{separator}{query}"
    finally:
        db.close()

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/transbank/create", response_model=WebpayCreateTransactionResponse)
def create_transbank_transaction(
    body: WebpayCreateTransactionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = PRODUCT_TYPE_CONFIG.get(body.product_type.value)
    if not cfg:
        raise HTTPException(status_code=400, detail="Unsupported product_type")

    # Acceso Cliente / Premium Proveedor son de vigencia única (no se acumulan
    # ni se reemplazan): si ya hay acceso activo, se bloquea la recompra hasta
    # que expire, evitando pagos duplicados por error o confusión de UI.
    if body.product_type.value in (
        "CLIENT_UNLOCK_7",
        "CLIENT_UNLOCK_30",
        "PROVIDER_PREMIUM_MONTHLY",
        "PROVIDER_PREMIUM_ANNUAL",
        "PROVIDER_PLAN_7D",
        "PROVIDER_PLAN_MONTHLY",
        "PROVIDER_PLAN_ANNUAL",
    ) and current_user.is_premium_active:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ya tienes acceso activo hasta "
                f"{current_user.premium_expires_at.isoformat() if current_user.premium_expires_at else ''}. "
                "Podrás comprar un nuevo período cuando expire."
            ),
        )

    product = _get_product_for_type(db, body.product_type.value)
    expected_amount = _expected_amount(body.product_type.value, product)

    if int(body.amount) != int(expected_amount):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid amount for {body.product_type.value}. Expected {expected_amount}",
        )

    buy_order = _make_buy_order()
    session_id = uuid.uuid4().hex[:16]  # 16 chars hex, max 26 for Transbank

    frontend_origin = _resolve_frontend_origin(request, body.return_url)
    frontend_return_path = _extract_frontend_return_path(body.return_url)

    try:
        tbk = TransbankService()
        result = tbk.create(
            buy_order=buy_order,
            session_id=session_id,
            amount=expected_amount,
            return_url=_build_return_url(request, buy_order),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Transbank create failed: {str(exc)}") from exc

    token = result.get("token")
    url = result.get("url")
    if not token or not url:
        raise HTTPException(status_code=502, detail="Invalid response from Transbank")

    tx = Transaction(
        user_id=current_user.id,
        product_id=product.id if product else None,
        platform="web",
        amount=Decimal(expected_amount),
        currency="CLP",
        status=TransactionStatus.PENDING,
        buy_order=buy_order,
        platform_order_id=buy_order,
        transaction_id=session_id,
        tbk_token=token,
        purchase_token=token,
        product_type=body.product_type.value,
        device_info={
            "provider": "transbank",
            "flow": "webpay_plus",
            "frontend_origin": frontend_origin,
            "frontend_return_path": frontend_return_path,
        },
    )

    db.add(tx)
    db.commit()

    return WebpayCreateTransactionResponse(
        success=True,
        token=token,
        url=url,
        buy_order=buy_order,
        session_id=session_id,
        amount=expected_amount,
        product_type=body.product_type,
    )


@router.post("/transbank/commit", response_model=WebpayCommitTransactionResponse)
def commit_transbank_transaction(
    body: WebpayCommitTransactionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.token and not body.buy_order:
        raise HTTPException(status_code=400, detail="token or buy_order is required")

    tx_query = db.query(Transaction).filter(Transaction.user_id == current_user.id)
    if body.token:
        tx_query = tx_query.filter(Transaction.tbk_token == body.token)
    else:
        tx_query = tx_query.filter(Transaction.buy_order == body.buy_order)

    tx = tx_query.order_by(Transaction.id.desc()).first()

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not tx.tbk_token:
        raise HTTPException(status_code=400, detail="Transaction has no Transbank token")

    if tx.status == TransactionStatus.COMPLETED:
        return WebpayCommitTransactionResponse(
            success=True,
            status=tx.status.value,
            buy_order=tx.buy_order,
            authorization_code=tx.authorization_code,
            amount=int(tx.amount),
            transaction_id=tx.id,
            expires_at=tx.expires_at,
        )

    try:
        tbk = TransbankService()
        result = tbk.commit(token=tx.tbk_token)
    except Exception as exc:
        tx.status = TransactionStatus.FAILED
        tx.validation_response = str(exc)
        db.commit()
        raise HTTPException(status_code=502, detail=f"Transbank commit failed: {str(exc)}") from exc

    response_code = int(result.get("response_code", -1))
    amount = int(result.get("amount", 0))
    buy_order = result.get("buy_order", tx.buy_order)
    auth_code = result.get("authorization_code")

    tx.buy_order = buy_order
    tx.authorization_code = auth_code
    tx.platform_transaction_id = auth_code
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    tx.paid_at = now
    tx.validated_at = now
    tx.validation_response = str(result)

    if response_code != 0:
        tx.status = TransactionStatus.FAILED
        db.commit()
        return WebpayCommitTransactionResponse(
            success=False,
            status=tx.status.value,
            buy_order=buy_order,
            amount=amount,
            transaction_id=tx.id,
            error=result.get("status", "Transbank rejected transaction"),
        )

    if amount != int(tx.amount):
        tx.status = TransactionStatus.FAILED
        tx.validation_response = f"Amount mismatch: tbk={amount} local={tx.amount}"
        db.commit()
        raise HTTPException(status_code=400, detail="Amount mismatch")

    tx.status = TransactionStatus.COMPLETED
    _apply_benefit(db, tx)
    db.commit()

    return WebpayCommitTransactionResponse(
        success=True,
        status=tx.status.value,
        buy_order=tx.buy_order,
        authorization_code=tx.authorization_code,
        amount=int(tx.amount),
        transaction_id=tx.id,
        expires_at=tx.expires_at,
    )


@router.get("/transbank/status/{buy_order}", response_model=WebpayStatusResponse)
def get_transbank_status(
    buy_order: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tx = (
        db.query(Transaction)
        .filter(Transaction.buy_order == buy_order, Transaction.user_id == current_user.id)
        .order_by(Transaction.id.desc())
        .first()
    )

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    tbk_status = None
    if tx.tbk_token:
        try:
            tbk_status = TransbankService().status(token=tx.tbk_token)
        except Exception:
            tbk_status = None

    return WebpayStatusResponse(
        success=True,
        buy_order=buy_order,
        local_status=tx.status.value,
        product_type=tx.product_type,
        amount=int(tx.amount),
        token=tx.tbk_token,
        transbank=tbk_status,
    )


@router.post("/transbank/internal/notify-expiring-slots", include_in_schema=False)
async def notify_expiring_service_slots(
    request: Request,
    db: Session = Depends(get_db),
):
    """Endpoint interno protegido por secreto compartido, pensado para ser
    invocado por un cron (Render Cron Job / cron-job.org) 1 vez al día.

    Envía un email de recordatorio a los proveedores cuyo slot de servicio
    pagado (provider_service_slots) vence dentro de los próximos 5 días,
    evitando reenvíos duplicados via `expiry_reminder_sent_at`.
    """
    cron_secret = settings.CRON_SECRET
    provided = request.headers.get("X-Cron-Secret")
    if not cron_secret or provided != cron_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_end = now + timedelta(days=5)

    slots = (
        db.query(ProviderServiceSlot)
        .filter(
            ProviderServiceSlot.is_active.is_(True),
            ProviderServiceSlot.expires_at.isnot(None),
            ProviderServiceSlot.expires_at > now,
            ProviderServiceSlot.expires_at <= window_end,
            ProviderServiceSlot.expiry_reminder_sent_at.is_(None),
        )
        .all()
    )

    from app.services.email_service import email_service

    sent = 0
    failed = 0
    for slot in slots:
        provider = db.query(Provider).filter(Provider.id == slot.provider_id).first()
        user = db.query(User).filter(User.id == provider.user_id).first() if provider else None
        if not user or not user.email:
            continue

        business_name = "tu servicio"
        if slot.service_provider_id:
            from app.models.provider import ServiceProvider
            sp = db.query(ServiceProvider).filter(ServiceProvider.id == slot.service_provider_id).first()
            if sp:
                business_name = sp.business_name

        try:
            ok = await email_service.send_service_slot_expiring_soon_email(
                email=user.email,
                business_name=business_name,
                expires_at=slot.expires_at,
            )
            if ok:
                slot.expiry_reminder_sent_at = now
                db.commit()
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    return {"checked": len(slots), "sent": sent, "failed": failed}


def _plan_profile_url(user: User) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/provider/tabs/profile" if user.role == "PROVIDER" else f"{base}/client/tabs/profile"


def _plan_user_display_name(user: User) -> str:
    client_profile = getattr(user, "client_profile", None)
    if client_profile and getattr(client_profile, "full_name", None):
        return client_profile.full_name
    provider_profile = getattr(user, "provider_profile", None)
    if provider_profile and getattr(provider_profile, "full_name", None):
        return provider_profile.full_name
    return user.email


@router.post("/transbank/internal/notify-plan-events", include_in_schema=False)
async def notify_plan_events(
    request: Request,
    db: Session = Depends(get_db),
):
    """Endpoint interno protegido por secreto compartido, pensado para ser
    invocado por un cron (Render Cron Job / cron-job.org) 1 vez al día.

    Recorre `transactions` (independiente de la pasarela de pago: Transbank,
    Mercado Pago, Google Play, Apple IAP) y envía notificación in-app (push
    vía WebSocket) + email para 3 eventos del ciclo de vida de un plan:
      1. Activación/inicio de plan (`activated_at` reciente, sin notificar).
      2. Aviso de renovación (vence dentro de los próximos 5 días).
      3. Término/expiración (ya venció), marcando además la transacción
         como `EXPIRED`.

    Cada evento se marca con su propia columna `*_notified_at`/`*_sent_at`
    en `transactions` para evitar reenvíos duplicados en corridas sucesivas.
    """
    cron_secret = settings.CRON_SECRET
    provided = request.headers.get("X-Cron-Secret")
    if not cron_secret or provided != cron_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.models.notification import Notification, NotificationType
    from app.models.product import Product
    from app.services.email_service import email_service
    from app.api.websocket.connection_manager import connection_manager

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_end = now + timedelta(days=5)

    async def _notify_in_app(user: User, notif_type: "NotificationType", title: str, content: str, tx: Transaction) -> None:
        try:
            notif = Notification(
                user_id=user.id,
                notification_type=notif_type,
                title=title,
                content=content,
                related_entity_type="transaction",
                related_entity_id=tx.id,
            )
            db.add(notif)
            db.commit()
            db.refresh(notif)

            ws_message = {
                **connection_manager.format_notification(
                    notification_id=notif.id,
                    notification_type=notif_type.value,
                    title=title,
                    content=content,
                    related_entity_id=tx.id,
                ),
                "channel": "notification",
                "data": {"transaction_id": tx.id},
            }
            await connection_manager.broadcast_to_user(user.id, ws_message)
        except Exception:
            db.rollback()

    result = {
        "activated": {"checked": 0, "sent": 0, "failed": 0},
        "renewal_reminder": {"checked": 0, "sent": 0, "failed": 0},
        "expired": {"checked": 0, "sent": 0, "failed": 0},
    }

    # 1) Activación / inicio de plan
    activated_txs = (
        db.query(Transaction)
        .filter(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.activated_at.isnot(None),
            Transaction.activation_notified_at.is_(None),
        )
        .limit(_PLAN_CRON_BATCH_LIMIT)
        .all()
    )
    for tx in activated_txs:
        result["activated"]["checked"] += 1
        user = db.query(User).filter(User.id == tx.user_id).first()
        if not user or not user.email:
            continue
        product = db.query(Product).filter(Product.id == tx.product_id).first() if tx.product_id else None
        product_name = product.name if product else _DEFAULT_PLAN_NAME
        try:
            ok = await email_service.send_plan_activated_email(
                email=user.email,
                user_name=_plan_user_display_name(user),
                product_name=product_name,
                expires_at=tx.expires_at,
                profile_url=_plan_profile_url(user),
            )
            await _notify_in_app(
                user, NotificationType.PLAN_ACTIVATED,
                "¡Tu plan está activo!",
                f"El plan {product_name} fue activado correctamente.",
                tx,
            )
            tx.activation_notified_at = now
            db.commit()
            result["activated"]["sent" if ok else "failed"] += 1
        except Exception:
            db.rollback()
            result["activated"]["failed"] += 1

    # 2) Aviso de renovación (vence dentro de los próximos 5 días)
    expiring_txs = (
        db.query(Transaction)
        .filter(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.expires_at.isnot(None),
            Transaction.expires_at > now,
            Transaction.expires_at <= window_end,
            Transaction.renewal_reminder_sent_at.is_(None),
        )
        .limit(_PLAN_CRON_BATCH_LIMIT)
        .all()
    )
    for tx in expiring_txs:
        result["renewal_reminder"]["checked"] += 1
        user = db.query(User).filter(User.id == tx.user_id).first()
        if not user or not user.email:
            continue
        product = db.query(Product).filter(Product.id == tx.product_id).first() if tx.product_id else None
        product_name = product.name if product else _DEFAULT_PLAN_NAME
        try:
            ok = await email_service.send_plan_expiring_soon_email(
                email=user.email,
                user_name=_plan_user_display_name(user),
                product_name=product_name,
                expires_at=tx.expires_at,
                renew_url=_plan_profile_url(user),
            )
            await _notify_in_app(
                user, NotificationType.PLAN_EXPIRING_SOON,
                "Tu plan vence pronto",
                f"El plan {product_name} vence el {tx.expires_at.strftime('%d/%m/%Y')}. Renueva para no perder tus beneficios.",
                tx,
            )
            tx.renewal_reminder_sent_at = now
            db.commit()
            result["renewal_reminder"]["sent" if ok else "failed"] += 1
        except Exception:
            db.rollback()
            result["renewal_reminder"]["failed"] += 1

    # 3) Término / expiración de plan
    expired_txs = (
        db.query(Transaction)
        .filter(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.expires_at.isnot(None),
            Transaction.expires_at <= now,
            Transaction.expiration_notified_at.is_(None),
        )
        .limit(_PLAN_CRON_BATCH_LIMIT)
        .all()
    )
    for tx in expired_txs:
        result["expired"]["checked"] += 1
        user = db.query(User).filter(User.id == tx.user_id).first()
        if not user or not user.email:
            continue
        product = db.query(Product).filter(Product.id == tx.product_id).first() if tx.product_id else None
        product_name = product.name if product else _DEFAULT_PLAN_NAME
        try:
            ok = await email_service.send_plan_expired_email(
                email=user.email,
                user_name=_plan_user_display_name(user),
                product_name=product_name,
                renew_url=_plan_profile_url(user),
            )
            await _notify_in_app(
                user, NotificationType.PLAN_EXPIRED,
                "Tu plan ha finalizado",
                f"El plan {product_name} venció. Renueva cuando quieras para recuperar tus beneficios.",
                tx,
            )
            tx.status = TransactionStatus.EXPIRED
            tx.expiration_notified_at = now
            db.commit()
            result["expired"]["sent" if ok else "failed"] += 1
        except Exception:
            db.rollback()
            result["expired"]["failed"] += 1

    return result
