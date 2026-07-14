"""
Transactions Endpoints
User transaction history and details
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.models.transaction import TransactionStatus
from app.services.transaction_service import TransactionService
from app.schemas.monetization import TransactionResponse, TransactionDetailResponse

router = APIRouter()


@router.get("/me", response_model=List[TransactionDetailResponse])
def get_my_transactions(
    status: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current user's transaction history
    
    Query Parameters:
    - status: Filter by status (pending, completed, failed, refunded, expired)
    - limit: Maximum number of transactions to return (default: 50, max: 100)
    
    Returns:
    - List of transactions with product details
    """
    try:
        # Validate limit
        if limit > 100:
            limit = 100
        
        # Parse status if provided
        transaction_status = None
        if status:
            try:
                transaction_status = TransactionStatus[status.upper()]
            except KeyError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status. Must be one of: pending, completed, failed, refunded, expired"
                )
        
        # Get transactions
        transactions = TransactionService.get_user_transactions(
            db=db,
            user_id=current_user.id,
            status=transaction_status,
            limit=limit
        )
        
        # Build detailed response
        result = []
        for transaction in transactions:
            trans_dict = {
                "id": transaction.id,
                "user_id": transaction.user_id,
                "product_id": transaction.product_id,
                "platform": transaction.platform,
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "status": transaction.status.value,
                "transaction_id": transaction.transaction_id,
                "platform_transaction_id": transaction.platform_transaction_id,
                "platform_order_id": transaction.platform_order_id,
                "activated_at": transaction.activated_at,
                "expires_at": transaction.expires_at,
                "created_at": transaction.created_at,
                "updated_at": transaction.updated_at,
                "product": None
            }
            
            # Add product details if available
            if transaction.product:
                trans_dict["product"] = {
                    "id": transaction.product.id,
                    "sku": transaction.product.sku,
                    "name": transaction.product.name,
                    "description": transaction.product.description,
                    "target_role": transaction.product.target_role,
                    "duration_days": transaction.product.duration_days,
                    "price_usd": float(transaction.product.price_usd),
                    "price_clp": float(transaction.product.price_clp),
                    "free_limit": transaction.product.free_limit,
                    "is_active": transaction.product.is_active,
                    "metadata": transaction.product.product_metadata,
                    "created_at": transaction.product.created_at,
                    "updated_at": transaction.product.updated_at
                }
            
            result.append(trans_dict)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving transactions: {str(e)}"
        )


@router.get("/{transaction_id}", response_model=TransactionDetailResponse)
def get_transaction_detail(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get transaction details by ID
    
    Path Parameters:
    - transaction_id: Transaction ID
    
    Returns:
    - Transaction details with product information
    """
    transaction = TransactionService.get_transaction_by_id(db, transaction_id)
    
    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )
    
    # Verify ownership
    if transaction.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view this transaction"
        )
    
    # Build response
    result = {
        "id": transaction.id,
        "user_id": transaction.user_id,
        "product_id": transaction.product_id,
        "platform": transaction.platform,
        "amount": float(transaction.amount),
        "currency": transaction.currency,
        "status": transaction.status.value,
        "transaction_id": transaction.transaction_id,
        "platform_transaction_id": transaction.platform_transaction_id,
        "activated_at": transaction.activated_at,
        "expires_at": transaction.expires_at,
        "created_at": transaction.created_at,
        "updated_at": transaction.updated_at,
        "product": None
    }
    
    # Add product details
    if transaction.product:
        result["product"] = {
            "id": transaction.product.id,
            "sku": transaction.product.sku,
            "name": transaction.product.name,
            "description": transaction.product.description,
            "target_role": transaction.product.target_role,
            "duration_days": transaction.product.duration_days,
            "price_usd": float(transaction.product.price_usd),
            "price_clp": float(transaction.product.price_clp),
            "free_limit": transaction.product.free_limit,
            "is_active": transaction.product.is_active,
            "metadata": transaction.product.product_metadata,
            "created_at": transaction.product.created_at,
            "updated_at": transaction.product.updated_at
        }
    
    return result


@router.get("/stats/summary")
def get_transaction_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get transaction statistics for current user
    
    Returns:
    - Summary of user's transaction history
    """
    try:
        # Get all user transactions
        transactions = TransactionService.get_user_transactions(
            db=db,
            user_id=current_user.id,
            limit=1000
        )
        
        # Calculate stats
        total_transactions = len(transactions)
        completed = sum(1 for t in transactions if t.status == TransactionStatus.COMPLETED)
        pending = sum(1 for t in transactions if t.status == TransactionStatus.PENDING)
        failed = sum(1 for t in transactions if t.status == TransactionStatus.FAILED)
        
        total_spent = sum(
            float(t.amount) for t in transactions 
            if t.status == TransactionStatus.COMPLETED and t.currency == "CLP"
        )
        
        return {
            "total_transactions": total_transactions,
            "completed": completed,
            "pending": pending,
            "failed": failed,
            "total_spent_clp": total_spent,
            "active_benefits": sum(
                1 for t in transactions 
                if t.status == TransactionStatus.COMPLETED and t.expires_at 
                and t.expires_at > db.query(User).filter(User.id == current_user.id).first().created_at
            )
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error calculating stats: {str(e)}"
        )
