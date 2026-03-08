"""
Background job service for updating pool_fees_daily aggregation.

This service runs as a background thread and updates the daily fees aggregation
periodically (every hour) to catch up on missing dates, especially after reprocessing.
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Optional
import structlog

from src.database.connection import SessionLocal
from src.services.pool_fees_daily_service import PoolFeesDailyService

logger = structlog.get_logger()


class DailyFeesJob:
    """
    Background job that updates pool_fees_daily aggregation periodically.

    Runs every hour to:
    1. Update yesterday's fees (if it's a new day)
    2. Catch up on any missing dates (useful after reprocessing)

    Runs as a daemon thread so it doesn't prevent the main process from exiting.
    """

    def __init__(self, run_immediately: bool = True, interval_hours: float = 1.0):
        """
        Initialize the daily fees job.

        Args:
            run_immediately: If True, run the job immediately on start. Otherwise, wait for first interval.
            interval_hours: Interval between job runs in hours (default: 1.0 = every hour)
        """
        self.run_immediately = run_immediately
        self.interval_hours = interval_hours
        self.interval_seconds = interval_hours * 3600
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_run: Optional[datetime] = None

    def _run_job(self):
        """Execute the daily fees update job."""
        db = SessionLocal()
        try:
            logger.info("Starting daily fees aggregation job")
            svc = PoolFeesDailyService(db)

            # 1. Update fees after processing 144 blocks (~24h of Bitcoin blocks)
            blocks_updated = svc.update_fees_after_144_blocks(blocks_per_aggregation=144)

            # 2. Update any missing dates (catches up after reprocessing)
            # Look back up to 30 days for missing aggregations
            missing_updated = svc.update_missing_dates(max_days_back=30)

            self._last_run = datetime.utcnow()
            logger.info(
                "Daily fees aggregation job completed",
                blocks_updated=blocks_updated,
                missing_dates_updated=missing_updated,
                last_run=self._last_run.isoformat(),
            )
        except Exception as e:
            logger.error("Daily fees aggregation job failed", error=str(e), exc_info=True)
        finally:
            db.close()

    def _worker(self):
        """Background worker thread that runs the job periodically."""
        logger.info(
            "Daily fees job thread started", interval_hours=self.interval_hours, run_immediately=self.run_immediately
        )

        # Run immediately on first start if requested
        if self.run_immediately:
            if not self._stop_event.is_set():
                self._run_job()

        while not self._stop_event.is_set():
            try:
                # Wait for the interval (checking stop event every minute)
                wait_seconds = self.interval_seconds
                while wait_seconds > 0 and not self._stop_event.is_set():
                    sleep_time = min(60.0, wait_seconds)  # Check every minute
                    if self._stop_event.wait(timeout=sleep_time):
                        break
                    wait_seconds -= sleep_time

                if not self._stop_event.is_set():
                    # Run the job
                    self._run_job()

            except Exception as e:
                logger.error("Error in daily fees job worker", error=str(e), exc_info=True)
                # Wait 1 hour before retrying on error
                if not self._stop_event.wait(timeout=3600):
                    continue
                else:
                    break

        logger.info("Daily fees job thread stopped")

    def start(self):
        """Start the background job thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Daily fees job thread is already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="DailyFeesJob")
        self._thread.start()
        logger.info("Daily fees job thread started")

    def stop(self):
        """Stop the background job thread."""
        if self._thread is None or not self._thread.is_alive():
            return

        logger.info("Stopping daily fees job thread")
        self._stop_event.set()
        self._thread.join(timeout=5.0)

        if self._thread.is_alive():
            logger.warning("Daily fees job thread did not stop within timeout")
        else:
            logger.info("Daily fees job thread stopped")

    def is_running(self) -> bool:
        """Check if the job thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def get_last_run(self) -> Optional[datetime]:
        """Get the last time the job ran."""
        return self._last_run
