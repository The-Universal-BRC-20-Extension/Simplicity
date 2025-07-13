import time

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers.brc20 import router as brc20_router
from src.api.routers.opi import router as opi_router
from src.api.routers.agent_communication import router as agent_comm_router
from src.utils.logging import setup_logging

setup_logging()
logger = structlog.get_logger()

app = FastAPI(
    title="Universal BRC-20 Indexer API",
    description="Production-grade BRC-20 indexer with API compatibility requirements",
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
app.include_router(opi_router, tags=["OPI Framework"])  # ✅ NEW
app.include_router(agent_comm_router, tags=["Agent Communication"])  # ✅ NEW


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


if __name__ == "__main__":
    import uvicorn
    import os

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
