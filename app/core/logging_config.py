"""
Configuración de logging estructurado para BAPP Search API.

- Development: formato simple legible por humanos
- Production: JSON estructurado (compatible con Render/Datadog/Sentry)
- Opcional: integración Sentry via SENTRY_DSN env var
"""

import logging
import logging.config
import os
import json
from datetime import datetime, timezone


class _JSONFormatter(logging.Formatter):
    """Formatea logs como JSON de una línea para producción."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> None:
    """
    Configura el sistema de logging.
    Llamar una vez en el lifespan de FastAPI antes de cualquier log.
    """
    env = os.getenv("ENVIRONMENT", "development")
    is_prod = env not in ("development", "dev", "local")
    level_name = os.getenv("LOG_LEVEL", "INFO" if is_prod else "DEBUG")
    level = getattr(logging, level_name.upper(), logging.INFO)

    formatter_class = "app.core.logging_config._JSONFormatter" if is_prod else "logging.Formatter"
    formatter_format = None if is_prod else "%(levelname)-8s %(name)s: %(message)s"

    config: dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": formatter_class,
                **({"format": formatter_format} if formatter_format else {}),
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {
            "level": level,
            "handlers": ["console"],
        },
        # Silenciar librerías ruidosas en producción
        "loggers": {
            "uvicorn.access": {"level": "WARNING" if is_prod else "INFO"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "httpx": {"level": "WARNING"},
            "aiohttp": {"level": "WARNING"},
        },
    }

    logging.config.dictConfig(config)

    # Integración opcional con Sentry
    sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
    if sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

            sentry_sdk.init(
                dsn=sentry_dsn,
                environment=env,
                traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.1")),
                integrations=[FastApiIntegration(), SqlalchemyIntegration()],
                send_default_pii=False,
            )
            logging.getLogger("bapp.startup").info("Sentry initialized")
        except ImportError:
            logging.getLogger("bapp.startup").warning(
                "SENTRY_DSN set but sentry-sdk not installed. "
                "Run: pip install sentry-sdk[fastapi]"
            )
