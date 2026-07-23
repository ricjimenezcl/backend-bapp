from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy import event, inspect
from sqlalchemy.sql.sqltypes import DateTime as SA_DateTime, TIMESTAMP as SA_TIMESTAMP
from datetime import datetime, timezone
import os

from app.core.config import settings

# Async engine for FastAPI
# Pool sizing for ~60k users: 12k DAU → ~500 concurrent requests at peak.
# pool_size=20 + max_overflow=20 = 40 max connections. Adjust based on DB plan.
engine_async = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800
)

# Sync engine for sync operations
engine_sync = None  # Will be initialized on demand

# Async sessionmaker
AsyncSessionLocal = async_sessionmaker(
    engine_async, 
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()


def _to_utc_naive(dt: datetime) -> datetime:
    """Convert aware datetimes to UTC naive for DB columns without timezone."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _normalize_datetime_params(value):
    """Recursively normalize aware datetimes inside SQL parameter containers."""
    if isinstance(value, datetime):
        return _to_utc_naive(value)
    if isinstance(value, dict):
        return {k: _normalize_datetime_params(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_normalize_datetime_params(v) for v in value)
    if isinstance(value, list):
        return [_normalize_datetime_params(v) for v in value]
    return value


@event.listens_for(engine_async.sync_engine, "before_cursor_execute", retval=True)
def _normalize_datetime_sql_params(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    """Last-line defense for asyncpg naive/aware datetime mismatches."""
    return statement, _normalize_datetime_params(parameters)


@event.listens_for(Session, "before_flush")
def _normalize_naive_datetime_columns(session: Session, flush_context, instances):
    """Prevent asyncpg naive/aware errors on TIMESTAMP WITHOUT TIME ZONE columns."""
    for obj in session.new.union(session.dirty):
        try:
            mapper = inspect(obj).mapper
        except Exception:
            continue

        for attr in mapper.column_attrs:
            column = attr.columns[0]
            col_type = column.type

            if not isinstance(col_type, (SA_DateTime, SA_TIMESTAMP)):
                continue

            # Only normalize columns that are NOT timezone-aware in DB schema.
            if getattr(col_type, "timezone", False):
                continue

            key = attr.key
            value = getattr(obj, key, None)
            if isinstance(value, datetime) and value.tzinfo is not None:
                setattr(obj, key, _to_utc_naive(value))

# Dependency for async operations
async def get_db_async():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# Dependency for sync operations (for bookings service)
def get_db():
    """Get sync database session"""
    global engine_sync
    
    if engine_sync is None:
        from sqlalchemy import create_engine
        # Convert async URL to sync URL
        sync_url = settings.DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')
        engine_sync = create_engine(
            sync_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=10,
            pool_recycle=1800
        )
    
    SessionLocal = sessionmaker(bind=engine_sync, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()