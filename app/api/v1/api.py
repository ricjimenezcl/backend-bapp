from fastapi import APIRouter, Depends, HTTPException
from app.api.v1.endpoints import auth, providers, payments, categories, users, notifications, reviews, chat, test, working_hours, clients, premium, products, payments_verify, payments_transbank, transactions, geocoding, service_viewers, reports, content_moderation, assistant
from app.api.v1.endpoints.client_images import router as client_images_router
from app.api.v1.endpoints.provider_images import router as provider_images_router
from app.modules.documents import router as documents_router
from app.modules.bookings import router as bookings_router


api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(providers.router, prefix="/providers", tags=["providers"])
api_router.include_router(bookings_router)  # Ya incluye /api/v1/bookings en el router
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(payments_verify.router, prefix="/payments", tags=["payment-verification"])
api_router.include_router(payments_transbank.router, prefix="/payments", tags=["payments-transbank"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(working_hours.router, prefix="/working-hours", tags=["working-hours"])
api_router.include_router(premium.router, prefix="/premium", tags=["premium"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_router.include_router(documents_router, tags=["documents"])
api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
api_router.include_router(geocoding.router)  # Geocoding proxy (no prefix, already in router)
api_router.include_router(test.router, tags=["test"])  # Test endpoints for development
api_router.include_router(client_images_router)    # /client/images/avatar
api_router.include_router(provider_images_router)  # /provider/images/avatar + /portfolio
api_router.include_router(service_viewers.router, prefix="/providers", tags=["service-viewers"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(content_moderation.router, prefix="/content", tags=["content-moderation"])
# api_router.include_router(admin.router, prefix="/admin", tags=["admin"])  # Comentado temporalmente