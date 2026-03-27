from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker, Session
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