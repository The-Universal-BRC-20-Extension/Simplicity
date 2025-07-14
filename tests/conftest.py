import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import threading
import sqlite3
import re
import os
import time
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import threading
import sqlite3
import re
import subprocess

from src.api.main import app
from src.database.connection import get_db
from src.utils.logging import setup_logging
from src.models.base import Base

# Import all models to ensure all tables are created
from src.models.balance import Balance
from src.models.block import ProcessedBlock
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.models.opi_operation import OPIOperation
from src.models.opi_configuration import OPIConfiguration
from src.models.legacy_token import LegacyToken

# Global test session storage
_test_db_session = None

def override_get_db():
    """Override the get_db dependency to use test database session"""
    global _test_db_session
    if _test_db_session is not None:
        yield _test_db_session
    else:
        # Fallback to production database if no test session is set
        from src.database.connection import SessionLocal
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

# Override the get_db dependency
app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope='session', autouse=True)
def cleanup_docker_containers():
    """Ensure Docker containers are cleaned up after test session"""
    yield
    # Cleanup after all tests complete
    try:
        # Stop all test PostgreSQL containers
        result = subprocess.run([
            'docker', 'ps', '-q', '--filter', 'name=pytest.*test-postgres'
        ], capture_output=True, text=True, check=False)
        
        if result.stdout.strip():
            container_ids = result.stdout.strip().split('\n')
            for container_id in container_ids:
                if container_id:
                    subprocess.run(['docker', 'stop', container_id], check=False)
                    subprocess.run(['docker', 'rm', container_id], check=False)
    except Exception:
        pass  # Ignore cleanup errors

# Register REGEXP for SQLite (needed for SQLAlchemy .op('regexp') in tests)
def regexp(expr, item):
    if item is None:
        return False
    reg = re.compile(expr)
    return reg.match(str(item)) is not None

# Patch SQLAlchemy engine to register REGEXP on each connection
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def sqlite_regexp(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function("regexp", 2, regexp)


@pytest.fixture(autouse=True, scope="session")
def configure_logging():
    setup_logging()


@pytest.fixture(scope='session')
def docker_compose_file(pytestconfig):
    # Path to your docker-compose.test.yml
    return str(pytestconfig.rootpath / "docker-compose.test.yml")

@pytest.fixture(scope='session')
def postgres_service(docker_services):
    """Ensure that PostgreSQL service is up and responsive."""
    # Use container port 5432 for port lookup
    port = docker_services.port_for('test-postgres', 5432)
    def is_responsive():
        import psycopg2
        try:
            conn = psycopg2.connect(
                dbname="ubrc20_test",
                user="test_user",
                password="test_pass",
                host="localhost",
                port=port,
            )
            conn.close()
            return True
        except Exception:
            return False
    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=1.0,
        check=is_responsive,
    )
    return f"postgresql://test_user:test_pass@localhost:{port}/ubrc20_test"

@pytest.fixture(params=["postgresql"])  # Only use PostgreSQL to avoid SQLite threading issues
def db_engine(request, postgres_service):
    """Create database engine for testing."""
    # Use PostgreSQL for testing (avoid SQLite threading issues)
    engine = create_engine(postgres_service, echo=False)
    
    # Clean up existing tables to ensure fresh database
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    
    # Create all tables using SQLAlchemy (not Alembic)
    Base.metadata.create_all(engine)
    return engine

@pytest.fixture
def db_session(db_engine):
    """Create database session for testing."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = SessionLocal()
    
    # Set the global test session for API endpoints
    global _test_db_session
    _test_db_session = db
    
    try:
        yield db
    finally:
        db.close()
        _test_db_session = None
        Base.metadata.drop_all(bind=db_engine)


@pytest.fixture
def client(db_session):
    # Ensure the session is set before creating the TestClient
    with TestClient(app) as c:
        yield c


# ===== REAL OBJECT TESTING FIXTURES =====

@pytest.fixture
def real_legacy_service():
    """Real LegacyTokenService for integration testing"""
    from src.services.legacy_token_service import LegacyTokenService
    return LegacyTokenService()


@pytest.fixture
def real_supply_service(db_session):
    """Real TokenSupplyService for integration testing"""
    from src.services.token_supply_service import TokenSupplyService
    return TokenSupplyService(db_session)


@pytest.fixture
def real_validator(db_session, real_legacy_service, real_supply_service):
    """Real BRC20Validator with real services"""
    from src.services.validator import BRC20Validator
    return BRC20Validator(db_session, real_legacy_service)


@pytest.fixture
def real_processor(db_session, mock_bitcoin_rpc, real_validator):
    """Real BRC20Processor with real validator"""
    from src.services.processor import BRC20Processor
    processor = BRC20Processor(db_session, mock_bitcoin_rpc)
    processor.validator = real_validator
    return processor


@pytest.fixture
def real_processor_with_validation(db_session, mock_bitcoin_rpc):
    """Real processor with real validation for integration testing"""
    from src.services.processor import BRC20Processor
    from src.services.validator import BRC20Validator
    from src.services.legacy_token_service import LegacyTokenService
    from src.services.token_supply_service import TokenSupplyService
    
    legacy_service = LegacyTokenService()
    supply_service = TokenSupplyService(db_session)
    validator = BRC20Validator(db_session, legacy_service)
    
    processor = BRC20Processor(db_session, mock_bitcoin_rpc)
    processor.validator = validator
    return processor


@pytest.fixture
def mock_bitcoin_rpc():
    """Mock BitcoinRPCService for testing"""
    from unittest.mock import Mock
    from src.services.bitcoin_rpc import BitcoinRPCService
    return Mock(spec=BitcoinRPCService)


# ===== TEST DATA GENERATORS =====

@pytest.fixture
def unique_ticker_generator():
    """Generate unique tickers for testing to avoid conflicts"""
    import time
    import random
    
    def generate_ticker(prefix="GAFQ"):
        timestamp = int(time.time() * 1000)
        random_suffix = random.randint(1000, 9999)
        return f"{prefix}{timestamp}{random_suffix}"
    
    return generate_ticker


@pytest.fixture
def test_tx_data():
    """Standard test transaction data"""
    return {
        "txid": "test_txid_1234567890123456789012345678901234567890123456789012345678901234",
        "block_height": 800000,
        "block_hash": "test_block_hash_1234567890123456789012345678901234567890123456789012345678901234",
        "vin": [{"txid": "prev_txid", "vout": 0}],
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "type": "pubkeyhash",
                    "addresses": ["1TestAddress1234567890123456789012345678901234567890"]
                }
            }
        ]
    }
