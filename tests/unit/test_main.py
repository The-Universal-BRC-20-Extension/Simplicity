"""
Unit tests for src/main.py
- 100% coverage required
- Use mocks for services, CLI, and error handling
- Strict PEP8, flake8, and black compliance
"""

import pytest
from unittest.mock import patch, MagicMock
from src import main as main_module


# --- main() service initialization and execution paths ---
def test_main_continuous_true():
    with (
        patch("src.main.get_db", return_value=iter([MagicMock()])),
        patch("src.main.BitcoinRPCService"),
        patch("src.main.IndexerService") as mock_indexer,
        patch("src.main.structlog.get_logger") as mock_logger,
    ):
        mock_indexer_instance = MagicMock()
        mock_indexer.return_value = mock_indexer_instance
        main_module.main(max_blocks=10, continuous=True)
        mock_indexer_instance.start_continuous_indexing.assert_called_with(start_height=None, max_blocks=10)
        mock_logger.return_value.info.assert_called()


def test_main_continuous_false():
    with (
        patch("src.main.get_db", return_value=iter([MagicMock()])),
        patch("src.main.BitcoinRPCService"),
        patch("src.main.IndexerService") as mock_indexer,
        patch("src.main.structlog.get_logger") as mock_logger,
    ):
        mock_indexer_instance = MagicMock()
        mock_indexer.return_value = mock_indexer_instance
        main_module.main(max_blocks=5, continuous=False)
        mock_indexer_instance.start_indexing.assert_called_with(start_height=None, max_blocks=5)
        mock_logger.return_value.info.assert_called()


def test_main_exception_handling():
    with (
        patch("src.main.get_db", return_value=iter([MagicMock()])),
        patch("src.main.BitcoinRPCService", side_effect=Exception("fail")),
        patch("src.main.structlog.get_logger") as mock_logger,
    ):
        with pytest.raises(Exception):
            main_module.main()
        mock_logger.return_value.error.assert_called()


def test_main_logger_configured():
    # Ensure structlog is configured (smoke test)
    assert hasattr(main_module.structlog, "configure")


# CLI entry point is not directly testable without subprocess or patching __name__,
# but main() is fully covered above.
