import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.connection import get_db
from src.models.base import Base

# Use PostgreSQL when DATABASE_URL or TEST_DATABASE_URL is set and not SQLite; otherwise SQLite
# TEST_DATABASE_URL overrides DATABASE_URL when running pytest (e.g. local docker postgres on 5433)
_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
if _DATABASE_URL and "sqlite" not in _DATABASE_URL.lower():
    TEST_DATABASE_URL = _DATABASE_URL
    USE_POSTGRES = True
else:
    TEST_DATABASE_URL = "sqlite:///./test.db"
    USE_POSTGRES = False

if USE_POSTGRES:
    engine = create_engine(TEST_DATABASE_URL)
else:
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def _alembic_upgrade_head(database_url: str) -> None:
    """Run Alembic migrations to head (PostgreSQL only)."""
    from alembic import command
    from alembic.config import Config
    import pathlib
    from sqlalchemy.exc import ProgrammingError

    cfg = Config()
    cfg.set_main_option("script_location", str(pathlib.Path(__file__).parents[1] / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    try:
        command.upgrade(cfg, "head")
    except ProgrammingError as e:
        msg = str(getattr(e, "orig", e))
        if "already exists" in msg or (hasattr(e, "orig") and getattr(e.orig, "pgcode", None) == "42P07"):
            command.stamp(cfg, "head")
        else:
            raise


@pytest.fixture(scope="session")
def _ensure_postgres_schema():
    """Run Alembic migrations when using PostgreSQL."""
    if USE_POSTGRES:
        _alembic_upgrade_head(TEST_DATABASE_URL)
    yield


def _truncate_all_tables(session):
    """Truncate all tables for PostgreSQL (preserves schema and triggers)."""
    if not USE_POSTGRES:
        return
    tables = [t.name for t in Base.metadata.sorted_tables]
    if tables:
        session.execute(text("TRUNCATE {} RESTART IDENTITY CASCADE".format(", ".join(tables))))
        session.commit()


@pytest.fixture
def db_session(_ensure_postgres_schema):
    """Provide a database session. PostgreSQL: truncate before each test. SQLite: create_all/drop_all."""
    if USE_POSTGRES:
        connection = engine.connect()
        Session = sessionmaker(bind=connection)
        session = Session()
        try:
            _truncate_all_tables(session)
            yield session
        finally:
            session.close()
            connection.close()
    else:
        Base.metadata.create_all(bind=engine)
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True, scope="session")
def configure_logging():
    """Configure logging for tests to use standard logging instead of JSON."""
    import logging
    import structlog

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
    )
    root_logger = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


@pytest.fixture
def client(db_session):
    with TestClient(app) as c:
        yield c
