"""Webpay Plus endpoints for web checkout flow."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_current_user, get_db
from app.models.provider import Provider
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


def _build_return_url() -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/payment/callback"


def _apply_benefit(db: Session, tx: Transaction) -> None:
    product_type = tx.product_type
    if not product_type:
        return

    duration_days = PRODUCT_TYPE_CONFIG.get(product_type, {}).get("duration_days", 7)
    now = datetime.utcnow()
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


def _make_buy_order(user_id: int, product_type: str) -> str:
    suffix = uuid.uuid4().hex[:10].upper()
    return f"BAPP-{user_id}-{product_type}-{suffix}-{int(time.time())}"


@router.post("/transbank/create", response_model=WebpayCreateTransactionResponse)
def create_transbank_transaction(
    body: WebpayCreateTransactionRequest,
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

    buy_order = _make_buy_order(current_user.id, body.product_type.value)
    session_id = f"sid-{uuid.uuid4().hex[:20]}"

    try:
        tbk = TransbankService()
        result = tbk.create(
            buy_order=buy_order,
            session_id=session_id,
            amount=expected_amount,
            return_url=_build_return_url(),
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
        device_info={"provider": "transbank", "flow": "webpay_plus"},
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
    tx = (
        db.query(Transaction)
        .filter(Transaction.tbk_token == body.token, Transaction.user_id == current_user.id)
        .order_by(Transaction.id.desc())
        .first()
    )

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

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
        result = tbk.commit(token=body.token)
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
    tx.paid_at = datetime.utcnow()
    tx.validated_at = datetime.utcnow()
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
