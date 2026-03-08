from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import time
import yaml

from src.api.routers.brc20 import router as brc20_router
from src.api.routers.mempool import router as mempool_router
from src.api.routers.validation import router as validation_router
from src.api.routers.swap import router as swap_router
from src.api.routers.wrap import router as wrap_router
from src.api.routers.curve import router as curve_router
from src.utils.logging import setup_logging, get_logger
from src.database.connection import get_db
from src.models.block import ProcessedBlock
from src.config import settings

# Import swap models to ensure SQLAlchemy relationships are resolved
from src.models.swap_position import SwapPosition  # noqa: F401
from src.models.swap_pool import SwapPool  # noqa: F401

setup_logging(
    log_level=settings.LOG_LEVEL,
    filter_stones_mint=settings.LOG_FILTER_STONES_MINT,
    filter_all_mints=settings.LOG_FILTER_ALL_MINTS,
    separate_logs=settings.LOG_SEPARATE_INDEXER_API,
    log_dir=settings.LOG_DIR or "logs",
    enable_file_logging=settings.LOG_ENABLE_FILE_LOGGING,
    max_bytes=settings.LOG_MAX_BYTES,
    backup_count=settings.LOG_BACKUP_COUNT,
)
logger = get_logger(component="api")

app = FastAPI(
    title="Simplicity - Swap API",
    description="Simplicity - Swap API",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    yaml_path = repo_root / "docs" / "api" / "openapi.yaml"

    if yaml_path.exists():
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                openapi_schema = yaml.safe_load(f)
            app.openapi_schema = openapi_schema
            return openapi_schema
        except Exception as e:
            logger.warning("Failed to load OpenAPI from YAML: %s. Falling back to auto-generation.", e)

    # Fallback: Generate from routes (original behavior)
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }

    # Apply security globally to all paths starting with /v1, except for the public health checks
    api_prefix = "/v1"
    public_paths = ["/v1/indexer/brc20/health", "/v1/validator/health"]

    for path, path_item in openapi_schema["paths"].items():
        if path.startswith(api_prefix) and path not in public_paths:
            for method in path_item:
                path_item[method]["security"] = [{"ApiKeyAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(brc20_router, tags=["BRC-20"])
app.include_router(mempool_router, tags=["Mempool"])
app.include_router(validation_router, tags=["Validation"])
app.include_router(swap_router, tags=["Swap"])
app.include_router(wrap_router, tags=["Wrap"])
app.include_router(curve_router, tags=["Curve"])


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.middleware("http")
async def log_requests(request, call_next):
    start_time = time.time()
    try:
        response = await call_next(request)
        process_time = time.time() - start_time

        # Skip logging for health checks to reduce overhead
        # Health endpoint can be called millions of times without issues
        if request.url.path not in [
            "/v1/indexer/brc20/health",
            "/health",
            "/health/concurrency",
            "/v1/validator/health",
        ]:
            logger.info(
                "Request completed",
                component="api",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                process_time=round(process_time, 3),
            )

        # Force connection close to prevent CLOSE_WAIT issues
        response.headers["Connection"] = "close"
        return response
    except Exception as e:
        logger.error(
            "Request failed",
            component="api",
            method=request.method,
            path=request.url.path,
            error=str(e),
            exc_info=True,
        )
        raise


@app.get("/")
async def root():
    return {"message": "Universal BRC-20 Indexer API SWAP Activated", "version": "2.1.0"}


@app.get("/health")
async def health():
    """Minimal health check; no DB/Redis to avoid timeouts."""
    return {"status": "ok"}


@app.get("/health/concurrency")
async def get_concurrency_health():
    try:
        db = next(get_db())

        from datetime import datetime, timedelta
        from sqlalchemy import func

        recent_conflicts = (
            db.query(ProcessedBlock).filter(ProcessedBlock.processed_at >= datetime.now() - timedelta(hours=1)).count()
        )

        duplicate_blocks = (
            db.query(ProcessedBlock)
            .filter(
                ProcessedBlock.height.in_(
                    db.query(ProcessedBlock.height)
                    .group_by(ProcessedBlock.height)
                    .having(func.count(ProcessedBlock.height) > 1)
                )
            )
            .count()
        )

        latest_block = db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()
        last_processed_height = latest_block.height if latest_block else 0

        one_hour_ago = datetime.now() - timedelta(hours=1)
        blocks_last_hour = db.query(ProcessedBlock).filter(ProcessedBlock.processed_at >= one_hour_ago).count()

        potential_reorgs = 0
        try:
            recent_blocks = db.query(ProcessedBlock).filter(ProcessedBlock.processed_at >= one_hour_ago).all()

            block_heights = [b.height for b in recent_blocks]
            if len(block_heights) != len(set(block_heights)):
                potential_reorgs = len(block_heights) - len(set(block_heights))
        except Exception:
            potential_reorgs = 0

        return {
            "status": ("healthy" if duplicate_blocks == 0 and potential_reorgs == 0 else "warning"),
            "recent_conflicts": recent_conflicts,
            "duplicate_blocks": duplicate_blocks,
            "potential_reorgs": potential_reorgs,
            "last_processed_block": last_processed_height,
            "processing_rate_blocks_per_hour": blocks_last_hour,
            "optimistic_locking_enabled": True,
            "reorg_detection_enabled": True,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8083)
