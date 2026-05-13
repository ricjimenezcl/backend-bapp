"""
Payment Verification Endpoints
Handles payment verification for Google Play, Apple IAP, Transbank, and Mercado Pago.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
from typing import Optional
from decimal import Decimal
import hashlib
import hmac
import json

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.services.validators import (
    GooglePlayValidator,
    AppleIAPValidator,
    TransbankValidator
)
from app.services.product_service import ProductService
from app.services.transaction_service import TransactionService
from app.services.email_service import email_service
from app.schemas.monetization import (
    GooglePlayVerificationRequest,
    AppleIAPVerificationRequest,
    TransbankVerificationRequest,
    PaymentVerificationResponse
)
from app.core.config import settings

router = APIRouter()


# Initialize validators (credentials from settings)
google_validator = GooglePlayValidator(
    package_name=getattr(settings, 'GOOGLE_PLAY_PACKAGE_NAME', 'io.ionic.bappsearch'),
    service_account_file=getattr(settings, 'GOOGLE_PLAY_SERVICE_ACCOUNT_FILE', None)
)

apple_validator = AppleIAPValidator(
    shared_secret=getattr(settings, 'APPLE_IAP_SHARED_SECRET', None),
    use_sandbox=getattr(settings, 'APPLE_IAP_USE_SANDBOX', True)
)

transbank_validator = TransbankValidator(
    commerce_code=getattr(settings, 'TRANSBANK_COMMERCE_CODE', ''),
    api_key=getattr(settings, 'TRANSBANK_API_KEY', ''),
    use_integration=getattr(settings, 'TRANSBANK_USE_INTEGRATION', True)
)


@router.post("/verify/google-play", response_model=PaymentVerificationResponse)
async def verify_google_play_purchase(
    request: GooglePlayVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    http_request: Request = None
):
    """
    Verify Google Play purchase and activate benefit
    
    Request Body:
    - purchase_token: Google Play purchase token
    - product_id: Product ID from Google Play (e.g., io.ionic.bappsearch.premium_7days)
    - package_name: App package name (default: io.ionic.bappsearch)
    
    Returns:
    - PaymentVerificationResponse with transaction details
    """
    try:
        # Get platform product mapping
        platform_product = ProductService.get_platform_product_by_platform_id(
            db=db,
            platform="google_play",
            platform_product_id=request.product_id
        )
        
        if not platform_product:
            raise HTTPException(
                status_code=404,
                detail=f"Product '{request.product_id}' not found in catalog"
            )
        
        # Get internal product
        product = ProductService.get_product_by_id(db, platform_product.product_id)
        
        if not product:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )
        
        # Check for duplicate purchase
        existing = TransactionService.check_duplicate_purchase(
            db=db,
            platform="google_play",
            purchase_token=request.purchase_token
        )
        
        if existing:
            return PaymentVerificationResponse(
                success=False,
                message="Purchase already processed",
                transaction_id=existing.id,
                error="Duplicate purchase"
            )
        
        # Verify with Google Play
        verification = await google_validator.verify_purchase(
            product_id=request.product_id,
            purchase_token=request.purchase_token
        )
        
        if not verification.get("valid"):
            return PaymentVerificationResponse(
                success=False,
                message="Purchase verification failed",
                error=verification.get("error", "Invalid purchase")
            )
        
        # Get client IP and user agent
        client_ip = http_request.client.host if http_request else None
        user_agent = http_request.headers.get("user-agent") if http_request else None
        
        # Create transaction
        transaction = TransactionService.create_transaction(
            db=db,
            user_id=current_user.id,
            product_id=product.id,
            platform="google_play",
            amount=Decimal(str(product.price_clp)),
            currency="CLP",
            purchase_token=request.purchase_token,
            ip_address=client_ip,
            user_agent=user_agent,
            device_info={
                "platform": "android",
                "package_name": request.package_name
            }
        )
        
        # Mark as validated
        TransactionService.mark_transaction_validated(
            db=db,
            transaction_id=transaction.id,
            platform_transaction_id=verification.get("order_id", ""),
            validation_response=str(verification.get("raw_response"))
        )
        
        # Activate benefit
        transaction = TransactionService.activate_transaction_benefit(
            db=db,
            transaction_id=transaction.id,
            benefit_metadata={
                "platform": "google_play",
                "product_id": request.product_id,
                "order_id": verification.get("order_id")
            }
        )
        
        # Send confirmation email
        try:
            email_service.send_purchase_confirmation(
                user_email=current_user.email,
                user_name=current_user.full_name or current_user.email,
                transaction=transaction,
                product=product
            )
        except Exception as email_error:
            logger.error(f"Failed to send confirmation email: {email_error}")
            # Don't fail the transaction if email fails
        
        # Acknowledge purchase (required by Google Play)
        await google_validator.acknowledge_purchase(
            product_id=request.product_id,
            purchase_token=request.purchase_token
        )
        
        return PaymentVerificationResponse(
            success=True,
            transaction_id=transaction.id,
            message="Purchase verified and benefit activated",
            expires_at=transaction.expires_at
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Payment verification failed: {str(e)}"
        )


@router.post("/verify/apple-iap", response_model=PaymentVerificationResponse)
async def verify_apple_iap_purchase(
    request: AppleIAPVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    http_request: Request = None
):
    """
    Verify Apple In-App Purchase and activate benefit
    
    Request Body:
    - receipt_data: Base64 encoded receipt from Apple
    - shared_secret: App-specific shared secret (optional, uses server config)
    
    Returns:
    - PaymentVerificationResponse with transaction details
    """
    try:
        # Verify with Apple
        verification = await apple_validator.verify_receipt(
            receipt_data=request.receipt_data
        )
        
        if not verification.get("valid"):
            return PaymentVerificationResponse(
                success=False,
                message="Receipt verification failed",
                error=verification.get("error", "Invalid receipt")
            )

        # Validar bundle_id contra el de la app configurado
        receipt_bundle_id = verification.get("bundle_id", "")
        expected_bundle_id = settings.APPLE_IAP_BUNDLE_ID
        if receipt_bundle_id and receipt_bundle_id != expected_bundle_id:
            return PaymentVerificationResponse(
                success=False,
                message="Receipt does not belong to this app",
                error=f"bundle_id mismatch: {receipt_bundle_id}"
            )

        # Get product ID from verification
        apple_product_id = verification.get("product_id")
        
        if not apple_product_id:
            return PaymentVerificationResponse(
                success=False,
                message="Product ID not found in receipt",
                error="Missing product_id"
            )
        
        # Get platform product mapping
        platform_product = ProductService.get_platform_product_by_platform_id(
            db=db,
            platform="apple_iap",
            platform_product_id=apple_product_id
        )
        
        if not platform_product:
            raise HTTPException(
                status_code=404,
                detail=f"Product '{apple_product_id}' not found in catalog"
            )
        
        # Get internal product
        product = ProductService.get_product_by_id(db, platform_product.product_id)
        
        if not product:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )
        
        # Check for duplicate purchase
        transaction_id = verification.get("transaction_id")
        existing = TransactionService.check_duplicate_purchase(
            db=db,
            platform="apple_iap",
            platform_transaction_id=transaction_id
        )
        
        if existing:
            return PaymentVerificationResponse(
                success=False,
                message="Purchase already processed",
                transaction_id=existing.id,
                error="Duplicate purchase"
            )
        
        # Get client IP and user agent
        client_ip = http_request.client.host if http_request else None
        user_agent = http_request.headers.get("user-agent") if http_request else None
        
        # Create transaction
        transaction = TransactionService.create_transaction(
            db=db,
            user_id=current_user.id,
            product_id=product.id,
            platform="apple_iap",
            amount=Decimal(str(product.price_usd)),
            currency="USD",
            receipt_data=request.receipt_data,
            ip_address=client_ip,
            user_agent=user_agent,
            device_info={
                "platform": "ios",
                "bundle_id": verification.get("bundle_id"),
                "environment": verification.get("environment")
            }
        )
        
        # Mark as validated
        TransactionService.mark_transaction_validated(
            db=db,
            transaction_id=transaction.id,
            platform_transaction_id=transaction_id,
            validation_response=str(verification.get("raw_response"))
        )
        
        # Activate benefit
        transaction = TransactionService.activate_transaction_benefit(
            db=db,
            transaction_id=transaction.id,
            benefit_metadata={
                "platform": "apple_iap",
                "product_id": apple_product_id,
                "transaction_id": transaction_id,
                "original_transaction_id": verification.get("original_transaction_id")
            }
        )
        
        # Send confirmation email
        try:
            email_service.send_purchase_confirmation(
                user_email=current_user.email,
                user_name=current_user.full_name or current_user.email,
                transaction=transaction,
                product=product
            )
        except Exception as email_error:
            logger.error(f"Failed to send confirmation email: {email_error}")
            # Don't fail the transaction if email fails
        
        return PaymentVerificationResponse(
            success=True,
            transaction_id=transaction.id,
            message="Purchase verified and benefit activated",
            expires_at=transaction.expires_at
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Payment verification failed: {str(e)}"
        )


@router.post("/verify/transbank", response_model=PaymentVerificationResponse)
async def verify_transbank_payment(
    request: TransbankVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    http_request: Request = None
):
    """
    Commit y verifica un pago Transbank Webpay Plus.

    Llama al PUT de commit obligatorio (captura el dinero) y luego
    activa el beneficio correspondiente al producto comprado.

    Request Body:
    - token: token_ws recibido en la URL de retorno de Transbank

    Returns:
    - PaymentVerificationResponse with transaction details
    """
    try:
        # --- Idempotencia por token_ws ---
        # Si este token ya fue procesado (doble click, refresh del callback),
        # devolver la transacción existente sin re-commitear.
        existing = TransactionService.check_duplicate_purchase(
            db=db,
            platform="web",
            purchase_token=request.token
        )
        if existing and existing.status.value == "completed":
            return PaymentVerificationResponse(
                success=True,
                message="Payment already processed",
                transaction_id=existing.id,
                expires_at=existing.expires_at
            )

        # --- Commit obligatorio (PUT) ---
        # Sin este paso Transbank revierte la transacción a los 30 segundos.
        verification = await transbank_validator.commit_transaction(
            token=request.token
        )

        # El 422 de Transbank indica que el token ya fue commiteado previamente.
        # Consultar estado actual para retornar la transacción existente.
        if verification.get("already_committed"):
            existing_by_auth = TransactionService.check_duplicate_purchase(
                db=db,
                platform="web",
                purchase_token=request.token
            )
            if existing_by_auth:
                return PaymentVerificationResponse(
                    success=True,
                    message="Payment already processed",
                    transaction_id=existing_by_auth.id,
                    expires_at=existing_by_auth.expires_at
                )

        if not verification.get("valid"):
            return PaymentVerificationResponse(
                success=False,
                message="Payment commit failed",
                error=verification.get("error", "Invalid payment")
            )

        # --- Extraer product SKU del buy_order ---
        # Formato: {user_id}_{product_sku}_{timestamp}
        buy_order = verification.get("buy_order", "")
        parts = buy_order.split("_")
        if len(parts) < 2:
            return PaymentVerificationResponse(
                success=False,
                message="Invalid buy order format",
                error="Cannot extract product SKU"
            )

        product_sku = parts[1]

        # --- Obtener producto ---
        product = ProductService.get_product_by_sku(db, product_sku)
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product '{product_sku}' not found"
            )

        # --- Idempotencia por authorization_code ---
        authorization_code = verification.get("authorization_code")
        existing_auth = TransactionService.check_duplicate_purchase(
            db=db,
            platform="web",
            platform_transaction_id=authorization_code
        )
        if existing_auth:
            return PaymentVerificationResponse(
                success=True,
                message="Payment already processed",
                transaction_id=existing_auth.id,
                expires_at=existing_auth.expires_at
            )

        # --- Registrar y activar ---
        client_ip = http_request.client.host if http_request else None
        user_agent = http_request.headers.get("user-agent") if http_request else None

        transaction = TransactionService.create_transaction(
            db=db,
            user_id=current_user.id,
            product_id=product.id,
            platform="web",
            amount=Decimal(str(verification.get("amount", 0))),
            currency="CLP",
            purchase_token=request.token,   # token_ws como clave de idempotencia
            ip_address=client_ip,
            user_agent=user_agent,
            device_info={
                "platform": "web",
                "payment_method": "transbank",
                "card_number": verification.get("card_number"),
                "payment_type": verification.get("payment_type_code")
            }
        )

        TransactionService.mark_transaction_validated(
            db=db,
            transaction_id=transaction.id,
            platform_transaction_id=authorization_code,
            validation_response=str(verification.get("raw_response"))
        )

        transaction = TransactionService.activate_transaction_benefit(
            db=db,
            transaction_id=transaction.id,
            benefit_metadata={
                "platform": "web",
                "payment_provider": "transbank",
                "buy_order": buy_order,
                "authorization_code": authorization_code
            }
        )

        try:
            email_service.send_purchase_confirmation(
                user_email=current_user.email,
                user_name=current_user.full_name or current_user.email,
                transaction=transaction,
                product=product
            )
        except Exception as email_error:
            logger.error(f"Failed to send confirmation email: {email_error}")

        return PaymentVerificationResponse(
            success=True,
            transaction_id=transaction.id,
            message="Payment verified and benefit activated",
            expires_at=transaction.expires_at
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Payment verification failed: {str(e)}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# MERCADO PAGO
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/mercadopago/create")
async def create_mercadopago_preference(
    product_sku: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Crea una preferencia de pago en Mercado Pago usando el SDK oficial.

    Guarda el preference_id en Transaction.platform_order_id para poder
    reconciliar el webhook cuando Mercado Pago notifique el resultado.

    Query Parameters:
    - product_sku: SKU del producto a comprar

    Returns:
    - preference_id, init_point (URL de pago), sandbox_init_point
    """
    import mercadopago

    if not settings.MERCADO_PAGO_ACCESS_TOKEN:
        raise HTTPException(status_code=503, detail="Mercado Pago not configured")

    product = ProductService.get_product_by_sku(db, product_sku)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_sku}' not found")

    try:
        sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)

        base_url = settings.FRONTEND_URL
        preference_data = {
            "items": [
                {
                    "id": product.sku,
                    "title": product.name,
                    "quantity": 1,
                    "currency_id": "CLP",
                    "unit_price": float(product.price_clp)
                }
            ],
            "back_urls": {
                "success": f"{base_url}/payment/callback?provider=mercadopago&status=approved",
                "failure": f"{base_url}/payment/callback?provider=mercadopago&status=failure",
                "pending": f"{base_url}/payment/callback?provider=mercadopago&status=pending"
            },
            "auto_return": "approved",
            # external_reference vincula la notificación webhook con user + producto
            "external_reference": f"{current_user.id}_{product.sku}",
            "notification_url": f"{base_url.replace('localhost:8100', 'backend-bapp.onrender.com')}/api/v1/payments/mercadopago/webhook",
        }

        preference_response = sdk.preference().create(preference_data)
        preference = preference_response.get("response", {})

        if "id" not in preference:
            raise HTTPException(status_code=500, detail="Failed to create Mercado Pago preference")

        preference_id = preference["id"]

        # Crear transaction PENDING con preference_id como platform_order_id
        # para que el webhook pueda encontrar y activar el beneficio
        transaction = TransactionService.create_transaction(
            db=db,
            user_id=current_user.id,
            product_id=product.id,
            platform="web",
            amount=Decimal(str(product.price_clp)),
            currency="CLP",
            device_info={
                "payment_method": "mercadopago",
                "preference_id": preference_id
            }
        )

        # Guardar preference_id en platform_order_id para reconciliación en webhook
        TransactionService.mark_transaction_validated(
            db=db,
            transaction_id=transaction.id,
            platform_transaction_id="pending",
            platform_order_id=preference_id,
            validation_response=json.dumps({"preference_id": preference_id, "status": "preference_created"})
        )
        # Revertir el status a PENDING ya que mark_transaction_validated no cambia el status
        # (solo actualiza campos de validación — el status se mueve a COMPLETED en webhook)

        return {
            "success": True,
            "preference_id": preference_id,
            "init_point": preference.get("init_point"),
            "sandbox_init_point": preference.get("sandbox_init_point"),
            "transaction_id": transaction.id,
            "product_sku": product_sku
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mercado Pago error: {str(e)}")


@router.post("/mercadopago/webhook")
async def mercadopago_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Webhook de notificaciones de Mercado Pago (IPN/Webhooks v2).

    Valida la firma x-signature antes de procesar para prevenir
    notificaciones falsas que activen beneficios sin pago real.

    Mercado Pago reintenta hasta 5 veces si no recibe 200. Este endpoint
    es idempotente: si la transaction ya está COMPLETED, retorna 200 sin
    volver a activar el beneficio.

    Docs: https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications/webhooks
    """
    import mercadopago

    # --- Validación de firma (x-signature) ---
    # Mercado Pago envía: x-signature: ts=<timestamp>,v1=<hash>
    # El hash es HMAC-SHA256 de "id:<payment_id>;request-id:<x-request-id>;ts:<ts>"
    # usando MERCADO_PAGO_ACCESS_TOKEN como clave secreta.
    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")

    body_bytes = await request.body()

    if settings.MERCADO_PAGO_ACCESS_TOKEN and x_signature:
        try:
            # Parsear ts y v1 del header
            sig_parts = dict(part.split("=", 1) for part in x_signature.split(",") if "=" in part)
            ts = sig_parts.get("ts", "")
            v1 = sig_parts.get("v1", "")

            body_data = json.loads(body_bytes)
            data_id = body_data.get("data", {}).get("id", "")

            manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
            expected = hmac.new(
                settings.MERCADO_PAGO_ACCESS_TOKEN.encode(),
                manifest.encode(),
                hashlib.sha256
            ).hexdigest()

            if v1 and expected != v1:
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        except (json.JSONDecodeError, KeyError):
            # Si no podemos parsear, continuar (MP no siempre envía signature en desarrollo)
            pass

    # --- Parsear payload ---
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        return {"status": "ignored", "reason": "invalid json"}

    event_type = payload.get("type")
    if event_type != "payment":
        # Solo procesar eventos de tipo payment (ignorar merchant_orders, etc.)
        return {"status": "ignored", "reason": f"event_type={event_type}"}

    payment_id = str(payload.get("data", {}).get("id", ""))
    if not payment_id:
        return {"status": "ignored", "reason": "no payment_id"}

    # --- Consultar estado real del pago en MP API ---
    if not settings.MERCADO_PAGO_ACCESS_TOKEN:
        return {"status": "skipped", "reason": "MP not configured"}

    try:
        sdk = mercadopago.SDK(settings.MERCADO_PAGO_ACCESS_TOKEN)
        payment_response = sdk.payment().get(payment_id)
        payment_data = payment_response.get("response", {})
    except Exception as e:
        # No devolver 500: MP reintentaría indefinidamente
        logger.error(f"[MP webhook] Error fetching payment {payment_id}: {e}")
        return {"status": "error", "reason": str(e)}

    mp_status = payment_data.get("status")           # approved | rejected | pending
    external_ref = payment_data.get("external_reference", "")  # "{user_id}_{product_sku}"

    if mp_status != "approved":
        return {"status": "ignored", "reason": f"payment_status={mp_status}"}

    # --- Reconciliar con Transaction por platform_order_id (preference_id) ---
    preference_id = str(payment_data.get("preference_id", ""))

    transaction = None
    if preference_id:
        transaction = db.query(__import__('app.models.transaction', fromlist=['Transaction']).Transaction).filter(
            __import__('app.models.transaction', fromlist=['Transaction']).Transaction.platform_order_id == preference_id
        ).first()

    if not transaction:
        logger.info(f"[MP webhook] No transaction found for preference_id={preference_id}")
        return {"status": "not_found", "reason": "transaction not found"}

    # --- Idempotencia: ya procesado ---
    from app.models.transaction import TransactionStatus
    if transaction.status == TransactionStatus.COMPLETED:
        return {"status": "already_processed", "transaction_id": transaction.id}

    # --- Activar beneficio ---
    product = ProductService.get_product_by_id(db, transaction.product_id)

    TransactionService.mark_transaction_validated(
        db=db,
        transaction_id=transaction.id,
        platform_transaction_id=payment_id,
        platform_order_id=preference_id,
        validation_response=json.dumps({
            "payment_id": payment_id,
            "mp_status": mp_status,
            "external_reference": external_ref
        })
    )

    activated = TransactionService.activate_transaction_benefit(
        db=db,
        transaction_id=transaction.id,
        benefit_metadata={
            "payment_provider": "mercadopago",
            "payment_id": payment_id,
            "preference_id": preference_id,
            "external_reference": external_ref
        }
    )

    if activated and product:
        try:
            user = db.query(User).filter(User.id == transaction.user_id).first()
            if user:
                email_service.send_purchase_confirmation(
                    user_email=user.email,
                    user_name=user.full_name or user.email,
                    transaction=activated,
                    product=product
                )
        except Exception as email_error:
            logger.error(f"[MP webhook] Email error: {email_error}")

    return {"status": "processed", "transaction_id": transaction.id}
