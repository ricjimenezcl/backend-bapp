# app/infra/redis/client.py
"""
Redis Client Module - Singleton instance for Redis connection management
Supports connection pooling, health checks, and graceful shutdown
"""

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool
from typing import Optional, Any, Dict, List
import logging
from app.core.config import Settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Singleton Redis client with connection pooling and health checks"""
    
    _instance: Optional['RedisClient'] = None
    _client: Optional[redis.Redis] = None
    _pool: Optional[ConnectionPool] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisClient, cls).__new__(cls)
        return cls._instance
    
    async def connect(self, settings: Settings) -> None:
        """Initialize Redis connection with pooling (Render/Upstash-compatible)"""
        try:
            if settings.REDIS_URL:
                # Production: URL-based connection (Render Redis, Upstash TCP rediss://, etc.)
                self._pool = ConnectionPool.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=5,
                    socket_connect_timeout=5,
                )
                logger.info(f"✅ Async Redis: using REDIS_URL (production mode)")
            else:
                # Development: host/port connection (local Redis)
                self._pool = ConnectionPool(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=5,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    socket_keepalive_options={
                        1: 1,  # TCP_KEEPIDLE
                        2: 3,  # TCP_KEEPINTVL
                    },
                )
                logger.info(f"✅ Async Redis: using {settings.REDIS_HOST}:{settings.REDIS_PORT} (dev mode)")

            self._client = redis.Redis(connection_pool=self._pool)

            # Test connection
            await self.health_check()
            logger.info("✅ Async Redis connected successfully")

        except Exception as e:
            logger.error(f"❌ Async Redis connection failed: {str(e)}")
            raise
    
    async def health_check(self) -> bool:
        """Check Redis connectivity and return status"""
        try:
            if not self._client:
                return False
            
            pong = await self._client.ping()
            if pong:
                logger.debug("Redis health check passed")
                return True
            return False
        except Exception as e:
            logger.error(f"Redis health check failed: {str(e)}")
            return False
    
    async def disconnect(self) -> None:
        """Close Redis connection gracefully"""
        if self._client:
            await self._client.close()
            self._client = None
        if self._pool:
            await self._pool.disconnect()
            self._pool = None
        logger.info("Redis disconnected")
    
    @staticmethod
    def get_instance() -> 'RedisClient':
        """Get Redis singleton instance"""
        if RedisClient._instance is None:
            RedisClient()
        return RedisClient._instance
    
    @property
    def client(self) -> redis.Redis:
        """Get Redis client instance"""
        if not self._client:
            raise RuntimeError("Redis client not initialized. Call connect() first.")
        return self._client
    
    # ========== String Operations ==========
    
    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """Set key-value with optional expiration (seconds)"""
        try:
            await self._client.set(key, value, ex=ex)
            return True
        except Exception as e:
            logger.error(f"Redis SET failed for {key}: {str(e)}")
            return False
    
    async def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error(f"Redis GET failed for {key}: {str(e)}")
            return None
    
    async def delete(self, *keys: str) -> int:
        """Delete one or more keys"""
        try:
            return await self._client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis DELETE failed: {str(e)}")
            return 0
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis EXISTS failed for {key}: {str(e)}")
            return False
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on existing key"""
        try:
            return await self._client.expire(key, seconds)
        except Exception as e:
            logger.error(f"Redis EXPIRE failed for {key}: {str(e)}")
            return False
    
    async def ttl(self, key: str) -> int:
        """Get remaining TTL in seconds (-2: not exists, -1: no expiration)"""
        try:
            return await self._client.ttl(key)
        except Exception as e:
            logger.error(f"Redis TTL failed for {key}: {str(e)}")
            return -2
    
    # ========== Hash Operations ==========
    
    async def hset(self, name: str, mapping: Dict[str, Any]) -> int:
        """Set hash fields from mapping"""
        try:
            return await self._client.hset(name, mapping=mapping)
        except Exception as e:
            logger.error(f"Redis HSET failed for {name}: {str(e)}")
            return 0
    
    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field value"""
        try:
            return await self._client.hget(name, key)
        except Exception as e:
            logger.error(f"Redis HGET failed for {name}: {str(e)}")
            return None
    
    async def hgetall(self, name: str) -> Dict[str, str]:
        """Get all hash fields"""
        try:
            return await self._client.hgetall(name)
        except Exception as e:
            logger.error(f"Redis HGETALL failed for {name}: {str(e)}")
            return {}
    
    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields"""
        try:
            return await self._client.hdel(name, *keys)
        except Exception as e:
            logger.error(f"Redis HDEL failed for {name}: {str(e)}")
            return 0
    
    # ========== List Operations ==========
    
    async def lpush(self, key: str, *values) -> int:
        """Push values to list head"""
        try:
            return await self._client.lpush(key, *values)
        except Exception as e:
            logger.error(f"Redis LPUSH failed for {key}: {str(e)}")
            return 0
    
    async def rpop(self, key: str, count: int = 1) -> Optional[List[str]]:
        """Pop values from list tail"""
        try:
            if count == 1:
                return await self._client.rpop(key)
            return await self._client.rpop(key, count=count)
        except Exception as e:
            logger.error(f"Redis RPOP failed for {key}: {str(e)}")
            return None
    
    async def lrange(self, key: str, start: int = 0, end: int = -1) -> List[str]:
        """Get range of list items"""
        try:
            return await self._client.lrange(key, start, end)
        except Exception as e:
            logger.error(f"Redis LRANGE failed for {key}: {str(e)}")
            return []
    
    async def llen(self, key: str) -> int:
        """Get list length"""
        try:
            return await self._client.llen(key)
        except Exception as e:
            logger.error(f"Redis LLEN failed for {key}: {str(e)}")
            return 0
    
    # ========== Pub/Sub Operations ==========
    
    async def publish(self, channel: str, message: str) -> int:
        """Publish message to channel"""
        try:
            return await self._client.publish(channel, message)
        except Exception as e:
            logger.error(f"Redis PUBLISH failed for {channel}: {str(e)}")
            return 0
    
    async def subscribe(self, *channels: str):
        """Subscribe to channels (returns PubSub object)"""
        try:
            pubsub = self._client.pubsub()
            await pubsub.subscribe(*channels)
            return pubsub
        except Exception as e:
            logger.error(f"Redis SUBSCRIBE failed: {str(e)}")
            return None
    
    # ========== Sorted Set Operations ==========
    
    async def zadd(self, key: str, mapping: Dict[str, float]) -> int:
        """Add members to sorted set with scores"""
        try:
            return await self._client.zadd(key, mapping)
        except Exception as e:
            logger.error(f"Redis ZADD failed for {key}: {str(e)}")
            return 0
    
    async def zrange(self, key: str, start: int = 0, end: int = -1, 
                     withscores: bool = False) -> List:
        """Get range from sorted set"""
        try:
            return await self._client.zrange(key, start, end, withscores=withscores)
        except Exception as e:
            logger.error(f"Redis ZRANGE failed for {key}: {str(e)}")
            return []
    
    async def zcard(self, key: str) -> int:
        """Get sorted set cardinality"""
        try:
            return await self._client.zcard(key)
        except Exception as e:
            logger.error(f"Redis ZCARD failed for {key}: {str(e)}")
            return 0
    
    # ========== Set Operations ==========
    
    async def sadd(self, key: str, *members: str) -> int:
        """Add members to set"""
        try:
            return await self._client.sadd(key, *members)
        except Exception as e:
            logger.error(f"Redis SADD failed for {key}: {str(e)}")
            return 0
    
    async def smembers(self, key: str) -> set:
        """Get all set members"""
        try:
            return await self._client.smembers(key)
        except Exception as e:
            logger.error(f"Redis SMEMBERS failed for {key}: {str(e)}")
            return set()
    
    async def sismember(self, key: str, member: str) -> bool:
        """Check if member is in set"""
        try:
            return await self._client.sismember(key, member)
        except Exception as e:
            logger.error(f"Redis SISMEMBER failed for {key}: {str(e)}")
            return False
    
    # ========== Transaction Operations ==========
    
    async def pipeline(self, transaction: bool = False):
        """Get pipeline for batch operations"""
        return self._client.pipeline(transaction=transaction)
    
    # ========== Key Management ==========
    
    async def flushdb(self, async_: bool = False) -> bool:
        """Flush current database (use with caution)"""
        try:
            await self._client.flushdb(asynchronous=async_)
            return True
        except Exception as e:
            logger.error(f"Redis FLUSHDB failed: {str(e)}")
            return False
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get all keys matching pattern"""
        try:
            return await self._client.keys(pattern)
        except Exception as e:
            logger.error(f"Redis KEYS failed: {str(e)}")
            return []
    
    async def dbsize(self) -> int:
        """Get number of keys in current database"""
        try:
            return await self._client.dbsize()
        except Exception as e:
            logger.error(f"Redis DBSIZE failed: {str(e)}")
            return 0
    
    async def info(self, section: str = "default") -> Dict:
        """Get Redis server info"""
        try:
            return await self._client.info(section)
        except Exception as e:
            logger.error(f"Redis INFO failed: {str(e)}")
            return {}


# Singleton instance
redis_client = RedisClient()
