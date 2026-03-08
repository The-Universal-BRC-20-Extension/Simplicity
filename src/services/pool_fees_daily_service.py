"""
Service for managing daily pool fees aggregation.

Handles:
- Daily aggregation of fees from balance_changes
- Live calculation for last 24h
- Historical data retrieval
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from decimal import Decimal
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import structlog

from src.models.balance_change import BalanceChange
from src.models.pool_fees_daily import PoolFeesDaily
from src.models.swap_pool import SwapPool
from src.models.swap_position import SwapPosition  # Import to ensure SQLAlchemy relationship resolution
from src.models.fees_aggregation_state import FeesAggregationState

logger = structlog.get_logger()


class PoolFeesDailyService:
    """Service for daily pool fees aggregation"""

    def __init__(self, db: Session):
        self.db = db

    def get_pool_tokens(self, pool_id: str) -> Optional[tuple[str, str]]:
        """
        Get token_a and token_b for a pool_id.

        Args:
            pool_id: Canonical pool ID (e.g., "LOL-WTF")

        Returns:
            Tuple of (token_a, token_b) or None if pool not found
        """
        pool = self.db.query(SwapPool).filter_by(pool_id=pool_id).first()
        if pool:
            return (pool.token_a_ticker, pool.token_b_ticker)

        # Fallback: parse from pool_id (preserve 'y' prefix)
        from src.utils.ticker_normalization import parse_pool_id_tickers

        try:
            token_a, token_b = parse_pool_id_tickers(pool_id)
            return (token_a, token_b)
        except ValueError:
            return None

    def calculate_daily_fees(self, pool_id: str, target_date: date) -> Dict:
        """
        Calculate fees for a specific pool and date from balance_changes.

        Args:
            pool_id: Pool identifier
            target_date: Date to calculate fees for

        Returns:
            Dict with fees_token_a, fees_token_b, total_changes, last_block_height
        """
        tokens = self.get_pool_tokens(pool_id)
        if not tokens:
            logger.warning("Pool not found for daily fees calculation", pool_id=pool_id)
            return {
                "fees_token_a": Decimal("0"),
                "fees_token_b": Decimal("0"),
                "total_changes": 0,
                "last_block_height": None,
            }

        token_a, token_b = tokens

        # Import ProcessedBlock for join
        from src.models.block import ProcessedBlock

        # Date range for the target date (start and end of day in UTC)
        start_datetime = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=None)
        end_datetime = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=None)

        # Query fees for token_a using block timestamp (not created_at)
        fees_a_result = (
            self.db.query(
                func.coalesce(func.sum(BalanceChange.amount_delta), 0).label("fees"),
                func.count(BalanceChange.id).label("count"),
                func.max(BalanceChange.block_height).label("max_block"),
            )
            .select_from(BalanceChange)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                BalanceChange.ticker == token_a,
                func.date(ProcessedBlock.timestamp) == target_date,
            )
            .first()
        )

        # Query fees for token_b using block timestamp (not created_at)
        fees_b_result = (
            self.db.query(
                func.coalesce(func.sum(BalanceChange.amount_delta), 0).label("fees"),
                func.count(BalanceChange.id).label("count"),
                func.max(BalanceChange.block_height).label("max_block"),
            )
            .select_from(BalanceChange)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                BalanceChange.ticker == token_b,
                func.date(ProcessedBlock.timestamp) == target_date,
            )
            .first()
        )

        fees_a = Decimal(str(fees_a_result.fees)) if fees_a_result and fees_a_result.fees else Decimal("0")
        fees_b = Decimal(str(fees_b_result.fees)) if fees_b_result and fees_b_result.fees else Decimal("0")
        total_changes = (fees_a_result.count if fees_a_result else 0) + (fees_b_result.count if fees_b_result else 0)
        last_block = (
            max(
                fees_a_result.max_block if fees_a_result and fees_a_result.max_block else 0,
                fees_b_result.max_block if fees_b_result and fees_b_result.max_block else 0,
            )
            or None
        )

        return {
            "fees_token_a": fees_a,
            "fees_token_b": fees_b,
            "total_changes": total_changes,
            "last_block_height": last_block,
        }

    def update_daily_fees(self, pool_id: str, target_date: date) -> PoolFeesDaily:
        """
        Update or create daily fees aggregation for a pool and date.

        Args:
            pool_id: Pool identifier
            target_date: Date to update

        Returns:
            PoolFeesDaily instance
        """
        # Calculate fees for the date
        fees_data = self.calculate_daily_fees(pool_id, target_date)

        # Get or create daily record
        daily = self.db.query(PoolFeesDaily).filter_by(pool_id=pool_id, date=target_date).first()

        if daily:
            # Update existing record
            daily.fees_token_a = fees_data["fees_token_a"]
            daily.fees_token_b = fees_data["fees_token_b"]
            daily.total_changes = fees_data["total_changes"]
            daily.last_block_height = fees_data["last_block_height"]
            daily.last_updated_at = datetime.utcnow()
        else:
            # Create new record
            daily = PoolFeesDaily(
                pool_id=pool_id,
                date=target_date,
                fees_token_a=fees_data["fees_token_a"],
                fees_token_b=fees_data["fees_token_b"],
                total_changes=fees_data["total_changes"],
                last_block_height=fees_data["last_block_height"],
            )
            self.db.add(daily)

        return daily

    def _get_or_create_aggregation_state(self) -> FeesAggregationState:
        """Get or create the fees aggregation state record."""
        state = self.db.query(FeesAggregationState).first()
        if not state:
            state = FeesAggregationState(last_aggregated_block_height=0)
            self.db.add(state)
            self.db.commit()
            self.db.refresh(state)
        return state

    def update_fees_after_144_blocks(self, blocks_per_aggregation: int = 144) -> int:
        """
        Update daily fees aggregation after processing 144 blocks (~24h of Bitcoin blocks).

        Logic:
        - Get the last aggregated block height
        - Get the current last processed block height
        - If we've processed >= 144 blocks since last aggregation, aggregate fees for those blocks
        - Update the last aggregated block height

        Args:
            blocks_per_aggregation: Number of blocks to process before aggregating (default: 144)

        Returns:
            Number of pool-date combinations updated
        """
        from src.models.block import ProcessedBlock
        from sqlalchemy import desc

        # Get aggregation state
        state = self._get_or_create_aggregation_state()
        last_aggregated = state.last_aggregated_block_height

        # Get current last processed block
        last_block = self.db.query(ProcessedBlock).order_by(desc(ProcessedBlock.height)).first()
        if not last_block:
            logger.debug("No blocks processed yet")
            return 0

        current_height = last_block.height

        # Check if we've processed enough blocks
        blocks_since_last = current_height - last_aggregated
        if blocks_since_last < blocks_per_aggregation:
            logger.debug(
                "Not enough blocks processed since last aggregation",
                blocks_since_last=blocks_since_last,
                required=blocks_per_aggregation,
                last_aggregated=last_aggregated,
                current_height=current_height,
            )
            return 0

        # Calculate the range of blocks to aggregate
        # We aggregate from (last_aggregated + 1) to (last_aggregated + blocks_per_aggregation)
        # But we might have processed more than blocks_per_aggregation, so we aggregate in chunks
        start_height = last_aggregated + 1
        end_height = min(last_aggregated + blocks_per_aggregation, current_height)

        logger.info(
            "Aggregating fees for block range",
            start_height=start_height,
            end_height=end_height,
            blocks_count=end_height - start_height + 1,
            last_aggregated=last_aggregated,
            current_height=current_height,
        )

        # Get all unique dates in this block range
        dates_in_range = (
            self.db.query(func.date(ProcessedBlock.timestamp).label("block_date"))
            .filter(
                ProcessedBlock.height >= start_height,
                ProcessedBlock.height <= end_height,
                ProcessedBlock.timestamp.isnot(None),
            )
            .distinct()
            .all()
        )

        if not dates_in_range:
            logger.debug("No dates found in block range")
            # Still update the state to avoid checking the same range again
            state.last_aggregated_block_height = end_height
            self.db.commit()
            return 0

        date_list = [d.block_date for d in dates_in_range]

        # Get all unique pool_ids for these dates and blocks
        pools_by_date = (
            self.db.query(BalanceChange.pool_id, func.date(ProcessedBlock.timestamp).label("fee_date"))
            .select_from(BalanceChange)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(
                BalanceChange.pool_id.isnot(None),
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                ProcessedBlock.height >= start_height,
                ProcessedBlock.height <= end_height,
                func.date(ProcessedBlock.timestamp).in_(date_list),
            )
            .distinct()
            .all()
        )

        if not pools_by_date:
            logger.debug("No pools found for block range")
            # Still update the state
            state.last_aggregated_block_height = end_height
            self.db.commit()
            return 0

        # Group by pool_id and date
        updates_by_pool_date = {}
        for pool_id, fee_date in pools_by_date:
            if pool_id and fee_date:
                key = (pool_id, fee_date)
                updates_by_pool_date[key] = True

        logger.info(
            "Found dates to aggregate",
            total_dates=len(date_list),
            total_pool_dates=len(updates_by_pool_date),
            date_range=f"{min(date_list)} to {max(date_list)}",
            block_range=f"{start_height} to {end_height}",
        )

        # Update each pool-date combination
        updated_count = 0
        for pool_id, target_date in updates_by_pool_date.keys():
            try:
                self.update_daily_fees(pool_id, target_date)
                updated_count += 1
                if updated_count % 10 == 0:
                    logger.debug("Updating fees", progress=f"{updated_count}/{len(updates_by_pool_date)}")
            except Exception as e:
                logger.error("Failed to update daily fees", pool_id=pool_id, date=target_date, error=str(e))

        # Update the aggregation state
        state.last_aggregated_block_height = end_height
        self.db.commit()

        logger.info(
            "Updated fees aggregation",
            total_updated=updated_count,
            dates=len(date_list),
            new_last_aggregated=end_height,
        )
        return updated_count

    def update_missing_dates(self, max_days_back: int = 30) -> int:
        """
        Update all missing dates in pool_fees_daily for all pools.

        This method finds all dates that have fees in balance_changes but don't have
        a corresponding entry in pool_fees_daily, and updates them.

        Useful after reprocessing blocks to catch up on missing aggregations.

        Args:
            max_days_back: Maximum number of days to look back (default: 30)

        Returns:
            Total number of pool-date combinations updated
        """
        from src.models.block import ProcessedBlock

        # Get date range
        today = date.today()
        start_date = today - timedelta(days=max_days_back)

        # Find all pool_id + date combinations that have fees but no aggregation
        # This query finds dates with fees that don't have a pool_fees_daily entry
        missing_aggregations = (
            self.db.query(BalanceChange.pool_id, func.date(ProcessedBlock.timestamp).label("fee_date"))
            .select_from(BalanceChange)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .outerjoin(
                PoolFeesDaily,
                and_(
                    PoolFeesDaily.pool_id == BalanceChange.pool_id,
                    PoolFeesDaily.date == func.date(ProcessedBlock.timestamp),
                ),
            )
            .filter(
                BalanceChange.pool_id.isnot(None),
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                func.date(ProcessedBlock.timestamp) >= start_date,
                func.date(ProcessedBlock.timestamp) < today,  # Exclude today (not complete yet)
                PoolFeesDaily.id.is_(None),  # No aggregation exists
            )
            .distinct()
            .all()
        )

        if not missing_aggregations:
            logger.info("No missing dates to update")
            return 0

        # Group by pool_id and date
        updates_by_pool_date = {}
        for pool_id, fee_date in missing_aggregations:
            if pool_id and fee_date:
                key = (pool_id, fee_date)
                if key not in updates_by_pool_date:
                    updates_by_pool_date[key] = True

        logger.info(
            "Found missing dates to update",
            total_missing=len(updates_by_pool_date),
            date_range=f"{start_date} to {today - timedelta(days=1)}",
        )

        # Update each missing date
        updated_count = 0
        for pool_id, target_date in updates_by_pool_date.keys():
            try:
                self.update_daily_fees(pool_id, target_date)
                updated_count += 1
                if updated_count % 10 == 0:
                    logger.debug("Updating missing dates", progress=f"{updated_count}/{len(updates_by_pool_date)}")
            except Exception as e:
                logger.error("Failed to update daily fees", pool_id=pool_id, date=target_date, error=str(e))

        self.db.commit()
        logger.info(
            "Updated missing dates in pool_fees_daily",
            total_updated=updated_count,
            date_range=f"{start_date} to {today - timedelta(days=1)}",
        )
        return updated_count

    def get_live_24h_fees(self, pool_id: str) -> Dict:
        """
        Calculate live fees for the last 24 hours (from balance_changes).

        Args:
            pool_id: Pool identifier

        Returns:
            Dict with fees_token_a, fees_token_b, executions_24h
        """
        tokens = self.get_pool_tokens(pool_id)
        if not tokens:
            return {
                "fees_token_a": Decimal("0"),
                "fees_token_b": Decimal("0"),
                "executions_24h": 0,
            }

        token_a, token_b = tokens

        # Calculate 24h threshold
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        # Get current block height for 24h calculation
        from src.models.transaction import BRC20Operation
        from src.models.swap_position import SwapPosition  # Ensure models are loaded

        latest_op = self.db.query(BRC20Operation).order_by(BRC20Operation.block_height.desc()).first()
        current_block_height = latest_op.block_height if latest_op else 0
        block_height_24h = current_block_height - 144 if current_block_height >= 144 else 0

        # Fees token_a (last 24h)
        fees_a_result = (
            self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                BalanceChange.ticker == token_a,
                BalanceChange.block_height >= block_height_24h,
            )
            .scalar()
        ) or Decimal("0")

        # Fees token_b (last 24h)
        fees_b_result = (
            self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                BalanceChange.ticker == token_b,
                BalanceChange.block_height >= block_height_24h,
            )
            .scalar()
        ) or Decimal("0")

        # Executions (last 24h)
        executions = (
            self.db.query(func.count(func.distinct(BalanceChange.txid)))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                BalanceChange.txid.isnot(None),
                BalanceChange.block_height >= block_height_24h,
            )
            .scalar()
        ) or 0

        return {
            "fees_token_a": Decimal(str(fees_a_result)),
            "fees_token_b": Decimal(str(fees_b_result)),
            "executions_24h": executions,
        }

    def get_historical_fees(
        self,
        pool_id: str,
        days: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict]:
        """
        Get historical daily fees from pool_fees_daily table.

        Args:
            pool_id: Pool identifier
            days: Number of days to retrieve (default: 30). If provided, returns last N days including today if available.
            start_date: Start date for date range (inclusive). If provided with end_date, days is ignored.
            end_date: End date for date range (inclusive). If provided with start_date, days is ignored.

        Returns:
            List of daily fees records
        """
        # Determine date range
        if start_date is not None and end_date is not None:
            # Use explicit date range
            filter_start = start_date
            filter_end = end_date
        elif days is not None:
            # Use days parameter: return last N days including today if available
            # Go back (days-1) from today to get N days total (including today)
            filter_end = date.today()  # Include today if data exists in table
            filter_start = date.today() - timedelta(days=days - 1)  # days-1 because we include today
        else:
            # Default: last 30 days including today
            filter_end = date.today()
            filter_start = date.today() - timedelta(days=29)  # 30 days including today

        records = (
            self.db.query(PoolFeesDaily)
            .filter(
                PoolFeesDaily.pool_id == pool_id,
                PoolFeesDaily.date >= filter_start,
                PoolFeesDaily.date <= filter_end,
            )
            .order_by(PoolFeesDaily.date.desc())
            .all()
        )

        tokens = self.get_pool_tokens(pool_id)
        token_a, token_b = tokens if tokens else ("", "")

        result = []
        for record in records:
            result.append(
                {
                    "date": record.date.isoformat(),
                    "fees_token_a": str(record.fees_token_a),
                    "fees_token_b": str(record.fees_token_b),
                    "ticker_a": token_a,
                    "ticker_b": token_b,
                    "total_changes": record.total_changes,
                }
            )

        return result
