"""
Google Play Billing Validator
Verifies purchase tokens with Google Play Developer API
"""
import aiohttp
import json
from typing import Optional, Dict, Any
from datetime import datetime
from google.oauth2 import service_account
from google.auth.transport.requests import Request


class GooglePlayValidator:
    """
    Validator for Google Play in-app purchases
    
    Requires:
    - Service account credentials JSON file
    - Google Play Developer API enabled
    - Package name configured
    """
    
    def __init__(
        self,
        package_name: str,
        service_account_file: Optional[str] = None,
        credentials_dict: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize Google Play validator
        
        Args:
            package_name: App package name (e.g., io.ionic.bappsearch)
            service_account_file: Path to service account JSON file
            credentials_dict: Service account credentials as dict
        """
        self.package_name = package_name
        self.base_url = "https://androidpublisher.googleapis.com/androidpublisher/v3"
        
        # Initialize credentials
        if service_account_file:
            self.credentials = service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=['https://www.googleapis.com/auth/androidpublisher']
            )
        elif credentials_dict:
            self.credentials = service_account.Credentials.from_service_account_info(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/androidpublisher']
            )
        else:
            self.credentials = None
    
    async def verify_purchase(
        self,
        product_id: str,
        purchase_token: str
    ) -> Dict[str, Any]:
        """
        Verify a product purchase with Google Play
        
        Args:
            product_id: Product ID (SKU) from Google Play Console
            purchase_token: Purchase token from client
            
        Returns:
            Dict with verification result:
            {
                "valid": bool,
                "purchase_state": int,  # 0=purchased, 1=canceled, 2=pending
                "consumption_state": int,  # 0=not consumed, 1=consumed
                "order_id": str,
                "purchase_time_millis": int,
                "acknowledgement_state": int,  # 0=not acknowledged, 1=acknowledged
                "error": str (if valid=False)
            }
        """
        if not self.credentials:
            return {
                "valid": False,
                "error": "Google Play credentials not configured"
            }
        
        try:
            # Refresh access token
            self.credentials.refresh(Request())
            access_token = self.credentials.token
            
            # Build API URL
            url = (
                f"{self.base_url}/applications/{self.package_name}/"
                f"purchases/products/{product_id}/tokens/{purchase_token}"
            )
            
            # Make request
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Parse response
                        purchase_state = data.get("purchaseState", 1)
                        
                        return {
                            "valid": purchase_state == 0,  # 0 = purchased
                            "purchase_state": purchase_state,
                            "consumption_state": data.get("consumptionState", 0),
                            "order_id": data.get("orderId"),
                            "purchase_time_millis": data.get("purchaseTimeMillis"),
                            "purchase_time": datetime.fromtimestamp(
                                int(data.get("purchaseTimeMillis", 0)) / 1000
                            ),
                            "acknowledgement_state": data.get("acknowledgementState", 0),
                            "developer_payload": data.get("developerPayload"),
                            "kind": data.get("kind"),
                            "region_code": data.get("regionCode"),
                            "raw_response": data
                        }
                    
                    elif response.status == 404:
                        return {
                            "valid": False,
                            "error": "Purchase token not found or already consumed"
                        }
                    
                    elif response.status == 401:
                        return {
                            "valid": False,
                            "error": "Invalid credentials or API not enabled"
                        }
                    
                    else:
                        error_text = await response.text()
                        return {
                            "valid": False,
                            "error": f"API error {response.status}: {error_text}"
                        }
        
        except Exception as e:
            return {
                "valid": False,
                "error": f"Verification failed: {str(e)}"
            }
    
    async def verify_subscription(
        self,
        subscription_id: str,
        purchase_token: str
    ) -> Dict[str, Any]:
        """
        Verify a subscription purchase with Google Play
        
        Args:
            subscription_id: Subscription ID from Google Play Console
            purchase_token: Purchase token from client
            
        Returns:
            Dict with verification result (similar to verify_purchase)
        """
        if not self.credentials:
            return {
                "valid": False,
                "error": "Google Play credentials not configured"
            }
        
        try:
            # Refresh access token
            self.credentials.refresh(Request())
            access_token = self.credentials.token
            
            # Build API URL
            url = (
                f"{self.base_url}/applications/{self.package_name}/"
                f"purchases/subscriptions/{subscription_id}/tokens/{purchase_token}"
            )
            
            # Make request
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Parse response
                        expiry_time = int(data.get("expiryTimeMillis", 0)) / 1000
                        is_active = datetime.fromtimestamp(expiry_time) > datetime.utcnow()
                        
                        return {
                            "valid": is_active,
                            "payment_state": data.get("paymentState", 0),  # 0=pending, 1=received
                            "auto_renewing": data.get("autoRenewing", False),
                            "price_currency_code": data.get("priceCurrencyCode"),
                            "price_amount_micros": data.get("priceAmountMicros"),
                            "country_code": data.get("countryCode"),
                            "start_time_millis": data.get("startTimeMillis"),
                            "expiry_time_millis": data.get("expiryTimeMillis"),
                            "expiry_time": datetime.fromtimestamp(expiry_time),
                            "order_id": data.get("orderId"),
                            "acknowledgement_state": data.get("acknowledgementState", 0),
                            "raw_response": data
                        }
                    
                    else:
                        error_text = await response.text()
                        return {
                            "valid": False,
                            "error": f"API error {response.status}: {error_text}"
                        }
        
        except Exception as e:
            return {
                "valid": False,
                "error": f"Verification failed: {str(e)}"
            }
    
    async def acknowledge_purchase(
        self,
        product_id: str,
        purchase_token: str
    ) -> Dict[str, Any]:
        """
        Acknowledge a purchase (required within 3 days)
        
        Args:
            product_id: Product ID (SKU)
            purchase_token: Purchase token
            
        Returns:
            Dict with result
        """
        if not self.credentials:
            return {
                "success": False,
                "error": "Google Play credentials not configured"
            }
        
        try:
            # Refresh access token
            self.credentials.refresh(Request())
            access_token = self.credentials.token
            
            # Build API URL
            url = (
                f"{self.base_url}/applications/{self.package_name}/"
                f"purchases/products/{product_id}/tokens/{purchase_token}:acknowledge"
            )
            
            # Make request
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                
                async with session.post(url, headers=headers) as response:
                    if response.status == 204:
                        return {
                            "success": True,
                            "acknowledged_at": datetime.utcnow()
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Acknowledgement failed: {error_text}"
                        }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Acknowledgement failed: {str(e)}"
            }
