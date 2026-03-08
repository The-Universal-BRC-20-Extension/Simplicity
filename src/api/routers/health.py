from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import time
import structlog

from src.database.connection import get_db, engine
from src.services.cache_service import CacheService

logger = structlog.get_logger()
router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    """
    Health check endpoint for monitoring and load balancers

    Returns 200 OK if all systems are operational
    Returns 503 Service Unavailable if critical systems are down
    """
    start_time = time.time()
    status = {"status": "healthy", "checks": {}, "timestamp": time.time()}
    is_healthy = True

    # Check 1: Database connection
    try:
        db = next(get_db())
        db.execute(text("SELECT 1"))
        db.close()
        status["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        logger.error("Health check: Database connection failed", error=str(e))
        status["checks"]["database"] = {"status": "error", "message": str(e)}
        is_healthy = False

    # Check 2: Database pool status
    try:
        pool = engine.pool
        status["checks"]["database_pool"] = {
            "status": "ok",
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "max_overflow": engine.pool._max_overflow,
            "total_capacity": pool.size() + engine.pool._max_overflow,
        }

        # Warning if pool is >80% saturated
        total_capacity = pool.size() + engine.pool._max_overflow
        utilization = (pool.checkedout() + pool.overflow()) / total_capacity

        if utilization > 0.8:
            status["checks"]["database_pool"]["warning"] = f"Pool is {utilization*100:.1f}% saturated"
            logger.warning("Database pool saturation high", utilization=utilization)

        # Critical if pool is >95% saturated
        if utilization > 0.95:
            status["checks"]["database_pool"]["status"] = "critical"
            is_healthy = False

    except Exception as e:
        logger.error("Health check: Pool status check failed", error=str(e))
        status["checks"]["database_pool"] = {"status": "error", "message": str(e)}
        is_healthy = False

    # Check 3: Redis connection
    try:
        cache = CacheService()
        test_key = "health_check_test"
        cache.set(test_key, "ok", ttl=5)
        result = cache.get(test_key)
        cache.delete(test_key)

        if result == "ok":
            status["checks"]["redis"] = {"status": "ok"}
        else:
            status["checks"]["redis"] = {"status": "error", "message": "Redis read/write test failed"}
            is_healthy = False
    except Exception as e:
        logger.error("Health check: Redis connection failed", error=str(e))
        status["checks"]["redis"] = {"status": "error", "message": str(e)}
        # Redis is non-critical - API can work without cache
        status["checks"]["redis"]["critical"] = False

    # Check 4: Response time
    response_time = time.time() - start_time
    status["response_time_ms"] = round(response_time * 1000, 2)

    if response_time > 5.0:
        logger.warning("Health check: Slow response time", response_time_ms=status["response_time_ms"])
        status["checks"]["response_time"] = {
            "status": "warning",
            "message": f"Response time {status['response_time_ms']}ms exceeds 5000ms threshold",
        }

    # Final status
    if is_healthy:
        status["status"] = "healthy"
        return JSONResponse(content=status, status_code=200)
    else:
        status["status"] = "unhealthy"
        return JSONResponse(content=status, status_code=503)


@router.get("/ready")
def readiness_check():
    """
    Readiness check for Kubernetes/Docker orchestration

    Returns 200 if service is ready to accept traffic
    Returns 503 if service is starting up or not ready
    """
    try:
        # Quick DB check
        db = next(get_db())
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ready"}
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        return JSONResponse(content={"status": "not_ready", "error": str(e)}, status_code=503)


@router.get("/live")
def liveness_check():
    """
    Liveness check for Kubernetes/Docker orchestration

    Returns 200 if service is alive (even if not fully functional)
    Should only fail if process needs to be restarted
    """
    return {"status": "alive", "timestamp": time.time()}
