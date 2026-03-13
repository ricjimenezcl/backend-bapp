"""
Apple In-App Purchase Validator
Verifies receipts with Apple App Store
"""
import aiohttp
import json
from typing import Optional, Dict, Any
from datetime import datetime
import base64


class AppleIAPValidator:
    """
    Validator for Apple In-App Purchases
    
    Uses Apple's receipt validation API
    Supports both sandbox and production environments
    """
    
    # Apple verification URLs
    PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
    SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"
    
    # Status codes
    STATUS_CODES = {
        0: "Valid receipt",
        21000: "The App Store could not read the JSON object",
        21002: "The data in the receipt-data property was malformed",
        21003: "The receipt could not be authenticated",
        21004: "The shared secret does not match",
        21005: "The receipt server is not currently available",
        21006: "This receipt is valid but the subscription has expired",
        21007: "This receipt is from the test environment",
        21008: "This receipt is from the production environment",
        21010: "This receipt could not be authorized"
    }
    
    def __init__(
        self,
        shared_secret: Optional[str] = None,
        use_sandbox: bool = False
    ):
        """
        Initialize Apple IAP validator
        
        Args:
            shared_secret: App-specific shared secret from App Store Connect
            use_sandbox: Use sandbox environment for testing
        """
        self.shared_secret = shared_secret
        self.use_sandbox = use_sandbox
        self.production_url = self.PRODUCTION_URL
        self.sandbox_url = self.SANDBOX_URL
    
    async def verify_receipt(
        self,
        receipt_data: str,
        exclude_old_transactions: bool = True
    ) -> Dict[str, Any]:
        """
        Verify a receipt with Apple
        
        Args:
            receipt_data: Base64 encoded receipt data
            exclude_old_transactions: Exclude old transactions from response
            
        Returns:
            Dict with verification result:
            {
                "valid": bool,
                "status": int,
                "status_message": str,
                "bundle_id": str,
                "product_id": str,
                "transaction_id": str,
                "original_transaction_id": str,
                "purchase_date": datetime,
                "quantity": int,
                "error": str (if valid=False)
            }
        """
        # Build request payload
        payload = {
            "receipt-data": receipt_data,
            "exclude-old-transactions": exclude_old_transactions
        }
        
        if self.shared_secret:
            payload["password"] = self.shared_secret
        
        # Try production first
        result = await self._verify_with_url(self.production_url, payload)
        
        # If status is 21007 (sandbox receipt sent to production), retry with sandbox
        if result.get("status") == 21007:
            result = await self._verify_with_url(self.sandbox_url, payload)
            result["environment"] = "sandbox"
        else:
            result["environment"] = "production"
        
        return result
    
    async def _verify_with_url(
        self,
        url: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Verify receipt with specific URL
        
        Args:
            url: Apple verification URL
            payload: Request payload
            
        Returns:
            Verification result dict
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json"
                }
                
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_response(data)
                    else:
                        error_text = await response.text()
                        return {
                            "valid": False,
                            "error": f"HTTP {response.status}: {error_text}"
                        }
        
        except aiohttp.ClientError as e:
            return {
                "valid": False,
                "error": f"Network error: {str(e)}"
            }
        except Exception as e:
            return {
                "valid": False,
                "error": f"Verification failed: {str(e)}"
            }
    
    def _parse_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Apple's verification response
        
        Args:
            data: Response from Apple
            
        Returns:
            Parsed result dict
        """
        status = data.get("status", -1)
        status_message = self.STATUS_CODES.get(status, "Unknown status")
        
        result = {
            "status": status,
            "status_message": status_message,
            "valid": status == 0,
            "raw_response": data
        }
        
        # If valid, extract receipt information
        if status == 0:
            receipt = data.get("receipt", {})
            in_app = receipt.get("in_app", [])
            
            # Get latest transaction
            if in_app:
                latest = in_app[0]
                
                # Parse purchase date
                purchase_date_ms = int(latest.get("purchase_date_ms", 0))
                purchase_date = datetime.fromtimestamp(purchase_date_ms / 1000) if purchase_date_ms else None
                
                # Parse expiration date (for subscriptions)
                expires_date_ms = latest.get("expires_date_ms")
                expires_date = None
                if expires_date_ms:
                    expires_date = datetime.fromtimestamp(int(expires_date_ms) / 1000)
                
                result.update({
                    "bundle_id": receipt.get("bundle_id"),
                    "application_version": receipt.get("application_version"),
                    "product_id": latest.get("product_id"),
                    "transaction_id": latest.get("transaction_id"),
                    "original_transaction_id": latest.get("original_transaction_id"),
                    "purchase_date": purchase_date,
                    "purchase_date_ms": purchase_date_ms,
                    "expires_date": expires_date,
                    "expires_date_ms": expires_date_ms,
                    "quantity": int(latest.get("quantity", 1)),
                    "is_trial_period": latest.get("is_trial_period") == "true",
                    "is_in_intro_offer_period": latest.get("is_in_intro_offer_period") == "true",
                    "cancellation_date": latest.get("cancellation_date"),
                    "web_order_line_item_id": latest.get("web_order_line_item_id")
                })
            
            # Latest receipt info (for auto-renewable subscriptions)
            latest_receipt_info = data.get("latest_receipt_info")
            if latest_receipt_info:
                result["latest_receipt_info"] = latest_receipt_info
            
            # Pending renewal info (for subscriptions)
            pending_renewal_info = data.get("pending_renewal_info")
            if pending_renewal_info:
                result["pending_renewal_info"] = pending_renewal_info
                
                # Check auto-renew status
                if pending_renewal_info:
                    auto_renew_status = pending_renewal_info[0].get("auto_renew_status")
                    result["auto_renew_enabled"] = auto_renew_status == "1"
        
        else:
            result["error"] = status_message
        
        return result
    
    async def verify_subscription(
        self,
        receipt_data: str
    ) -> Dict[str, Any]:
        """
        Verify a subscription receipt
        
        Args:
            receipt_data: Base64 encoded receipt
            
        Returns:
            Verification result with subscription info
        """
        result = await self.verify_receipt(receipt_data, exclude_old_transactions=False)
        
        if result.get("valid"):
            # Check if subscription is still active
            expires_date = result.get("expires_date")
            if expires_date:
                is_active = expires_date > datetime.utcnow()
                result["is_active"] = is_active
                
                if not is_active:
                    result["valid"] = False
                    result["error"] = "Subscription has expired"
            else:
                # Not a subscription
                result["is_subscription"] = False
        
        return result
    
    def decode_receipt(self, receipt_data: str) -> Optional[Dict[str, Any]]:
        """
        Decode receipt data (for debugging)
        
        Args:
            receipt_data: Base64 encoded receipt
            
        Returns:
            Decoded receipt data or None
        """
        try:
            decoded = base64.b64decode(receipt_data)
            # Note: Receipt is in PKCS7 format, not JSON
            # This is mainly for validation
            return {
                "length": len(decoded),
                "valid_base64": True
            }
        except Exception as e:
            return {
                "valid_base64": False,
                "error": str(e)
            }
    
    async def refresh_receipt(
        self,
        original_transaction_id: str,
        receipt_data: str
    ) -> Dict[str, Any]:
        """
        Refresh receipt to get latest subscription status
        
        Args:
            original_transaction_id: Original transaction ID
            receipt_data: Latest receipt data
            
        Returns:
            Updated verification result
        """
        result = await self.verify_receipt(receipt_data, exclude_old_transactions=False)
        
        if result.get("valid"):
            # Find transaction matching original_transaction_id
            latest_receipt_info = result.get("latest_receipt_info", [])
            
            for transaction in latest_receipt_info:
                if transaction.get("original_transaction_id") == original_transaction_id:
                    expires_date_ms = transaction.get("expires_date_ms")
                    if expires_date_ms:
                        expires_date = datetime.fromtimestamp(int(expires_date_ms) / 1000)
                        result["current_expiry"] = expires_date
                        result["is_active"] = expires_date > datetime.utcnow()
                    break
        
        return result
