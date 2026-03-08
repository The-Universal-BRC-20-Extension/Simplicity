from pydantic import validator
from pydantic_settings import BaseSettings
from typing import Optional, Dict, Any, ClassVar


class Settings(BaseSettings):
    # Database
    DB_USER: str = "user"
    DB_PASSWORD: str = "password"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "brc20"
    DATABASE_URL: Optional[str] = None

    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        return (
            f"postgresql+psycopg2://{values.get('DB_USER')}:{values.get('DB_PASSWORD')}@"
            f"{values.get('DB_HOST')}:{values.get('DB_PORT')}/{values.get('DB_NAME')}"
        )

    # Bitcoin RPC
    BITCOIN_RPC_URL: str = "http://localhost:8332"
    BITCOIN_RPC_USER: str = "bitcoinrpc"
    BITCOIN_RPC_PASSWORD: str = "password"
    BITCOIN_RPC_COOKIE_FILE: Optional[str] = None
    # Optional: for external providers (QuickNode, Alchemy). Use header-based auth instead of Basic.
    # BITCOIN_RPC_AUTH_HEADER: "Bearer" (default) -> Authorization: Bearer <key>; "x-token" -> x-token: <key>; "api-key" -> api-key: <key>
    BITCOIN_RPC_API_KEY: Optional[str] = None
    BITCOIN_RPC_AUTH_HEADER: str = "Bearer"

    # Indexing settings
    START_BLOCK_HEIGHT: int = 895534  # Universal BRC-20 start
    BATCH_SIZE: int = 10
    MAX_REORG_DEPTH: int = 100

    # Mint validation settings
    MINT_OP_RETURN_POSITION_BLOCK_HEIGHT: int = (
        984444  # Block height when strict mint OP_RETURN position validation starts
    )

    # Marketplace template change block height
    MARKETPLACE_TRANSFER_BLOCK_HEIGHT: int = (
        901350  # Block height when new marketplace transfer template validation starts
    )

    # Emergency marketplace transfer sender fix block range
    EMERGENCY_MARKETPLACE_SENDER_START_BLOCK: Optional[int] = None  # Start block for emergency sender fix (inclusive)
    EMERGENCY_MARKETPLACE_SENDER_END_BLOCK: Optional[int] = None  # End block for emergency sender fix (inclusive)

    # Swap protocol activation heights
    SWAP_EXE_ACTIVATION_HEIGHT: int = 926480  # Block height when swap.exe operations are activated

    # STONES mint activation height
    STONES_ACTIVATION_HEIGHT: int = 925399  # Block height when STONES mint operations are activated

    # Performance
    MAX_WORKERS: int = 1  # Sequential processing
    DB_POOL_SIZE: int = 5
    QUERY_TIMEOUT: int = 30

    # Monitoring
    LOG_LEVEL: str = "INFO"
    LOG_NON_BRC20_OPERATIONS: bool = False  # Optional logging for non-BRC20 OP_RETURNs
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 60

    # Logging Configuration
    LOG_FILTER_STONES_MINT: bool = True  # Filter STONES mint logs
    LOG_FILTER_ALL_MINTS: bool = True  # Filter all mint operations
    LOG_SEPARATE_INDEXER_API: bool = True  # Separate indexer and API logs
    LOG_ENABLE_FILE_LOGGING: bool = False  # Enable file logging with rotation
    LOG_DIR: Optional[str] = None  # Directory for log files (default: logs/)
    LOG_MAX_BYTES: int = 100 * 1024 * 1024  # 100MB per log file
    LOG_BACKUP_COUNT: int = 10  # Number of rotated log files to keep

    # Error handling
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5
    STOP_ON_ERROR: bool = False  # Only stop on critical errors, not validation errors

    # API
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8083
    API_WORKERS: int = 9  # Number of Gunicorn workers for API

    # Cache Redis
    REDIS_URL: str = "redis://localhost:6380/0"
    CACHE_TTL: int = 300

    # Indexer Version
    INDEXER_VERSION: str = "1.0.0"

    LOG_MARKETPLACE_METRICS: bool = True
    VALIDATE_PROCESSING_CONSISTENCY: bool = True

    # OPI Configuration (for other OPI processors, not wrap operations)
    ENABLE_OPI: bool = True
    STOP_ON_OPI_ERROR: bool = True

    # Enabled OPIs: operation name -> processor class import path
    ENABLED_OPIS: ClassVar[Dict[str, str]] = {
        "test_opi": "src.opi.operations.test_opi.processor.TestOPIProcessor",
        "swap": "src.opi.operations.swap.processor.SwapProcessor",
    }

    # Taproot Wrap Configuration (x-only format, without 03 prefix)
    PLATFORM_PUBKEY: str = "d22eaaa259553e25fcdd2bba871702ca2c305bdf4384ce6b90db139700949fb5"

    # Wrap Protocol Constants
    WRAP_TICKER: str = "W"
    WRAP_DUST_THRESHOLD: int = 660  # satoshis
    WRAP_MAGIC_CODE: str = "W_PROOF"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
