"""
Transbank Webpay Plus Validator
Validates web payments through Transbank (Chile)
"""
import aiohttp
import json
from typing import Optional, Dict, Any
from datetime import datetime
import hmac
import hashlib


class TransbankValidator:
    """
    Validator for Transbank Webpay Plus payments
    
    Supports Webpay Plus integration for Chilean payments
    """
    
    # Transbank environments
    PRODUCTION_URL = "https://webpay3g.transbank.cl"
    INTEGRATION_URL = "https://webpay3gint.transbank.cl"
    
    # Response codes
    RESPONSE_CODES = {
        0: "Transacción aprobada",
        -1: "Rechazo de transacción",
        -2: "Transacción debe reintentarse",
        -3: "Error en transacción",
        -4: "Rechazo de transacción",
        -5: "Rechazo por error de tasa",
        -6: "Excede cupo máximo mensual",
        -7: "Excede límite diario por transacción",
        -8: "Rubro no autorizado"
    }
    
    def __init__(
        self,
        commerce_code: str,
        api_key: str,
        use_integration: bool = False
    ):
        """
        Initialize Transbank validator
        
        Args:
            commerce_code: Código de comercio Transbank
            api_key: API Key from Transbank
            use_integration: Use integration environment for testing
        """
        self.commerce_code = commerce_code
        self.api_key = api_key
        self.base_url = self.INTEGRATION_URL if use_integration else self.PRODUCTION_URL
        self.environment = "integration" if use_integration else "production"
    
    async def commit_transaction(
        self,
        token: str
    ) -> Dict[str, Any]:
        """
        Commit (capture) a Webpay Plus transaction — OBLIGATORIO después del redirect.

        Webpay Plus exige un PUT al endpoint de transacciones dentro de los 30 segundos
        posteriores a que el usuario es redirigido de vuelta al sitio. Sin este paso,
        Transbank revierte la transacción automáticamente y el dinero NO se captura.

        Args:
            token: token_ws recibido en la URL de retorno

        Returns:
            Dict con el resultado del commit (misma estructura que _parse_response)
        """
        try:
            url = f"{self.base_url}/rswebpaytransaction/api/webpay/v1.2/transactions/{token}"

            async with aiohttp.ClientSession() as session:
                headers = {
                    "Tbk-Api-Key-Id": self.commerce_code,
                    "Tbk-Api-Key-Secret": self.api_key,
                    "Content-Type": "application/json"
                }

                # PUT sin body — Transbank captura la transacción y devuelve el resultado
                async with session.put(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_response(data)

                    elif response.status == 422:
                        # Transacción ya fue commiteada anteriormente (idempotencia)
                        return {
                            "valid": False,
                            "already_committed": True,
                            "error": "Transaction already committed"
                        }

                    elif response.status == 404:
                        return {
                            "valid": False,
                            "error": "Transaction not found or expired"
                        }

                    elif response.status == 401:
                        return {
                            "valid": False,
                            "error": "Invalid credentials"
                        }

                    else:
                        error_text = await response.text()
                        return {
                            "valid": False,
                            "error": f"Commit error {response.status}: {error_text}"
                        }

        except Exception as e:
            return {
                "valid": False,
                "error": f"Commit failed: {str(e)}"
            }

    async def verify_transaction(
        self,
        token: str
    ) -> Dict[str, Any]:
        """
        Consulta el estado de una transacción ya commiteada (GET).

        IMPORTANTE: este método es para consultar el estado DESPUÉS de haber
        llamado commit_transaction(). Para el flujo normal de callback usar
        commit_transaction() directamente.

        Args:
            token: Transaction token from Transbank

        Returns:
            Dict with verification result:
            {
                "valid": bool,
                "response_code": int,
                "authorization_code": str,
                "amount": float,
                "transaction_date": datetime,
                "buy_order": str,
                "error": str (if valid=False)
            }
        """
        try:
            url = f"{self.base_url}/rswebpaytransaction/api/webpay/v1.2/transactions/{token}"

            async with aiohttp.ClientSession() as session:
                headers = {
                    "Tbk-Api-Key-Id": self.commerce_code,
                    "Tbk-Api-Key-Secret": self.api_key,
                    "Content-Type": "application/json"
                }

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return self._parse_response(data)

                    elif response.status == 404:
                        return {
                            "valid": False,
                            "error": "Transaction not found"
                        }

                    elif response.status == 401:
                        return {
                            "valid": False,
                            "error": "Invalid credentials"
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
    
    def _parse_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Transbank response
        
        Args:
            data: Response from Transbank
            
        Returns:
            Parsed result dict
        """
        response_code = data.get("response_code", -1)
        status_message = self.RESPONSE_CODES.get(
            response_code,
            f"Código desconocido: {response_code}"
        )
        
        # Transaction is valid if response_code is 0
        is_valid = response_code == 0
        
        result = {
            "valid": is_valid,
            "response_code": response_code,
            "status_message": status_message,
            "environment": self.environment,
            "raw_response": data
        }
        
        if is_valid:
            # Parse transaction date
            transaction_date_str = data.get("transaction_date")
            transaction_date = None
            if transaction_date_str:
                try:
                    # Format: 2024-01-20T10:30:00
                    transaction_date = datetime.fromisoformat(transaction_date_str.replace('Z', '+00:00'))
                except:
                    pass
            
            result.update({
                "vci": data.get("vci"),  # Validation Code Indicator
                "amount": float(data.get("amount", 0)),
                "status": data.get("status"),
                "buy_order": data.get("buy_order"),
                "session_id": data.get("session_id"),
                "card_number": data.get("card_detail", {}).get("card_number"),
                "accounting_date": data.get("accounting_date"),
                "transaction_date": transaction_date,
                "authorization_code": data.get("authorization_code"),
                "payment_type_code": data.get("payment_type_code"),
                "installments_number": data.get("installments_number", 0)
            })
        else:
            result["error"] = status_message
        
        return result
    
    async def create_transaction(
        self,
        buy_order: str,
        session_id: str,
        amount: float,
        return_url: str
    ) -> Dict[str, Any]:
        """
        Create a new Webpay Plus transaction
        
        Args:
            buy_order: Unique order identifier
            session_id: Session identifier
            amount: Transaction amount in CLP
            return_url: URL to return after payment
            
        Returns:
            Dict with transaction token and URL
        """
        try:
            url = f"{self.base_url}/rswebpaytransaction/api/webpay/v1.2/transactions"
            
            payload = {
                "buy_order": buy_order,
                "session_id": session_id,
                "amount": int(amount),  # Amount in CLP (integer)
                "return_url": return_url
            }
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Tbk-Api-Key-Id": self.commerce_code,
                    "Tbk-Api-Key-Secret": self.api_key,
                    "Content-Type": "application/json"
                }
                
                async with session.post(
                    url,
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        return {
                            "success": True,
                            "token": data.get("token"),
                            "url": data.get("url"),
                            "buy_order": buy_order,
                            "session_id": session_id,
                            "amount": amount
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"API error {response.status}: {error_text}"
                        }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Transaction creation failed: {str(e)}"
            }
    
    async def refund_transaction(
        self,
        token: str,
        amount: float
    ) -> Dict[str, Any]:
        """
        Refund a transaction
        
        Args:
            token: Transaction token
            amount: Amount to refund in CLP
            
        Returns:
            Dict with refund result
        """
        try:
            url = f"{self.base_url}/rswebpaytransaction/api/webpay/v1.2/transactions/{token}/refunds"
            
            payload = {
                "amount": int(amount)
            }
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Tbk-Api-Key-Id": self.commerce_code,
                    "Tbk-Api-Key-Secret": self.api_key,
                    "Content-Type": "application/json"
                }
                
                async with session.post(
                    url,
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        return {
                            "success": True,
                            "authorization_code": data.get("authorization_code"),
                            "authorization_date": data.get("authorization_date"),
                            "nullified_amount": data.get("nullified_amount"),
                            "balance": data.get("balance"),
                            "response_code": data.get("response_code")
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Refund failed: {error_text}"
                        }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Refund failed: {str(e)}"
            }
    
    async def check_transaction_status(
        self,
        token: str
    ) -> str:
        """
        Check transaction status
        
        Args:
            token: Transaction token
            
        Returns:
            Status string: "AUTHORIZED", "FAILED", "PENDING", "UNKNOWN"
        """
        result = await self.verify_transaction(token)
        
        if result.get("valid"):
            return "AUTHORIZED"
        
        response_code = result.get("response_code", -1)
        
        if response_code == -2:
            return "PENDING"
        elif response_code < 0:
            return "FAILED"
        else:
            return "UNKNOWN"
