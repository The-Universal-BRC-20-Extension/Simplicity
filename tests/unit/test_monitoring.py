"""
Institutional-grade unit tests for src/services/monitoring.py
- 100% coverage required
- Use db_session fixture and mocks for models/logger
- Strict PEP8, flake8, and black compliance
"""

import pytest
from unittest.mock import MagicMock, patch
from src.services.monitoring import MonitoringService, HealthStatus, PerformanceMetrics


@pytest.fixture
def mock_db_session():
    return MagicMock()


@pytest.fixture
def monitoring(mock_db_session):
    return MonitoringService(mock_db_session)


# --- record_block_processed ---
def test_record_block_processed_success(monitoring):
    with patch.object(monitoring.logger, "info") as mock_info:
        monitoring.record_block_processed(100, 0.5, 10, 2, 0)
        assert monitoring._block_processing_times[-1] == 0.5
        assert monitoring._transaction_counts[-1] == 10
        assert monitoring._operation_counts[-1] == 2
        assert monitoring._error_counts[-1] == 0
        assert monitoring._consecutive_errors == 0
        mock_info.assert_called()


def test_record_block_processed_error(monitoring):
    with patch.object(monitoring.logger, "error") as mock_error:
        monitoring.record_block_processed(100, 0.5, 10, 2, 1)
        assert monitoring._consecutive_errors == 1
        mock_error.assert_not_called()  # Only called on exception


def test_record_block_processed_exception(monitoring):
    with patch.object(
        monitoring, "get_performance_metrics", side_effect=Exception("fail")
    ):
        with patch.object(monitoring.logger, "error") as mock_error:
            monitoring.record_block_processed(100, 0.5, 10, 2, 0)
            mock_error.assert_called()


# --- record_operation_processed ---
def test_record_operation_processed_valid(monitoring):
    with patch.object(monitoring.logger, "debug") as mock_debug:
        monitoring.record_operation_processed("mint", True, 0.1)
        mock_debug.assert_not_called()


def test_record_operation_processed_invalid(monitoring):
    with patch.object(monitoring.logger, "debug") as mock_debug:
        monitoring.record_operation_processed("mint", False, 0.1)
        mock_debug.assert_called()


def test_record_operation_processed_exception(monitoring):
    with patch.object(monitoring.logger, "debug", side_effect=Exception("fail")):
        with patch.object(monitoring.logger, "error") as mock_error:
            monitoring.record_operation_processed("mint", False, 0.1)
            mock_error.assert_called()


# --- record_query_time ---
def test_record_query_time_fast(monitoring):
    with patch.object(monitoring.logger, "warning") as mock_warning:
        monitoring.record_query_time("test", 0.5)
        assert monitoring._query_times[-1] == 0.5
        mock_warning.assert_not_called()


def test_record_query_time_slow(monitoring):
    with patch.object(monitoring.logger, "warning") as mock_warning:
        monitoring.record_query_time("test", 1.5)
        assert monitoring._query_times[-1] == 1.5
        mock_warning.assert_called()


def test_record_query_time_exception(monitoring):
    with patch.object(monitoring.logger, "warning", side_effect=Exception("fail")):
        with patch.object(monitoring.logger, "error") as mock_error:
            monitoring.record_query_time("test", 1.5)
            mock_error.assert_called()


# --- add_warning / add_error ---
def test_add_warning_and_error(monitoring):
    with patch.object(monitoring.logger, "warning") as mock_warning, patch.object(
        monitoring.logger, "error"
    ) as mock_error:
        monitoring.add_warning("warn", {"foo": "bar"})
        assert len(monitoring._warnings) == 1
        mock_warning.assert_called()
        monitoring.add_error("err", {"foo": "bar"})
        assert len(monitoring._errors) == 1
        mock_error.assert_called()


# --- get_health_status ---
def test_get_health_status(monitoring):
    status = monitoring.get_health_status()
    assert isinstance(status, HealthStatus)
    assert hasattr(status, "is_healthy")


# --- get_performance_metrics ---
def test_get_performance_metrics(monitoring):
    metrics = monitoring.get_performance_metrics()
    assert isinstance(metrics, PerformanceMetrics)
    assert hasattr(metrics, "blocks_per_second")


# --- get_database_metrics ---
def test_get_database_metrics(monitoring):
    with patch.object(monitoring.db, "query", return_value=MagicMock()):
        metrics = monitoring.get_database_metrics()
        assert isinstance(metrics, dict)


# --- export_metrics ---
def test_export_metrics(monitoring):
    with patch.object(
        monitoring,
        "get_performance_metrics",
        return_value=PerformanceMetrics(1, 1, 1, 1, 1, 1, 1, 1),
    ):
        with patch.object(
            monitoring,
            "get_health_status",
            return_value=HealthStatus(True, None, None, 0.0),
        ):
            metrics = monitoring.export_metrics()
            assert isinstance(metrics, dict)


# --- get_sync_status ---
def test_get_sync_status(monitoring):
    with patch.object(monitoring, "_get_sync_status", return_value={"foo": "bar"}):
        status = monitoring.get_sync_status()
        assert status == {"foo": "bar"}


# --- log_system_info ---
def test_log_system_info(monitoring):
    with patch.object(monitoring.logger, "info") as mock_info:
        monitoring.log_system_info()
        mock_info.assert_called()


# --- reset_metrics ---
def test_reset_metrics(monitoring):
    monitoring._block_processing_times.append(1)
    monitoring._transaction_counts.append(1)
    monitoring._operation_counts.append(1)
    monitoring._error_counts.append(1)
    monitoring._query_times.append(1)
    monitoring.reset_metrics()
    assert len(monitoring._block_processing_times) == 0
    assert len(monitoring._transaction_counts) == 0
    assert len(monitoring._operation_counts) == 0
    assert len(monitoring._error_counts) == 0
    assert len(monitoring._query_times) == 0
