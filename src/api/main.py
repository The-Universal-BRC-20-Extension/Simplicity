from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import time

from src.api.routers.brc20 import router as brc20_router
from src.api.routers.mempool import router as mempool_router
from src.utils.logging import setup_logging
from src.database.connection import get_db
from src.models.block import ProcessedBlock

setup_logging()
logger = structlog.get_logger()

app = FastAPI(
    title="Simplicity",
    description="Universal BRC-20 Indexer API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(brc20_router, tags=["BRC-20"])
app.include_router(mempool_router, tags=["Mempool"])


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
    response = await call_next(request)
    process_time = time.time() - start_time

    logger.info(
        "Request completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time=round(process_time, 3),
    )
    return response


@app.get("/")
async def root():
    return {"message": "Universal BRC-20 Indexer API", "version": "1.0.0"}


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

    uvicorn.run(app, host="127.0.0.1", port=8080)
