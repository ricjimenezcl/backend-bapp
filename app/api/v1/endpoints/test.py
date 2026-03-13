"""
Test Endpoints for Notification System
Used for testing email, SMS, WhatsApp, and event system
Only available in development mode
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging

from app.core.database import get_db_async
from app.dependencies import get_current_user
from app.models.user import User
from app.services.event_dispatcher import get_dispatcher, EventType
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.core.config import settings

router = APIRouter(tags=["test"], prefix="/test")
logger = logging.getLogger(__name__)


@router.post("/send-email")
async def test_send_email(
    to_email: str,
    subject: str = "Test Email from BAPP",
    body: str = "<h1>Test</h1><p>This is a test email</p>",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Test email sending
    Only available in development mode
    """
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test endpoint only available in development mode"
        )
    
    try:
        email_service = EmailService()
        await email_service.send_email(
            to_email=to_email,
            subject=subject,
            body=body
        )
        return {
            "status": "success",
            "message": f"Email sent to {to_email}",
            "subject": subject
        }
    except Exception as e:
        logger.error(f"❌ Email send failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Email send failed: {str(e)}"
        )


@router.post("/send-sms")
async def test_send_sms(
    phone_number: str,
    message: str = "Test SMS from BAPP",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Test SMS sending via Twilio
    Only available in development mode
    """
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test endpoint only available in development mode"
        )
    
    try:
        from app.services.twilio_service import TwilioService
        twilio_service = TwilioService()
        success = await twilio_service.send_sms(
            phone_number=phone_number,
            message=message
        )
        
        if not success:
            raise Exception("Twilio returned false")
        
        return {
            "status": "success",
            "message": f"SMS sent to {phone_number}",
            "body": message
        }
    except Exception as e:
        logger.error(f"❌ SMS send failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SMS send failed: {str(e)}"
        )


@router.post("/send-whatsapp")
async def test_send_whatsapp(
    phone_number: str,
    message: str = "Test WhatsApp from BAPP 🔔",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Test WhatsApp sending via Twilio
    Only available in development mode
    """
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test endpoint only available in development mode"
        )
    
    try:
        from app.services.twilio_service import TwilioService
        twilio_service = TwilioService()
        success = await twilio_service.send_whatsapp(
            phone_number=phone_number,
            message=message
        )
        
        if not success:
            raise Exception("Twilio returned false")
        
        return {
            "status": "success",
            "message": f"WhatsApp sent to {phone_number}",
            "body": message
        }
    except Exception as e:
        logger.error(f"❌ WhatsApp send failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"WhatsApp send failed: {str(e)}"
        )


@router.post("/emit-event")
async def test_emit_event(
    event_type: str,
    booking_id: int,
    client_id: int,
    provider_id: int,
    service_name: str,
    scheduled_date: Optional[str] = None,
    price: Optional[float] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Test event emission to trigger notification handlers
    Only available in development mode
    
    event_type options: "booking.created", "booking.accepted", "booking.rejected"
    """
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test endpoint only available in development mode"
        )
    
    try:
        dispatcher = get_dispatcher()
        
        # Map string event type to EventType enum
        event_map = {
            "booking.created": EventType.BOOKING_CREATED,
            "booking.accepted": EventType.BOOKING_ACCEPTED,
            "booking.rejected": EventType.BOOKING_REJECTED,
        }
        
        if event_type not in event_map:
            raise ValueError(f"Unknown event type: {event_type}")
        
        event_enum = event_map[event_type]
        
        # Emit event
        await dispatcher.emit(event_enum, {
            "booking_id": booking_id,
            "client_id": client_id,
            "provider_id": provider_id,
            "service_name": service_name,
            "scheduled_date": scheduled_date or "Not specified",
            "price": price or 0
        })
        
        return {
            "status": "success",
            "message": f"Event '{event_type}' emitted successfully",
            "event_type": event_type,
            "data": {
                "booking_id": booking_id,
                "client_id": client_id,
                "provider_id": provider_id,
                "service_name": service_name
            }
        }
    except Exception as e:
        logger.error(f"❌ Event emission failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Event emission failed: {str(e)}"
        )


@router.get("/event-history")
async def test_event_history(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Get recent event history for debugging
    Only available in development mode
    """
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test endpoint only available in development mode"
        )
    
    try:
        dispatcher = get_dispatcher()
        history = dispatcher.get_event_history(limit=limit)
        
        return {
            "status": "success",
            "total_events": len(history),
            "events": history
        }
    except Exception as e:
        logger.error(f"❌ Failed to get event history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get event history: {str(e)}"
        )


@router.post("/create-notification")
async def test_create_notification(
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_async)
):
    """
    Test creating a notification directly in DB
    Only available in development mode
    """
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Test endpoint only available in development mode"
        )
    
    try:
        notification_service = NotificationService(db)
        notification = await notification_service.create_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            data={}
        )
        
        return {
            "status": "success",
            "message": "Notification created successfully",
            "notification": {
                "id": notification.id,
                "user_id": notification.user_id,
                "title": notification.title,
                "message": notification.message,
                "is_read": notification.is_read,
                "created_at": notification.created_at.isoformat() if notification.created_at else None
            }
        }
    except Exception as e:
        logger.error(f"❌ Failed to create notification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create notification: {str(e)}"
        )
