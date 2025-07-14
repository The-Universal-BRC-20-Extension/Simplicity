from typing import ClassVar
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/ubrc20_indexer"

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

    # Marketplace validation settings
    MARKETPLACE_TRANSFER_BLOCK_HEIGHT: int = (
        901350  # Block height when new marketplace transfer template validation starts
    )

    # Performance
    MAX_WORKERS: int = 1  # Sequential processing
    DB_POOL_SIZE: int = 5
    QUERY_TIMEOUT: int = 30

    # Monitoring
    LOG_LEVEL: str = "INFO"
    LOG_NON_BRC20_OPERATIONS: bool = (
        False  # Optional debug logging for non-BRC20 OP_RETURNs
    )
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 60

    # Error handling
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5
    STOP_ON_ERROR: bool = False  # Only stop on critical errors, not validation errors

    # API
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8081

    # Cache Redis
    REDIS_URL: str = "redis://localhost:6380/0"
    CACHE_TTL: int = 300

    # OPI (OP_RETURN Indexer) Settings
    OPI_LC_URL: str = "http://localhost:3004"
    OPI_ENABLED: bool = True
    OPI_DEFAULT_TIMEOUT: int = 30
    OPI_MAX_RETRIES: int = 3
    OPI_000_SATOSHI_ADDRESS: str = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

    # Legacy validation settings
    LEGACY_VALIDATION_ENABLED: bool = True
    LEGACY_VALIDATION_TIMEOUT: int = 30
    LEGACY_VALIDATION_MAX_RETRIES: int = 3
    
    # Supply tracking settings
    SUPPLY_TRACKING_ENABLED: bool = True
    SUPPLY_UPDATE_INTERVAL: int = 300  # 5 minutes

    # Indexer Version
    INDEXER_VERSION: str = "1.0.0"

    model_config: ClassVar[SettingsConfigDict] = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
