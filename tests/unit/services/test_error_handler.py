"""
Tests for ErrorHandler service.
"""

from unittest.mock import patch

import pytest

from src.config import settings
from src.services.error_handler import ErrorHandler


class TestErrorHandler:
    """Test ErrorHandler functionality"""

    @pytest.fixture
    def error_handler(self):
        """Create ErrorHandler instance"""
        return ErrorHandler()

    def test_handle_rpc_error(self, error_handler):
        """Test handling of RPC errors"""
        with patch.object(error_handler.logger, "error") as mock_log:
            result = error_handler.handle_rpc_error(Exception("RPC timeout"), {"block": 850000})
            mock_log.assert_called_once()
            assert result is True

    def test_handle_database_error(self, error_handler):
        """Test handling of database errors"""
        with patch.object(error_handler.logger, "error") as mock_log:
            result = error_handler.handle_database_error(Exception("Connection failed"), {"query": "SELECT *"})
            mock_log.assert_called_once()
            assert result is True

    def test_handle_validation_error(self, error_handler):
        """Test handling of validation errors"""
        with patch.object(error_handler.logger, "warning") as mock_log:
            error_handler.handle_validation_error(Exception("Invalid ticker"), {"op": "deploy"})
            mock_log.assert_called_once()

    def test_should_retry(self, error_handler):
        """Test the should_retry logic"""
        assert error_handler.should_retry(1) is True
        assert error_handler.should_retry(settings.MAX_RETRIES - 1) is True
        assert error_handler.should_retry(settings.MAX_RETRIES) is False

    def test_get_retry_delay(self, error_handler):
        """Test the retry delay calculation"""
        with patch.object(error_handler.logger, "info") as mock_log:
            delay1 = error_handler.get_retry_delay(1)
            assert delay1 == settings.RETRY_DELAY
            mock_log.assert_called_with("Retrying operation", attempt=1, delay=delay1)

            delay2 = error_handler.get_retry_delay(2)
            assert delay2 == settings.RETRY_DELAY * 2
            mock_log.assert_called_with("Retrying operation", attempt=2, delay=delay2)

            delay3 = error_handler.get_retry_delay(3)
            assert delay3 == settings.RETRY_DELAY * 4
            mock_log.assert_called_with("Retrying operation", attempt=3, delay=delay3)
