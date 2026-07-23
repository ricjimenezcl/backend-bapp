from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

try:
    from app.core.config import settings
    from app.api.v1.api import api_router
    from app.api.v1.endpoints.websocket import router as websocket_router
    from app.core.database import engine_async, Base, get_db_async
    from app.services.event_dispatcher import get_dispatcher
    from app.services.notification_event_handler import get_notification_handler
    # ¡IMPORTANTE! Importar todos los modelos ANTES de crear las tablas
    from app.models import (
        User, UserProfile, Provider, ServiceProvider,
        ServiceCategory, MainCategory, Service, Booking,
        Payment, Review, Notification, UserDocument,
        ProviderVerification, Gallery, Conversation,
        ConversationParticipant, Message, MessageStatus,
        ConversationInvitation, ConversationBlock,
        ServiceViewUnlock, ServiceViewEvent, BannedWord,
    )
except ImportError as e:
    import sys
    print(f"Import error: {e}", file=sys.stderr)
    print("Please make sure all modules are properly installed and configured", file=sys.stderr)
    raise


_startup_logger = logging.getLogger("bapp.startup")


def _split_sql_statements(sql: str) -> list[str]:
    normalized_lines: list[str] = []
    for line in sql.splitlines():
        normalized_lines.append(line.split("--", 1)[0])

    sql = "\n".join(normalized_lines)

    statements: list[str] = []
    current: list[str] = []
    in_dollar_block = False
    i = 0

    while i < len(sql):
        if sql[i:i + 2] == "$$":
            in_dollar_block = not in_dollar_block
            current.append("$$")
            i += 2
            continue

        char = sql[i]
        if char == ";" and not in_dollar_block:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


async def _run_sql_migration_file(migration_name: str, file_path: Path) -> None:
    from sqlalchemy import text

    sql = file_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql)

    async with engine_async.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))

    _startup_logger.info("Migration %s applied successfully", migration_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from app.core.logging_config import setup_logging
    setup_logging()

    _startup_logger.info("Starting up Service Finder API...")
    _startup_logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")
    _startup_logger.info(f"Database URL: {settings.DATABASE_URL[:50]}...")

    try:
        async with engine_async.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _startup_logger.info("Database tables created successfully")
    except Exception as e:
        _startup_logger.warning(f"Database initialization error: {type(e).__name__}: {e}")
        _startup_logger.warning("Continuing without database tables...")

    # Migration: make service_view_events.service_provider_id nullable (idempotent)
    try:
        from sqlalchemy import text as _text
        async with engine_async.begin() as conn:
            await conn.execute(_text(
                "ALTER TABLE service_view_events ALTER COLUMN service_provider_id DROP NOT NULL"
            ))
        _startup_logger.info("Migration: service_provider_id is now nullable")
    except Exception as e:
        _startup_logger.info(f"Migration service_provider_id skip: {type(e).__name__}: {e}")

    # Run idempotent SQL migrations needed by production schema
    migrations_dir = Path(__file__).parent / "migrations"
    startup_migrations = [
        ("014 (notifications)", migrations_dir / "014_create_notifications_table.sql"),
        ("017 (transbank fields)", migrations_dir / "017_transbank_webpay_fields.sql"),
        ("019 (service slot notifications)", migrations_dir / "019_service_slot_notifications.sql"),
        ("020 (banned words)", migrations_dir / "020_create_banned_words.sql"),
        ("021 (same email by role)", migrations_dir / "021_allow_same_email_by_role.sql"),
        ("022 (booking reminder 24h)", migrations_dir / "022_booking_reminder_24h.sql"),
    ]

    for migration_name, migration_path in startup_migrations:
        try:
            if migration_path.exists():
                await _run_sql_migration_file(migration_name, migration_path)
        except Exception as e:
            _startup_logger.warning(f"Migration {migration_name} error: {type(e).__name__}: {e}")
            _startup_logger.warning(f"Continuing without migration {migration_name}...")

    # Initialize Event Dispatcher and Notification Handlers
    try:
        dispatcher = get_dispatcher()
        _startup_logger.info("Event Dispatcher initialized")

        notification_handler = get_notification_handler()
        _startup_logger.info("Notification Event Handler initialized and subscribed")
    except Exception as e:
        _startup_logger.warning(f"Event dispatcher initialization error: {type(e).__name__}: {e}")

    # Initialize async Redis client + distributed WebSocket backend
    _redis_client_started = False
    try:
        from app.infra.redis.client import redis_client
        from app.infra.ws_redis_backend import start_ws_redis_subscriber
        await redis_client.connect(settings)
        _redis_client_started = True
        distributed = await start_ws_redis_subscriber()
        if distributed:
            _startup_logger.info("Async Redis connected + distributed WebSocket backend enabled")
        else:
            _startup_logger.info("Async Redis connected (single-instance WS mode)")
    except Exception as e:
        _startup_logger.warning(f"Async Redis not available: {type(e).__name__}: {e}")
        _startup_logger.warning("Continuing in single-instance WebSocket mode")

    # ── Cron: mantenimiento de reservas — cada hora ───────────────────────────
    import asyncio as _asyncio

    async def _booking_maintenance_cron() -> None:
        """
        Cron job de reservas — se ejecuta cada hora.

                Caso 0 (APPROVED/CONFIRMED/IN_PROGRESS con cita en <=24h):
                    Envía recordatorio único a cliente y proveedor (email + notificación in-app).

                Caso 1 (APPROVED/CONFIRMED/IN_PROGRESS → COMPLETED):
          Si la fecha + hora + duración ya terminó, marca la reserva como COMPLETED
          y envía notificación in-app + email SES al cliente con link de reseña.

        Caso 2 (PENDING expirado → DELETE):
          Si la fecha programada ya pasó y la reserva sigue PENDING,
          la elimina y envía email SES al cliente invitándolo a reagendar.
        """
        from datetime import datetime as _dt, timedelta
        from sqlalchemy import select, update
        from app.core.database import get_db_async
        from app.models.booking import Booking, BookingStatus
        from app.models.user import User as _User
        from app.models.provider import Provider as _Provider
        from app.models.notification import NotificationType
        from app.services.notification_service import NotificationService
        from app.services.email_service import get_email_service
        from app.api.websocket.connection_manager import connection_manager
        from app.infra.pubsub import publish_to_user

        logger = _startup_logger.manager.getLogger("bapp.booking_cron")

        while True:
            await _asyncio.sleep(3600)  # cada hora
            logger.info("[CRON] Running booking maintenance...")

            try:
                now_utc = datetime.utcnow()
                email_svc = get_email_service()
                frontend_url = settings.FRONTEND_URL

                async for db in get_db_async():

                    # ──────────────────────────────────────────────────────────
                    # CASO 0: recordatorio único cuando faltan <=24h para la cita
                    # ──────────────────────────────────────────────────────────
                    reminder_candidates_result = await db.execute(
                        select(Booking).where(
                            Booking.status.in_([
                                BookingStatus.APPROVED,
                                BookingStatus.CONFIRMED,
                                BookingStatus.IN_PROGRESS,
                            ]),
                            Booking.scheduled_date.isnot(None),
                            Booking.scheduled_time.isnot(None),
                            Booking.reminder_24h_sent_at.is_(None),
                        )
                    )
                    reminder_candidates = reminder_candidates_result.scalars().all()

                    reminder_sent = 0
                    for b in reminder_candidates:
                        try:
                            start_dt = _dt.combine(b.scheduled_date, b.scheduled_time)
                            delta = start_dt - now_utc

                            # Resiliente ante drift/restarts: cualquier cita próxima dentro de 24h.
                            if not (timedelta(seconds=0) < delta <= timedelta(hours=24)):
                                continue

                            client_r = await db.execute(select(_User).where(_User.id == b.client_id))
                            client = client_r.scalar_one_or_none()

                            provider_row = await db.execute(select(_Provider).where(_Provider.id == b.provider_id))
                            provider = provider_row.scalar_one_or_none()
                            provider_user = None
                            if provider:
                                provider_user_r = await db.execute(select(_User).where(_User.id == provider.user_id))
                                provider_user = provider_user_r.scalar_one_or_none()

                            if not client or not provider_user:
                                continue

                            when_text = start_dt.strftime("%d/%m/%Y %H:%M")
                            service_name = b.service_category or "Servicio"

                            notification_svc = NotificationService(db)

                            # In-app cliente/proveedor
                            await notification_svc.create_booking_notification(
                                user_id=b.client_id,
                                notification_type=NotificationType.BOOKING_REMINDER_24H,
                                booking_id=b.id,
                                message=f"Tu reserva de {service_name} es el {when_text}.",
                            )
                            await notification_svc.create_booking_notification(
                                user_id=provider_user.id,
                                notification_type=NotificationType.BOOKING_REMINDER_24H,
                                booking_id=b.id,
                                message=f"Tienes una reserva de {service_name} el {when_text}.",
                            )

                            # WebSocket real-time
                            ws_base = {
                                "type": "notification",
                                "related_entity_id": b.id,
                                "title": "Recordatorio de reserva",
                                "is_read": False,
                            }
                            await connection_manager.broadcast_to_user(b.client_id, {
                                **ws_base,
                                "notification_type": "booking_reminder_24h",
                                "content": f"Tu reserva de {service_name} es el {when_text}.",
                                "message": f"Tu reserva de {service_name} es el {when_text}.",
                            })
                            await connection_manager.broadcast_to_user(provider_user.id, {
                                **ws_base,
                                "notification_type": "booking_reminder_24h",
                                "content": f"Tienes una reserva de {service_name} el {when_text}.",
                                "message": f"Tienes una reserva de {service_name} el {when_text}.",
                            })

                            # Pub/Sub offline
                            publish_to_user(b.client_id, "booking_reminder_24h", {
                                "booking_id": b.id,
                                "related_entity_id": b.id,
                            })
                            publish_to_user(provider_user.id, "booking_reminder_24h", {
                                "booking_id": b.id,
                                "related_entity_id": b.id,
                            })

                            # Email cliente/proveedor
                            _asyncio.create_task(email_svc.send_booking_reminder(
                                email=client.email,
                                user_name=getattr(client, "full_name", "") or client.email,
                                is_provider=False,
                                data={
                                    "title": "Recordatorio: tu reserva es en menos de 24 horas ⏰",
                                    "message": f"Tu reserva de <strong>{service_name}</strong> está agendada para el <strong>{when_text}</strong>.",
                                    "service_name": service_name,
                                    "booking_date": when_text,
                                    "other_party_name": getattr(provider_user, "full_name", "") or "Proveedor",
                                    "location": b.location_address or "Ver en la app",
                                    "action_text": "Ver mi reserva",
                                    "action_url": f"{frontend_url}/client/tabs/bookings",
                                }
                            ))
                            _asyncio.create_task(email_svc.send_booking_reminder(
                                email=provider_user.email,
                                user_name=getattr(provider_user, "full_name", "") or provider_user.email,
                                is_provider=True,
                                data={
                                    "title": "Recordatorio: tienes una reserva en menos de 24 horas ⏰",
                                    "message": f"Tienes una reserva de <strong>{service_name}</strong> agendada para el <strong>{when_text}</strong>.",
                                    "service_name": service_name,
                                    "booking_date": when_text,
                                    "other_party_name": getattr(client, "full_name", "") or "Cliente",
                                    "location": b.location_address or "Ver en la app",
                                    "action_text": "Ver reservas",
                                    "action_url": f"{frontend_url}/provider/tabs/bookings",
                                }
                            ))

                            await db.execute(
                                update(Booking)
                                .where(Booking.id == b.id)
                                .values(reminder_24h_sent_at=now_utc)
                            )
                            await db.commit()
                            reminder_sent += 1

                        except Exception as exc:
                            logger.error(f"[CRON] ❌ Error sending 24h reminder for booking {b.id}: {exc}")
                            await db.rollback()

                    # ──────────────────────────────────────────────────────────
                    # CASO 1: APPROVED / CONFIRMED / IN_PROGRESS → COMPLETED
                    # ──────────────────────────────────────────────────────────
                    active_result = await db.execute(
                        select(Booking).where(
                            Booking.status.in_([
                                BookingStatus.APPROVED,
                                BookingStatus.CONFIRMED,
                                BookingStatus.IN_PROGRESS,
                            ]),
                            Booking.scheduled_date.isnot(None),
                            Booking.scheduled_time.isnot(None),
                        )
                    )
                    active_bookings = active_result.scalars().all()

                    to_complete = []
                    for b in active_bookings:
                        try:
                            end_dt = _dt.combine(b.scheduled_date, b.scheduled_time) + timedelta(minutes=b.duration or 60)
                            if end_dt <= now_utc:
                                to_complete.append(b)
                        except Exception:
                            continue

                    for b in to_complete:
                        try:
                            # Cargar cliente y proveedor para SES
                            client_r = await db.execute(select(_User).where(_User.id == b.client_id))
                            client = client_r.scalar_one_or_none()

                            # Marcar como COMPLETED
                            await db.execute(
                                update(Booking)
                                .where(Booking.id == b.id)
                                .values(status=BookingStatus.COMPLETED, completed_at=now_utc)
                            )
                            await db.commit()

                            notification_svc = NotificationService(db)

                            # Notificaciones in-app
                            await notification_svc.create_booking_notification(
                                user_id=b.client_id,
                                notification_type=NotificationType.BOOKING_COMPLETED,
                                booking_id=b.id,
                                message="Tu servicio ha sido completado.",
                            )
                            await notification_svc.create_booking_notification(
                                user_id=b.client_id,
                                notification_type=NotificationType.BOOKING_REVIEW_REQUEST,
                                booking_id=b.id,
                                message="¿Cómo fue tu experiencia? Califica el servicio recibido.",
                            )

                            # WebSocket en tiempo real
                            ws_base = {
                                "type": "notification",
                                "related_entity_id": b.id,
                            }
                            await connection_manager.broadcast_to_user(b.client_id, {
                                **ws_base,
                                "notification_type": "booking_completed",
                                "message": "Tu servicio ha sido completado.",
                            })
                            await connection_manager.broadcast_to_user(b.client_id, {
                                **ws_base,
                                "notification_type": "booking_review_request",
                                "message": "¿Cómo fue tu experiencia? Califica el servicio.",
                            })

                            # Pub/Sub offline
                            publish_to_user(b.client_id, "booking_review_request", {
                                "booking_id": b.id,
                                "related_entity_id": b.id,
                            })

                            # SES: email con link de reseña (no crítico)
                            if client:
                                review_url = f"{frontend_url}/client/bookings?review={b.id}"
                                _asyncio.create_task(email_svc.send_booking_completed_email(
                                    client_email=client.email,
                                    client_name=getattr(client, "full_name", "") or client.email,
                                    provider_name=b.service_category or "tu proveedor",
                                    review_url=review_url,
                                ))

                            logger.info(f"[CRON] ✅ Auto-completed booking {b.id} for client {b.client_id}")

                        except Exception as exc:
                            logger.error(f"[CRON] ❌ Error completing booking {b.id}: {exc}")
                            await db.rollback()

                    # ──────────────────────────────────────────────────────────
                    # CASO 2: PENDING expirado → DELETE
                    # ──────────────────────────────────────────────────────────
                    expired_result = await db.execute(
                        select(Booking).where(
                            Booking.status == BookingStatus.PENDING,
                            Booking.scheduled_date.isnot(None),
                            Booking.scheduled_date <= now_utc.date(),
                        )
                    )
                    pending_candidates = expired_result.scalars().all()

                    expired_bookings = []
                    for b in pending_candidates:
                        try:
                            if b.scheduled_time:
                                pending_start = _dt.combine(b.scheduled_date, b.scheduled_time)
                                if pending_start <= now_utc.replace(tzinfo=None):
                                    expired_bookings.append(b)
                            else:
                                if b.scheduled_date < now_utc.date():
                                    expired_bookings.append(b)
                        except Exception:
                            continue

                    for b in expired_bookings:
                        try:
                            client_r = await db.execute(select(_User).where(_User.id == b.client_id))
                            client = client_r.scalar_one_or_none()

                            # Eliminar registro
                            await db.delete(b)
                            await db.commit()

                            # SES: email de expiración (no crítico)
                            if client:
                                scheduled_str = b.scheduled_date.strftime("%d/%m/%Y") if b.scheduled_date else "N/A"
                                search_url = f"{frontend_url}/services"
                                _asyncio.create_task(email_svc.send_booking_expired_email(
                                    client_email=client.email,
                                    client_name=getattr(client, "full_name", "") or client.email,
                                    service_name=b.service_category or "Servicio",
                                    scheduled_date=scheduled_str,
                                    search_url=search_url,
                                ))

                            logger.info(f"[CRON] 🗑️ Deleted expired PENDING booking {b.id} for client {b.client_id}")

                        except Exception as exc:
                            logger.error(f"[CRON] ❌ Error deleting expired booking {b.id}: {exc}")
                            await db.rollback()

                    logger.info(
                        f"[CRON] Maintenance complete — reminders_24h: {reminder_sent}, completed: {len(to_complete)}, expired/deleted: {len(expired_bookings)}"
                    )

            except Exception as exc:
                logger.error(f"[CRON] ❌ Maintenance task error: {exc}")

    _auto_complete_task = _asyncio.create_task(_booking_maintenance_cron())
    _startup_logger.info("Booking maintenance cron started (every 1 hour)")

    try:
        yield
    finally:
        # Shutdown
        _startup_logger.info("Shutting down...")

        # Cancelar tarea de auto-completado
        try:
            _auto_complete_task.cancel()
            await _asyncio.gather(_auto_complete_task, return_exceptions=True)
            _startup_logger.info("Booking maintenance cron cancelled")
        except Exception:
            pass

        if _redis_client_started:
            try:
                from app.infra.ws_redis_backend import stop_ws_redis_subscriber
                from app.infra.redis.client import redis_client
                await stop_ws_redis_subscriber()
                await redis_client.disconnect()
                _startup_logger.info("Async Redis disconnected")
            except Exception as e:
                _startup_logger.warning(f"Error during async Redis shutdown: {e}")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Agrega cabeceras de seguridad HTTP a todas las respuestas."""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            raise
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP permisive para API: la app frontend tiene su propio CSP
        response.headers["Content-Security-Policy"] = "default-src 'none';  script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline';  style-src 'self' https://cdn.jsdelivr.net;  img-src 'self' https://fastapi.tiangolo.com;  connect-src 'self';   # Permite llamadas a tu API  font-src 'self';  frame-ancestors 'none';  base-uri 'self';  form-action 'self';"
        # Eliminar fingerprint del servidor
        if "server" in response.headers:
            del response.headers["server"]
        return response


def create_app() -> FastAPI:
    _logger = logging.getLogger(__name__)

    app = FastAPI(
        title="Service Finder API",
        description="Backend para aplicación de servicios por geolocalización",
        version="1.0.0",
        lifespan=lifespan
    )

    # Security headers (primero, envuelve todo)
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — métodos y cabeceras explícitos (no ["*"])
    _logger.info(f"CORS ORIGINS: {settings.ALLOWED_ORIGINS}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    )

    # -------------------------------------------------------
    # VALIDATION ERROR HANDLER - Enhanced error messages for 422
    # -------------------------------------------------------
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """
        Handle Pydantic validation errors with clear, actionable messages.
        This prevents 422 errors from being cryptic.
        """
        errors = []
        for error in exc.errors():
            # Build field path (e.g., "body -> selfie_document_id")
            field_path = " -> ".join(str(loc) for loc in error['loc'] if loc not in ('body', 'values'))
            error_detail = {
                "field": field_path or "body",
                "type": error['type'],
                "message": error['msg'],
                "input": str(error.get('input', 'unknown'))[:100]  # Limit input length
            }
            errors.append(error_detail)
        
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[VALIDATION_ERROR] Request: {request.url.path} | Method: {request.method}")
        logger.error(f"[VALIDATION_ERROR] Errors: {errors}")

        first_message = errors[0]["message"] if errors else "Request validation failed"
        
        return JSONResponse(
            status_code=422,
            content={
            "detail": first_message,
                "errors": errors,
                "hint": "Check that all required fields are present and have correct types",
                "path": str(request.url.path),
                "method": request.method
            }
        )

    # Exception handler para excepciones de aplicación
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        _exc_logger = logging.getLogger("bapp.exceptions")
        exc_type = type(exc).__name__
        # Skip asyncio exceptions - let uvicorn handle them
        if exc_type in ('CancelledError', 'TaskGroupException', 'WouldBlock'):
            raise

        try:
            exc_detail = str(exc)
        except Exception:
            exc_detail = "Error converting exception"
        _exc_logger.error(f"Unhandled exception: {exc_type}: {exc_detail}", exc_info=True)

        # Add CORS headers manually so the browser sees the error (not a CORS block)
        origin = request.headers.get("origin", "")
        cors_headers = {}
        if origin in settings.ALLOWED_ORIGINS:
            cors_headers = {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
            }

        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {exc_type}"},
            headers=cors_headers if cors_headers else None,
        )

    # Include routers
    try:
        app.include_router(api_router, prefix="/api/v1")
        app.include_router(websocket_router, prefix="/api/v1")
    except Exception as e:
        _logger.error(f"Router initialization error: {e}", exc_info=True)

    return app


app = create_app()


# -------------------------------------------------------
# Endpoints de diagnóstico
# -------------------------------------------------------
@app.get("/")
async def root():
    return {
        "message": "Service Finder API",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health")
async def health_check():
    """Health check CON test real de base de datos"""
    db_status = "unknown"
    db_error = None
    db_latency_ms = None

    try:
        from sqlalchemy import text
        import time

        start = time.time()
        async with engine_async.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        db_latency_ms = round((time.time() - start) * 1000)
        db_status = "connected"
    except Exception as e:
        db_status = "error"
        db_error = f"{type(e).__name__}: {str(e)}"
        logging.getLogger("bapp.health").warning(f"Health check DB error: {db_error}")

    # Check Celery/Redis health
    celery_status = "unknown"
    celery_error = None
    try:
        from app.core.celery import celery_app
        inspect_result = celery_app.control.inspect().active()
        if inspect_result is not None:
            celery_status = "connected"
        else:
            celery_status = "no_workers"
    except Exception as e:
        celery_status = "error"
        celery_error = f"{type(e).__name__}: {str(e)}"
        logging.getLogger("bapp.health").warning(f"Health check Celery error: {celery_error}")

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
        "db_latency_ms": db_latency_ms,
        "db_error": db_error,
        "celery": celery_status,
        "celery_error": celery_error,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


@app.get("/debug/db")
async def debug_database():
    """
    Diagnóstico COMPLETO de la base de datos.
    Prueba conexión, lista tablas, y cuenta usuarios.
    """
    results = {
        "database_url": settings.DATABASE_URL[:30] + "...",
        "db_host": settings.DB_HOST,
        "db_name": settings.DB_NAME,
        "steps": {}
    }

    # Paso 1: Conectar
    try:
        from sqlalchemy import text
        async with engine_async.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        results["steps"]["1_connect"] = "✅ OK"
    except Exception as e:
        results["steps"]["1_connect"] = f"❌ {type(e).__name__}: {str(e)}"
        return results

    # Paso 2: Listar tablas
    try:
        async with engine_async.begin() as conn:
            result = await conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            tables = [row[0] for row in result.fetchall()]
        results["steps"]["2_tables"] = f"✅ {tables}"
    except Exception as e:
        results["steps"]["2_tables"] = f"❌ {type(e).__name__}: {str(e)}"
        return results

    # Paso 3: Contar usuarios
    try:
        async with engine_async.begin() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM users"))
            count = result.scalar()
        results["steps"]["3_user_count"] = f"✅ {count} usuarios"
    except Exception as e:
        results["steps"]["3_user_count"] = f"❌ {type(e).__name__}: {str(e)}"

    # Paso 4: Buscar el usuario de test
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT id, email, role, status FROM users WHERE email = 'searchbapp@gmail.com'"
            ))
            user = result.fetchone()
        if user:
            results["steps"]["4_test_user"] = f"✅ Encontrado: id={user[0]}, role={user[2]}, status={user[3]}"
        else:
            results["steps"]["4_test_user"] = "⚠️ Usuario searchbapp@gmail.com NO encontrado"
    except Exception as e:
        results["steps"]["4_test_user"] = f"❌ {type(e).__name__}: {str(e)}"

    return results


@app.get("/config")
async def show_config():
    """Endpoint para verificar la configuración (solo desarrollo)"""
    return {
        "database_url_preview": settings.DATABASE_URL[:40] + "...",
        "db_host": settings.DB_HOST,
        "db_name": settings.DB_NAME,
        "allowed_origins": settings.ALLOWED_ORIGINS,
        "environment": os.getenv("ENVIRONMENT", "development")
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)