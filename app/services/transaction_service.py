"""
Transaction Service - Unified transaction management and benefit activation
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.models.transaction import Transaction, TransactionStatus
from app.models.product import Product
from app.models.user import User
from app.models.provider import Provider
from app.models.provider_service_slot import ProviderServiceSlot
from app.schemas.monetization import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse
)
import asyncio
from app.services.email_service import email_service

class TransactionService:
    """Service for managing transactions and benefit activation"""

    @staticmethod
    def create_transaction(
        db: Session,
        user_id: int,
        product_id: int,
        platform: str,
        amount: Decimal,
        currency: str = "CLP",
        purchase_token: Optional[str] = None,
        receipt_data: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_info: Optional[Dict[str, Any]] = None
    ) -> Transaction:
        """
        Create a new transaction
        
        Args:
            db: Database session
            user_id: User ID
            product_id: Product ID
            platform: Payment platform
            amount: Transaction amount
            currency: Currency code (CLP, USD)
            purchase_token: Google Play purchase token
            receipt_data: Apple IAP receipt data
            ip_address: Client IP address
            user_agent: Client user agent
            device_info: Additional device information
            
        Returns:
            Created transaction
        """
        transaction = Transaction(
            user_id=user_id,
            product_id=product_id,
            platform=platform,
            amount=amount,
            currency=currency,
            status=TransactionStatus.PENDING,
            purchase_token=purchase_token,
            receipt_data=receipt_data,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info=device_info
        )
        
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        
        return transaction

    @staticmethod
    def update_transaction(
        db: Session,
        transaction_id: int,
        update_data: TransactionUpdate
    ) -> Optional[Transaction]:
        """
        Update transaction
        
        Args:
            db: Database session
            transaction_id: Transaction ID
            update_data: Update data
            
        Returns:
            Updated transaction or None
        """
        transaction = db.query(Transaction).filter(
            Transaction.id == transaction_id
        ).first()
        
        if not transaction:
            return None
        
        update_dict = update_data.dict(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(transaction, field, value)
        
        db.commit()
        db.refresh(transaction)
        
        return transaction

    @staticmethod
    def mark_transaction_validated(
        db: Session,
        transaction_id: int,
        platform_transaction_id: str,
        platform_order_id: Optional[str] = None,
        validation_response: Optional[str] = None
    ) -> Optional[Transaction]:
        """
        Mark transaction as validated
        
        Args:
            db: Database session
            transaction_id: Transaction ID
            platform_transaction_id: Platform transaction ID
            platform_order_id: Platform order ID
            validation_response: Raw validation response
            
        Returns:
            Updated transaction or None
        """
        transaction = db.query(Transaction).filter(
            Transaction.id == transaction_id
        ).first()
        
        if not transaction:
            return None
        
        transaction.platform_transaction_id = platform_transaction_id
        transaction.platform_order_id = platform_order_id
        transaction.validation_response = validation_response
        transaction.validated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(transaction)
        
        return transaction

    @staticmethod
    def activate_transaction_benefit(
        db: Session,
        transaction_id: int,
        benefit_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Transaction]:
        """
        Activate benefit for transaction (premium or service slot)
        
        Args:
            db: Database session
            transaction_id: Transaction ID
            benefit_metadata: Additional metadata about activated benefit
            
        Returns:
            Updated transaction with activated benefit
        """
        transaction = db.query(Transaction).filter(
            Transaction.id == transaction_id
        ).first()
        
        if not transaction or transaction.status != TransactionStatus.PENDING:
            return None

        # Get product to determine duration and validate amount
        product = db.query(Product).filter(
            Product.id == transaction.product_id
        ).first()

        if not product:
            return None

        # Validar que el monto pagado no sea inferior al precio del catálogo.
        # Tolerancia de 1 CLP/centavo para evitar falsos rechazos por redondeo.
        expected_amount = product.price_clp if transaction.currency == "CLP" else product.price_usd
        if transaction.amount < (expected_amount - 1):
            # Marcar como fallida y no activar el beneficio
            transaction.status = TransactionStatus.FAILED
            transaction.validation_response = (
                f"Amount mismatch: paid={transaction.amount}, expected={expected_amount}"
            )
            db.commit()
            return None

        # Calculate expiration
        activated_at = datetime.utcnow()
        expires_at = activated_at + timedelta(days=product.duration_days)
        
        # Update transaction
        transaction.status = TransactionStatus.COMPLETED
        transaction.activated_at = activated_at
        transaction.expires_at = expires_at
        transaction.benefit_metadata = benefit_metadata
        
        # Activate benefit based on product SKU
        user = db.query(User).filter(User.id == transaction.user_id).first()
        
        if not user:
            return None
        
        if product.sku == "premium_access_7days":
            # Activate premium access
            user.has_premium = True
            user.premium_activated_at = activated_at
            user.premium_expires_at = expires_at
            
        elif product.sku == "service_publication_30days":
            # Activate provider service slot
            provider = db.query(Provider).filter(
                Provider.user_id == user.id
            ).first()
            
            if provider:
                # Find next available paid slot (slot_number > 2)
                occupied_slots = db.query(ProviderServiceSlot.slot_number).filter(
                    and_(
                        ProviderServiceSlot.provider_id == provider.id,
                        ProviderServiceSlot.is_active == True
                    )
                ).all()
                
                occupied_numbers = [s[0] for s in occupied_slots]
                
                # Find next slot number
                next_slot_number = 3  # Start from slot 3 (first paid slot)
                while next_slot_number in occupied_numbers:
                    next_slot_number += 1
                
                # Get or create slot
                slot = db.query(ProviderServiceSlot).filter(
                    and_(
                        ProviderServiceSlot.provider_id == provider.id,
                        ProviderServiceSlot.slot_number == next_slot_number
                    )
                ).first()
                
                if not slot:
                    slot = ProviderServiceSlot(
                        provider_id=provider.id,
                        slot_number=next_slot_number,
                        is_free=False
                    )
                    db.add(slot)
                
                # Activate slot
                slot.transaction_id = transaction.id
                slot.activated_at = activated_at
                slot.expires_at = expires_at
                slot.is_active = True
        
        db.commit()
        db.refresh(transaction)

        # Enviar correo de confirmación de compra
        try:
            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
            
            email_data = {
                "item_name": product.name,
                "amount": f"{transaction.amount:,.0f} {transaction.currency}",
                "date": transaction.activated_at.strftime("%d/%m/%Y %H:%M"),
                "reference_id": str(transaction.id)
            }
            
            if loop and loop.is_running():
                loop.create_task(email_service.send_purchase_confirmation(user.email, email_data))
            else:
                asyncio.run(email_service.send_purchase_confirmation(user.email, email_data))
        except Exception as e:
            print(f"Error sending purchase confirmation email: {e}")
        
        return transaction

    @staticmethod
    def get_user_transactions(
        db: Session,
        user_id: int,
        status: Optional[TransactionStatus] = None,
        limit: int = 50
    ) -> List[Transaction]:
        """
        Get user transactions
        
        Args:
            db: Database session
            user_id: User ID
            status: Filter by status
            limit: Maximum results
            
        Returns:
            List of transactions
        """
        query = db.query(Transaction).filter(
            Transaction.user_id == user_id
        )
        
        if status:
            query = query.filter(Transaction.status == status)
        
        return query.order_by(desc(Transaction.created_at)).limit(limit).all()

    @staticmethod
    def get_transaction_by_id(
        db: Session,
        transaction_id: int
    ) -> Optional[Transaction]:
        """
        Get transaction by ID
        
        Args:
            db: Database session
            transaction_id: Transaction ID
            
        Returns:
            Transaction or None
        """
        return db.query(Transaction).filter(
            Transaction.id == transaction_id
        ).first()

    @staticmethod
    def check_duplicate_purchase(
        db: Session,
        platform: str,
        purchase_token: Optional[str] = None,
        platform_transaction_id: Optional[str] = None
    ) -> Optional[Transaction]:
        """
        Check for duplicate purchase
        
        Args:
            db: Database session
            platform: Payment platform
            purchase_token: Google Play purchase token
            platform_transaction_id: Platform transaction ID
            
        Returns:
            Existing transaction or None
        """
        if platform == "google_play" and purchase_token:
            return db.query(Transaction).filter(
                and_(
                    Transaction.platform == platform,
                    Transaction.purchase_token == purchase_token,
                    Transaction.status.in_([
                        TransactionStatus.COMPLETED,
                        TransactionStatus.PENDING
                    ])
                )
            ).first()
        
        if platform_transaction_id:
            return db.query(Transaction).filter(
                and_(
                    Transaction.platform == platform,
                    Transaction.platform_transaction_id == platform_transaction_id,
                    Transaction.status.in_([
                        TransactionStatus.COMPLETED,
                        TransactionStatus.PENDING
                    ])
                )
            ).first()
        
        return None

    @staticmethod
    def mark_transaction_failed(
        db: Session,
        transaction_id: int,
        error_message: str
    ) -> Optional[Transaction]:
        """
        Mark transaction as failed
        
        Args:
            db: Database session
            transaction_id: Transaction ID
            error_message: Error description
            
        Returns:
            Updated transaction or None
        """
        transaction = db.query(Transaction).filter(
            Transaction.id == transaction_id
        ).first()
        
        if not transaction:
            return None
        
        transaction.status = TransactionStatus.FAILED
        transaction.validation_response = error_message
        
        db.commit()
        db.refresh(transaction)
        
        return transaction
