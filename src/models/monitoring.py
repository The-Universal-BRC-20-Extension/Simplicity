"""
Monitoring and observability service for Universal BRC-20 Extension indexer.

This service provides health monitoring, performance metrics, and observability
for the blockchain indexing process.
"""

import time
import structlog
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

from sqlalchemy.orm import Session
from sqlalchemy import func

from src.config import settings
from src.models.block import ProcessedBlock
from src.models.transaction import BRC20Operation
from src.models.balance import Balance
from src.models.deploy import Deploy


@dataclass
class HealthStatus:
    """Current health status of the indexer"""

    is_healthy: bool
    last_block_time: Optional[datetime]
    sync_status: Optional[Dict[str, Any]]
    error_rate: float
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class PerformanceMetrics:
    """Performance metrics for the indexer"""

    blocks_per_second: float
    transactions_per_second: float
    operations_per_second: float
    avg_block_processing_time: float
    avg_query_time: float
    memory_usage_mb: float
    error_rate: float
    uptime_seconds: float


class MonitoringService:
    """
    Monitor indexer health and performance.

    Provides real-time monitoring, metrics collection, and health status
    for the Universal BRC-20 indexer service.
    """

    def __init__(self, db_session: Session):
        """
        Initialize the monitoring service.

        Args:
            db_session: Database session for metrics queries
        """
        self.db = db_session
        self.logger = structlog.get_logger()

        self._start_time = time.time()
        self._block_processing_times = deque(maxlen=1000)
        self._transaction_counts = deque(maxlen=1000)
        self._operation_counts = deque(maxlen=1000)
        self._error_counts = deque(maxlen=1000)
        self._query_times = deque(maxlen=100)

        self._last_block_processed = None
        self._consecutive_errors = 0
        self._warnings = []
        self._errors = []

        self._metrics_cache = {}
        self._cache_expiry = 0
        self._cache_ttl = 30

    def record_block_processed(
        self,
        height: int,
        processing_time: float,
        tx_count: int,
        operation_count: int,
        error_count: int = 0,
    ) -> None:
        """
        Record block processing metrics.

        Args:
            height: Block height processed
            processing_time: Time taken to process block (seconds)
            tx_count: Number of transactions in block
            operation_count: Number of BRC-20 operations found
            error_count: Number of errors encountered
        """
        try:
            current_time = datetime.utcnow()

            self._block_processing_times.append(processing_time)
            self._transaction_counts.append(tx_count)
            self._operation_counts.append(operation_count)
            self._error_counts.append(error_count)
            self._last_block_processed = current_time

            if error_count == 0:
                self._consecutive_errors = 0
            else:
                self._consecutive_errors += 1

            if height % 100 == 0:
                metrics = self.get_performance_metrics()
                self.logger.info(
                    "Performance metrics",
                    height=height,
                    blocks_per_second=metrics.blocks_per_second,
                    avg_processing_time=metrics.avg_block_processing_time,
                    error_rate=metrics.error_rate,
                )

        except Exception as e:
            self.logger.error("Failed to record block metrics", error=str(e))

    def record_operation_processed(self, operation_type: str, is_valid: bool, processing_time: float = 0.0) -> None:
        """
        Record operation processing metrics.

        Args:
            operation_type: Type of operation (deploy, mint, transfer)
            is_valid: Whether operation was valid
            processing_time: Time taken to process operation
        """
        try:
            if not is_valid:
                self.logger.debug(
                    "Invalid operation processed",
                    operation_type=operation_type,
                    processing_time=processing_time,
                )

        except Exception as e:
            self.logger.error("Failed to record operation metrics", error=str(e))

    def record_query_time(self, query_type: str, execution_time: float) -> None:
        """
        Record database query execution time.

        Args:
            query_type: Type of query executed
            execution_time: Time taken to execute query (seconds)
        """
        try:
            self._query_times.append(execution_time)

            if execution_time > 1.0:
                self.logger.warning(
                    "Slow query detected",
                    query_type=query_type,
                    execution_time=execution_time,
                )

        except Exception as e:
            self.logger.error("Failed to record query time", error=str(e))

    def add_warning(self, message: str, context: Dict[str, Any] = None) -> None:
        """
        Add a warning to the monitoring system.

        Args:
            message: Warning message
            context: Additional context information
        """
        warning_entry = {
            "timestamp": datetime.utcnow(),
            "message": message,
            "context": context or {},
        }

        self._warnings.append(warning_entry)

        if len(self._warnings) > 100:
            self._warnings = self._warnings[-100:]

        self.logger.warning("Monitoring warning", message=message, context=context)

    def add_error(self, message: str, context: Dict[str, Any] = None) -> None:
        """
        Add an error to the monitoring system.

        Args:
            message: Error message
            context: Additional context information
        """
        error_entry = {
            "timestamp": datetime.utcnow(),
            "message": message,
            "context": context or {},
        }

        self._errors.append(error_entry)

        if len(self._errors) > 100:
            self._errors = self._errors[-100:]

        self.logger.error("Monitoring error", message=message, context=context)

    def get_health_status(self) -> HealthStatus:
        """
        Get current health status.

        Returns:
            HealthStatus with current system health
        """
        try:
            total_blocks = len(self._block_processing_times)
            total_errors = sum(self._error_counts) if self._error_counts else 0
            error_rate = (total_errors / total_blocks) if total_blocks > 0 else 0.0

            is_healthy = True
            warnings = []
            errors = []

            if self._last_block_processed:
                time_since_last_block = datetime.utcnow() - self._last_block_processed
                if time_since_last_block > timedelta(minutes=10):
                    is_healthy = False
                    errors.append(f"No blocks processed in {time_since_last_block}")
                elif time_since_last_block > timedelta(minutes=5):
                    warnings.append(f"No blocks processed in {time_since_last_block}")

            if error_rate > 0.1:
                is_healthy = False
                errors.append(f"High error rate: {error_rate:.2%}")
            elif error_rate > 0.05:
                warnings.append(f"Elevated error rate: {error_rate:.2%}")

            if self._consecutive_errors > 10:
                is_healthy = False
                errors.append(f"Too many consecutive errors: {self._consecutive_errors}")
            elif self._consecutive_errors > 5:
                warnings.append(f"Multiple consecutive errors: {self._consecutive_errors}")

            if self._block_processing_times:
                recent_avg = sum(list(self._block_processing_times)[-10:]) / min(10, len(self._block_processing_times))
                overall_avg = sum(self._block_processing_times) / len(self._block_processing_times)

                if recent_avg > overall_avg * 2:
                    warnings.append(f"Performance degradation detected: {recent_avg:.2f}s vs {overall_avg:.2f}s avg")

            sync_status = self._get_sync_status()

            return HealthStatus(
                is_healthy=is_healthy,
                last_block_time=self._last_block_processed,
                sync_status=sync_status,
                error_rate=error_rate,
                warnings=[w["message"] for w in self._warnings[-10:]] + warnings,
                errors=[e["message"] for e in self._errors[-10:]] + errors,
            )

        except Exception as e:
            self.logger.error("Failed to get health status", error=str(e))
            return HealthStatus(
                is_healthy=False,
                last_block_time=None,
                sync_status=None,
                error_rate=1.0,
                warnings=[],
                errors=[f"Health check failed: {str(e)}"],
            )

    def get_performance_metrics(self) -> PerformanceMetrics:
        """
        Get current performance metrics.

        Returns:
            PerformanceMetrics with current performance data
        """
        try:
            current_time = time.time()
            if current_time < self._cache_expiry and self._metrics_cache:
                return self._metrics_cache

            uptime = current_time - self._start_time

            blocks_processed = len(self._block_processing_times)
            blocks_per_second = blocks_processed / uptime if uptime > 0 else 0.0

            total_transactions = sum(self._transaction_counts) if self._transaction_counts else 0
            transactions_per_second = total_transactions / uptime if uptime > 0 else 0.0

            total_operations = sum(self._operation_counts) if self._operation_counts else 0
            operations_per_second = total_operations / uptime if uptime > 0 else 0.0

            avg_block_time = (
                (sum(self._block_processing_times) / len(self._block_processing_times))
                if self._block_processing_times
                else 0.0
            )
            avg_query_time = (sum(self._query_times) / len(self._query_times)) if self._query_times else 0.0

            total_errors = sum(self._error_counts) if self._error_counts else 0
            error_rate = (total_errors / blocks_processed) if blocks_processed > 0 else 0.0

            memory_usage_mb = 0.0

            metrics = PerformanceMetrics(
                blocks_per_second=blocks_per_second,
                transactions_per_second=transactions_per_second,
                operations_per_second=operations_per_second,
                avg_block_processing_time=avg_block_time,
                avg_query_time=avg_query_time,
                memory_usage_mb=memory_usage_mb,
                error_rate=error_rate,
                uptime_seconds=uptime,
            )

            self._metrics_cache = metrics
            self._cache_expiry = current_time + self._cache_ttl

            return metrics

        except Exception as e:
            self.logger.error("Failed to get performance metrics", error=str(e))
            return PerformanceMetrics(
                blocks_per_second=0.0,
                transactions_per_second=0.0,
                operations_per_second=0.0,
                avg_block_processing_time=0.0,
                avg_query_time=0.0,
                memory_usage_mb=0.0,
                error_rate=1.0,
                uptime_seconds=time.time() - self._start_time,
            )

    def get_database_metrics(self) -> Dict[str, Any]:
        """
        Get database-related metrics.

        Returns:
            Dictionary with database metrics
        """
        try:
            start_time = time.time()

            total_blocks = self.db.query(ProcessedBlock).count()
            total_operations = self.db.query(BRC20Operation).count()
            valid_operations = self.db.query(BRC20Operation).filter_by(is_valid=True).count()
            total_balances = self.db.query(Balance).count()
            total_deploys = self.db.query(Deploy).count()

            latest_block = self.db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()

            operation_counts = (
                self.db.query(BRC20Operation.operation, func.count(BRC20Operation.id))
                .filter_by(is_valid=True)
                .group_by(BRC20Operation.operation)
                .all()
            )

            query_time = time.time() - start_time
            self.record_query_time("database_metrics", query_time)

            return {
                "total_blocks_processed": total_blocks,
                "total_operations": total_operations,
                "valid_operations": valid_operations,
                "invalid_operations": total_operations - valid_operations,
                "total_balances": total_balances,
                "total_deploys": total_deploys,
                "latest_block_height": latest_block.height if latest_block else 0,
                "latest_block_hash": latest_block.block_hash if latest_block else None,
                "latest_block_time": (latest_block.processed_at if latest_block else None),
                "operation_breakdown": dict(operation_counts),
                "query_time": query_time,
            }

        except Exception as e:
            self.logger.error("Failed to get database metrics", error=str(e))
            return {
                "error": str(e),
                "total_blocks_processed": 0,
                "total_operations": 0,
                "valid_operations": 0,
                "invalid_operations": 0,
            }

    def export_metrics(self) -> Dict[str, Any]:
        """
        Export metrics for external monitoring systems.

        Returns:
            Dictionary with all metrics in a standardized format
        """
        try:
            health = self.get_health_status()
            performance = self.get_performance_metrics()
            database = self.get_database_metrics()

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "health": {
                    "is_healthy": health.is_healthy,
                    "last_block_time": (health.last_block_time.isoformat() if health.last_block_time else None),
                    "error_rate": health.error_rate,
                    "warning_count": len(health.warnings),
                    "error_count": len(health.errors),
                },
                "performance": {
                    "blocks_per_second": performance.blocks_per_second,
                    "transactions_per_second": performance.transactions_per_second,
                    "operations_per_second": performance.operations_per_second,
                    "avg_block_processing_time": performance.avg_block_processing_time,
                    "avg_query_time": performance.avg_query_time,
                    "uptime_seconds": performance.uptime_seconds,
                },
                "database": database,
                "config": {
                    "start_block_height": settings.START_BLOCK_HEIGHT,
                    "batch_size": settings.BATCH_SIZE,
                    "max_reorg_depth": settings.MAX_REORG_DEPTH,
                },
            }

        except Exception as e:
            self.logger.error("Failed to export metrics", error=str(e))
            return {"timestamp": datetime.utcnow().isoformat(), "error": str(e)}

    def get_sync_status(self) -> Optional[Dict[str, Any]]:
        """Get synchronization status from database"""
        return self._get_sync_status()

    def _get_sync_status(self) -> Optional[Dict[str, Any]]:
        """Get synchronization status from database"""
        try:
            latest_block = self.db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()

            if not latest_block:
                return None

            return {
                "last_processed_height": latest_block.height,
                "last_processed_hash": latest_block.block_hash,
                "last_processed_time": latest_block.processed_at.isoformat(),
                "blocks_processed": self.db.query(ProcessedBlock).count(),
            }

        except Exception as e:
            self.logger.error("Failed to get sync status", error=str(e))
            return None

    def log_system_info(self) -> None:
        """Log current system information"""
        try:
            health = self.get_health_status()
            performance = self.get_performance_metrics()

            self.logger.info(
                "System status report",
                is_healthy=health.is_healthy,
                blocks_per_second=performance.blocks_per_second,
                error_rate=performance.error_rate,
                uptime_hours=performance.uptime_seconds / 3600,
                warnings=len(health.warnings),
                errors=len(health.errors),
            )

        except Exception as e:
            self.logger.error("Failed to log system info", error=str(e))

    def reset_metrics(self) -> None:
        """Reset all metrics"""
        try:
            self._start_time = time.time()
            self._block_processing_times.clear()
            self._transaction_counts.clear()
            self._operation_counts.clear()
            self._error_counts.clear()
            self._query_times.clear()
            self._last_block_processed = None
            self._consecutive_errors = 0
            self._warnings.clear()
            self._errors.clear()
            self._metrics_cache.clear()
            self._cache_expiry = 0

            self.logger.info("Metrics reset")

        except Exception as e:
            self.logger.error("Failed to reset metrics", error=str(e))
