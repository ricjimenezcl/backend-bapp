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
        ServiceViewUnlock, ServiceViewEvent,
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

    # ── Auto-complete expired bookings — tarea periódica ─────────────────────
    import asyncio as _asyncio

    async def _auto_complete_expired_bookings() -> None:
        """
        Cada 5 minutos busca reservas CONFIRMED o IN_PROGRESS cuya fecha/hora
        + duración ya haya pasado y las marca como COMPLETED, enviando la
        solicitud de reseña al cliente.
        """
        from sqlalchemy import select, update, func as sqlfunc, cast, Interval
        from sqlalchemy.dialects.postgresql import INTERVAL
        from app.core.database import get_db_async
        from app.models.booking import Booking, BookingStatus
        from app.models.notification import NotificationType
        from app.services.notification_service import NotificationService
        from app.api.websocket.connection_manager import connection_manager
        from app.infra.pubsub import publish_to_user

        logger = _startup_logger.manager.getLogger("bapp.autocomplete")

        while True:
            await _asyncio.sleep(300)  # ejecutar cada 5 minutos
            try:
                now_utc = datetime.now(timezone.utc)
                async for db in get_db_async():
                    # Reservas activas cuyo momento de fin (fecha + hora + duración) ya pasó
                    result = await db.execute(
                        select(Booking).where(
                            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS]),
                            Booking.scheduled_date.isnot(None),
                            Booking.scheduled_time.isnot(None),
                        )
                    )
                    bookings = result.scalars().all()

                    completed_ids = []
                    for booking in bookings:
                        try:
                            from datetime import datetime as _dt, timedelta
                            scheduled_dt = _dt.combine(booking.scheduled_date, booking.scheduled_time)
                            duration_min = booking.duration or 60
                            end_dt = scheduled_dt + timedelta(minutes=duration_min)
                            # Comparar sin timezone (asumimos hora local del servidor == UTC o igual zona)
                            if end_dt <= now_utc.replace(tzinfo=None):
                                completed_ids.append(booking)
                        except Exception:
                            continue

                    for booking in completed_ids:
                        try:
                            await db.execute(
                                update(Booking)
                                .where(Booking.id == booking.id)
                                .values(status=BookingStatus.COMPLETED, completed_at=now_utc)
                            )
                            await db.commit()

                            notification_svc = NotificationService(db)

                            # Notificaciones al cliente
                            await notification_svc.create_booking_notification(
                                user_id=booking.client_id,
                                notification_type=NotificationType.BOOKING_COMPLETED,
                                booking_id=booking.id,
                                message="Tu servicio ha sido completado."
                            )
                            await notification_svc.create_booking_notification(
                                user_id=booking.client_id,
                                notification_type=NotificationType.BOOKING_REVIEW_REQUEST,
                                booking_id=booking.id,
                                message="¿Cómo fue tu experiencia? Califica el servicio recibido."
                            )

                            # WebSocket en tiempo real
                            await connection_manager.broadcast_to_user(booking.client_id, {
                                "type": "notification",
                                "notification_type": "booking_completed",
                                "related_entity_id": booking.id,
                                "message": "Tu servicio ha sido completado."
                            })
                            await connection_manager.broadcast_to_user(booking.client_id, {
                                "type": "notification",
                                "notification_type": "booking_review_request",
                                "related_entity_id": booking.id,
                                "message": "¿Cómo fue tu experiencia? Califica el servicio."
                            })

                            # Cola offline
                            publish_to_user(booking.client_id, "booking_review_request", {
                                "booking_id": booking.id,
                                "related_entity_id": booking.id,
                            })

                            logger.info(f"✅ Auto-completed booking {booking.id} for client {booking.client_id}")

                        except Exception as exc:
                            logger.error(f"❌ Error auto-completing booking {booking.id}: {exc}")
                            await db.rollback()

            except Exception as exc:
                logger.error(f"❌ Auto-complete task error: {exc}")

    _auto_complete_task = _asyncio.create_task(_auto_complete_expired_bookings())
    _startup_logger.info("Auto-complete expired bookings task started (every 5 min)")

    try:
        yield
    finally:
        # Shutdown
        _startup_logger.info("Shutting down...")

        # Cancelar tarea de auto-completado
        try:
            _auto_complete_task.cancel()
            await _asyncio.gather(_auto_complete_task, return_exceptions=True)
            _startup_logger.info("Auto-complete task cancelled")
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
        
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Request validation failed",
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