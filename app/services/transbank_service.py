"""Transbank Webpay Plus service using transbank-sdk."""

from __future__ import annotations

from typing import Any, Dict

from app.core.config import settings

try:
    from transbank.common.integration_type import IntegrationType
    from transbank.common.options import WebpayOptions
    from transbank.webpay.webpay_plus.transaction import Transaction
except Exception as exc:  # pragma: no cover
    IntegrationType = None  # type: ignore[assignment]
    WebpayOptions = None  # type: ignore[assignment]
    Transaction = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class TransbankService:
    """Wrapper around Webpay Plus Transaction API."""

    INTEGRATION_COMMERCE_CODE = "597055555532"
    INTEGRATION_API_KEY = "579B464AD27157C5D4E7D17B7A9A4E74"

    def __init__(self) -> None:
        if Transaction is None or WebpayOptions is None or IntegrationType is None:
            raise RuntimeError(f"transbank-sdk is not available: {_IMPORT_ERROR}")

        environment = (getattr(settings, "TRANSBANK_ENVIRONMENT", "integration") or "integration").lower()
        use_integration = environment == "integration"

        commerce_code = settings.TRANSBANK_COMMERCE_CODE
        api_key = settings.TRANSBANK_API_KEY

        if use_integration:
            commerce_code = commerce_code or self.INTEGRATION_COMMERCE_CODE
            api_key = api_key or self.INTEGRATION_API_KEY

        if not commerce_code or not api_key:
            raise RuntimeError("Transbank credentials are not configured")

        integration_type = IntegrationType.TEST if use_integration else IntegrationType.LIVE
        self._tx = Transaction(WebpayOptions(commerce_code, api_key, integration_type))

    def create(self, buy_order: str, session_id: str, amount: int, return_url: str) -> Dict[str, Any]:
        return self._tx.create(buy_order=buy_order, session_id=session_id, amount=amount, return_url=return_url)

    def commit(self, token: str) -> Dict[str, Any]:
        return self._tx.commit(token=token)

    def status(self, token: str) -> Dict[str, Any]:
        return self._tx.status(token=token)
