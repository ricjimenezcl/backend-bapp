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

    user = db.query(User).filter(User.id == tx.user_id).first()
    if not user:
        return

    if product_type in ("CLIENT_UNLOCK_7", "CLIENT_UNLOCK_30", "PROVIDER_PREMIUM_MONTHLY"):
        user.has_premium = True
        user.premium_activated_at = now
        user.premium_expires_at = expires_at
        tx.expires_at = expires_at

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
