"""
Payment Verification Endpoints
Handles payment verification for Google Play, Apple IAP, and Transbank
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional
from decimal import Decimal

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
            print(f"Failed to send confirmation email: {email_error}")
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
            print(f"Failed to send confirmation email: {email_error}")
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
    Verify Transbank payment and activate benefit
    
    Request Body:
    - token: Transaction token from Transbank
    
    Returns:
    - PaymentVerificationResponse with transaction details
    """
    try:
        # Verify with Transbank
        verification = await transbank_validator.verify_transaction(
            token=request.token
        )
        
        if not verification.get("valid"):
            return PaymentVerificationResponse(
                success=False,
                message="Payment verification failed",
                error=verification.get("error", "Invalid payment")
            )
        
        # Extract buy_order to get product SKU
        buy_order = verification.get("buy_order", "")
        
        # Format: {user_id}_{product_sku}_{timestamp}
        parts = buy_order.split("_")
        if len(parts) < 2:
            return PaymentVerificationResponse(
                success=False,
                message="Invalid buy order format",
                error="Cannot extract product SKU"
            )
        
        product_sku = parts[1]
        
        # Get product
        product = ProductService.get_product_by_sku(db, product_sku)
        
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product '{product_sku}' not found"
            )
        
        # Check for duplicate purchase
        authorization_code = verification.get("authorization_code")
        existing = TransactionService.check_duplicate_purchase(
            db=db,
            platform="web",
            platform_transaction_id=authorization_code
        )
        
        if existing:
            return PaymentVerificationResponse(
                success=False,
                message="Payment already processed",
                transaction_id=existing.id,
                error="Duplicate payment"
            )
        
        # Get client IP and user agent
        client_ip = http_request.client.host if http_request else None
        user_agent = http_request.headers.get("user-agent") if http_request else None
        
        # Create transaction
        transaction = TransactionService.create_transaction(
            db=db,
            user_id=current_user.id,
            product_id=product.id,
            platform="web",
            amount=Decimal(str(verification.get("amount", 0))),
            currency="CLP",
            ip_address=client_ip,
            user_agent=user_agent,
            device_info={
                "platform": "web",
                "payment_method": "transbank",
                "card_number": verification.get("card_number"),
                "payment_type": verification.get("payment_type_code")
            }
        )
        
        # Mark as validated
        TransactionService.mark_transaction_validated(
            db=db,
            transaction_id=transaction.id,
            platform_transaction_id=authorization_code,
            validation_response=str(verification.get("raw_response"))
        )
        
        # Activate benefit
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
        
        # Send confirmation email
        try:
            email_service.send_purchase_confirmation(
                user_email=current_user.email,
                user_name=current_user.full_name or current_user.email,
                transaction=transaction,
                product=product
            )
        except Exception as email_error:
            print(f"Failed to send confirmation email: {email_error}")
            # Don't fail the transaction if email fails
        
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


@router.post("/transbank/create")
async def create_transbank_transaction(
    product_sku: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    http_request: Request = None
):
    """
    Create a Transbank Webpay Plus transaction
    
    Query Parameters:
    - product_sku: Product SKU to purchase
    
    Returns:
    - token: Transaction token
    - url: Webpay payment URL
    """
    try:
        # Get product
        product = ProductService.get_product_by_sku(db, product_sku)
        
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product '{product_sku}' not found"
            )
        
        # Generate unique buy_order
        import time
        buy_order = f"{current_user.id}_{product_sku}_{int(time.time())}"
        session_id = f"session_{current_user.id}_{int(time.time())}"
        
        # Build return URL
        base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:8100')
        return_url = f"{base_url}/payment/callback"
        
        # Create transaction
        result = await transbank_validator.create_transaction(
            buy_order=buy_order,
            session_id=session_id,
            amount=float(product.price_clp),
            return_url=return_url
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Failed to create transaction")
            )
        
        return {
            "success": True,
            "token": result.get("token"),
            "url": result.get("url"),
            "buy_order": buy_order,
            "amount": float(product.price_clp),
            "product_sku": product_sku
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transaction creation failed: {str(e)}"
        )
