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

    # Performance
    MAX_WORKERS: int = 1  # Sequential processing
    DB_POOL_SIZE: int = 5
    QUERY_TIMEOUT: int = 30

    # Monitoring
    LOG_LEVEL: str = "INFO"
    LOG_NON_BRC20_OPERATIONS: bool = False  # Optional logging for non-BRC20 OP_RETURNs
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 60

    # Error handling
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5
    STOP_ON_ERROR: bool = False  # Only stop on critical errors, not validation errors

    # API
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8083

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
    OPERATOR_PUBKEY: str = "d22eaaa259553e25fcdd2bba871702ca2c305bdf4384ce6b90db139700949fb5"

    # Wrap Protocol Constants
    WRAP_TICKER: str = "W"
    WRAP_DUST_THRESHOLD: int = 660  # satoshis
    WRAP_MAGIC_CODE: str = "W_PROOF"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
