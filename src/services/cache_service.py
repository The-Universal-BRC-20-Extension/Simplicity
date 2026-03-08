import json
import redis
import os
from typing import Optional, Any


class CacheService:
    """Redis cache service for frequent endpoints."""

    def __init__(self):
        self.redis_client = None
        try:
            # Try to use settings.REDIS_URL (dev environment)
            from src.config import settings

            if hasattr(settings, "REDIS_URL") and settings.REDIS_URL:
                try:
                    self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                    self.redis_client.ping()
                    return
                except Exception:
                    pass
        except ImportError:
            pass

        # Fallback to environment variables (prod environment)
        try:
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", 6379))
            redis_db = int(os.getenv("REDIS_DB", 0))

            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True,
            )
            self.redis_client.ping()
        except Exception:
            self.redis_client = None

    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        if not self.redis_client:
            return None
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
        except Exception:
            pass
        return None

    def set(self, key: str, value: Any, ttl: int = 60) -> bool:
        """Stocke une valeur dans le cache avec TTL"""
        if not self.redis_client:
            return False
        try:
            self.redis_client.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        if not self.redis_client:
            return False
        try:
            return bool(self.redis_client.delete(key))
        except Exception:
            return False


_cache_service = None


def generate_cache_key(prefix: str, *parts: Any) -> str:
    """Generate a cache key from prefix and parts (e.g. prefix:1_foo_3)."""
    return f"{prefix}:{'_'.join(str(p) for p in parts)}"


def get_cache_service() -> CacheService:
    """Return the cache service instance (singleton)."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service
