import logging
from typing import List

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.models.review import Review
from app.models.booking import Booking
from app.models.provider import Provider, ServiceProvider
from app.models.notification import NotificationType
from app.schemas.review import CreateReviewRequest, ReviewResponse
from app.schemas.booking import BookingStatusEnum

logger = logging.getLogger(__name__)


class ReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _resolve_review_provider_id(self, booking: Booking) -> int:
        """
        Resuelve el valor a guardar en reviews.provider_id.

        En la BD actual, reviews.provider_id referencia service_providers.id.
        Priorizamos booking.service_provider_id y, si no existe, intentamos
        inferirlo por provider_id (+ service_id cuando esté disponible).
        """
        if booking.service_provider_id:
            return booking.service_provider_id

        query = select(ServiceProvider).where(
            ServiceProvider.provider_id == booking.provider_id
        )

        if booking.service_id:
            query = query.where(ServiceProvider.service_id == booking.service_id)

        result = await self.db.execute(query.order_by(ServiceProvider.id.asc()).limit(1))
        sp = result.scalar_one_or_none()
        if sp:
            return sp.id

        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo resolver el servicio del proveedor para esta reserva. "
                "Contacta soporte para regularizar la data histórica."
            ),
        )

    async def create_review(self, client_id: int, review_in: CreateReviewRequest) -> ReviewResponse:
        # 1. Verificar Booking existe
        result_booking = await self.db.execute(
            select(Booking).where(Booking.id == review_in.booking_id)
        )
        booking = result_booking.scalar_one_or_none()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        # 2. Verificar que el cliente sea dueño del booking
        if booking.client_id != client_id:
            raise HTTPException(status_code=403, detail="Not authorized to review this booking")

        # 3. Verificar que el booking esté COMPLETADO
        if booking.status != BookingStatusEnum.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail=f"El booking debe estar COMPLETADO para dejar una reseña (estado actual: {booking.status})"
            )

        # 4. Verificar que no existe reseña previa para este booking
        result_exists = await self.db.execute(
            select(Review).where(Review.booking_id == review_in.booking_id)
        )
        if result_exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Ya existe una reseña para este booking")

        # 5. Resolver service_provider_id objetivo para la reseña
        review_provider_id = await self._resolve_review_provider_id(booking)

        # 6. Crear la reseña
        new_review = Review(
            booking_id=review_in.booking_id,
            client_id=client_id,
            provider_id=review_provider_id,
            rating=review_in.rating,
            comment=review_in.comment,
        )
        self.db.add(new_review)

        # Flush para obtener el id y para que el AVG lo incluya
        await self.db.flush()

        # 7. Recalcular ratings (ServiceProvider + Provider padre)
        await self._recalculate_ratings(review_provider_id)

        # 8. Commit principal
        await self.db.commit()
        await self.db.refresh(new_review)

        # 9. Notificar al proveedor (transacción separada — no crítica)
        await self._notify_provider_review(new_review, review_provider_id, review_in)

        # 10. Resolver client_name para el response
        client_name = await self._get_client_name(client_id)

        return ReviewResponse(
            id=new_review.id,
            booking_id=new_review.booking_id,
            client_id=new_review.client_id,
            provider_id=new_review.provider_id,
            rating=float(new_review.rating),
            comment=new_review.comment,
            client_name=client_name,
            created_at=new_review.created_at,
            updated_at=new_review.updated_at,
        )

    async def _recalculate_ratings(self, provider_id: int):
        """Recalcula rating_avg y total_reviews en ServiceProvider y en Provider padre."""
        # ServiceProvider: recalcular por reviews directas
        sp_result = await self.db.execute(
            select(ServiceProvider).where(ServiceProvider.id == provider_id)
        )
        sp = sp_result.scalar_one_or_none()
        if not sp:
            return

        # AVG y COUNT de reviews sobre este ServiceProvider
        stats_result = await self.db.execute(
            select(
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("count_reviews"),
            ).where(Review.provider_id == provider_id)
        )
        stats = stats_result.first()
        sp.rating_avg = round(float(stats.avg_rating or 0), 2)
        sp.total_reviews = int(stats.count_reviews or 0)
        self.db.add(sp)

        # Provider padre: recalcular sobre todos sus ServiceProviders
        main_prov_result = await self.db.execute(
            select(Provider).where(Provider.id == sp.provider_id)
        )
        main_prov = main_prov_result.scalar_one_or_none()
        if main_prov:
            agg_result = await self.db.execute(
                select(
                    func.avg(ServiceProvider.rating_avg).label("avg"),
                    func.sum(ServiceProvider.total_reviews).label("total"),
                ).where(ServiceProvider.provider_id == main_prov.id)
            )
            agg = agg_result.first()
            main_prov.rating_avg = round(float(agg.avg or 0), 2)
            self.db.add(main_prov)

        logger.info(f"[REVIEWS] Ratings recalculados para ServiceProvider {provider_id}")

    async def _notify_provider_review(
        self,
        review: Review,
        service_provider_id: int,
        review_in: CreateReviewRequest,
    ):
        """Envía notificación al proveedor. Falla silenciosamente (no crítico)."""
        try:
            sp_result = await self.db.execute(
                select(ServiceProvider).where(ServiceProvider.id == service_provider_id)
            )
            sp = sp_result.scalar_one_or_none()
            if not sp:
                return

            prov_result = await self.db.execute(
                select(Provider).where(Provider.id == sp.provider_id)
            )
            provider = prov_result.scalar_one_or_none()
            if not provider:
                return

            from app.services.notification_service import NotificationService
            notif_service = NotificationService(self.db)

            preview = review_in.comment[:80] if review_in.comment else "Sin comentario"
            notif = await notif_service.create_notification(
                user_id=provider.user_id,
                notification_type=NotificationType.REVIEW_RECEIVED,
                title="Nueva reseña recibida",
                content=f"⭐ {review_in.rating}/5 — {preview}",
                related_entity_type="review",
                related_entity_id=review.id,
            )

            # Enviar por WebSocket si el proveedor está conectado
            try:
                from app.api.websocket.connection_manager import connection_manager
                from app.infra.pubsub import publish_to_user
                ws_payload = {
                    "type": "notification",
                    "notificationId": notif.id,
                    "notificationType": NotificationType.REVIEW_RECEIVED.value,
                    "title": notif.title,
                    "content": notif.content,
                    "relatedEntityType": "review",
                    "relatedEntityId": review.id,
                }
                if connection_manager.is_user_online(provider.user_id):
                    import asyncio
                    asyncio.create_task(
                        connection_manager.broadcast_to_user(provider.user_id, ws_payload)
                    )
                else:
                    import asyncio
                    asyncio.create_task(publish_to_user(provider.user_id, ws_payload))
            except Exception as ws_err:
                logger.warning(f"[REVIEWS] WS notify error (non-critical): {ws_err}")

        except Exception as e:
            logger.warning(f"[REVIEWS] Error enviando notificación REVIEW_RECEIVED (non-critical): {e}")

    async def _get_client_name(self, client_id: int) -> str | None:
        """Obtiene el nombre del cliente para incluirlo en el response."""
        try:
            from app.models.user import UserProfile
            result = await self.db.execute(
                select(UserProfile).where(UserProfile.user_id == client_id)
            )
            profile = result.scalar_one_or_none()
            return profile.full_name if profile else None
        except Exception:
            return None

    async def get_provider_reviews(self, provider_id: int, limit: int = 20) -> List[ReviewResponse]:
        """Lista reseñas de un proveedor (providers.id) con nombre del cliente."""
        from app.models.user import UserProfile

        # reviews.provider_id referencia service_providers.id en la BD actual,
        # por eso primero resolvemos los servicios publicados del proveedor.
        sp_result = await self.db.execute(
            select(ServiceProvider.id).where(ServiceProvider.provider_id == provider_id)
        )
        sp_ids = [row[0] for row in sp_result.all()]
        if not sp_ids:
            return []

        result = await self.db.execute(
            select(Review)
            .where(Review.provider_id.in_(sp_ids))
            .order_by(Review.created_at.desc())
            .limit(limit)
        )
        reviews = result.scalars().all()

        # Recopilar client_ids para cargar nombres en bulk
        client_ids = list({r.client_id for r in reviews})
        profiles_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id.in_(client_ids))
        )
        profiles_map = {p.user_id: p.full_name for p in profiles_result.scalars().all()}

        return [
            ReviewResponse(
                id=r.id,
                booking_id=r.booking_id,
                client_id=r.client_id,
                provider_id=r.provider_id,
                rating=float(r.rating),
                comment=r.comment,
                client_name=profiles_map.get(r.client_id),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in reviews
        ]
