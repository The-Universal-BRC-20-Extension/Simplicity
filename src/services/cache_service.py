import redis
import json
import structlog
from typing import Optional, Any
import os

logger = structlog.get_logger()


class CacheService:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0)),
            decode_responses=True,
        )

    def get(self, key: str) -> Optional[Any]:
        """Get cached value"""
        try:
            cached = self.redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.error("Cache get failed", key=key, error=str(e))
        return None

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set cached value with TTL"""
        try:
            return self.redis_client.setex(key, ttl, json.dumps(value, default=str))
        except Exception as e:
            logger.error("Cache set failed", key=key, error=str(e))
            return False

    def delete(self, key: str) -> bool:
        """Delete cached value"""
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            logger.error("Cache delete failed", key=key, error=str(e))
            return False

    def generate_key(self, prefix: str, *args) -> str:
        """Generate cache key"""
        return f"{prefix}:{'_'.join(str(arg) for arg in args)}"
