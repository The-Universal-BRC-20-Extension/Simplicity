from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import Dict, List, Optional
from decimal import Decimal
import structlog

from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.transaction import BRC20Operation
from src.models.block import ProcessedBlock
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.curve import CurveConstitution, CurveUserInfo
from src.utils.amounts import compare_amounts
from src.api.models import Op

logger = structlog.get_logger()


class BRC20CalculationService:
    """Calculate statistics for BRC-20 tickers"""

    def __init__(self, db_session: Session):
        self.db = db_session

    def get_all_tickers_with_stats(self, start: int = 0, size: int = 50) -> Dict:
        try:
            query = self.db.query(Deploy).order_by(Deploy.deploy_height.desc())
            total = query.count()
            deploys = query.offset(start).limit(size).all()

            # Optimize: Use batch queries instead of N+1 queries for better performance
            if len(deploys) > 10:
                ticker_data = self._calculate_ticker_stats_batch(deploys)
            else:
                # For small batches, use individual queries (less overhead)
                ticker_data = []
                for deploy in deploys:
                    stats = self._calculate_ticker_stats(deploy)
                    if stats:
                        ticker_data.append(stats)

            return {"total": total, "start": start, "size": size, "data": ticker_data}
        except Exception as e:
            logger.error("Failed to get tickers", error=str(e))
            raise

    def get_ticker_stats(self, ticker: str) -> Optional[Dict]:
        try:
            normalized_ticker = ticker.upper()

            deploy = self.db.query(Deploy).filter(Deploy.ticker == normalized_ticker).first()

            if not deploy:
                return None

            return self._calculate_ticker_stats(deploy)

        except Exception as e:
            logger.error("Failed to get ticker stats", ticker=ticker, error=str(e))
            raise

    def _calculate_ticker_stats(self, deploy: Deploy) -> Dict:
        # Calculate total minted from mint operations (for accurate minted count)
        # Include "mint_stones" in the query to count STONES mints
        total_minted = (
            self.db.query(func.coalesce(func.sum(BRC20Operation.amount), 0))
            .filter(
                BRC20Operation.ticker == deploy.ticker,
                BRC20Operation.operation.in_(["mint", "mint_stones"]),
                BRC20Operation.is_valid == True,
            )
            .scalar()
            or 0
        )

        # Determine if this is a special token (Wrap or STONES)
        # Wrap: ticker == "W" or (max_supply == 0 AND limit_per_op == 0)
        # STONES: ticker == "STONES" or (max_supply == 0 AND limit_per_op == 1)
        is_wrap_token = deploy.ticker == "W" or (deploy.max_supply == 0 and deploy.limit_per_op == 0)
        is_stones_token = deploy.ticker == "STONES" or (
            deploy.max_supply == 0 and deploy.limit_per_op == 1 and not is_wrap_token
        )
        is_special_token = is_wrap_token or is_stones_token

        # Calculate current_supply based on token type
        if is_special_token:
            # For special tokens (W, STONES), use sum of balances
            current_supply = (
                self.db.query(func.coalesce(func.sum(Balance.balance), 0))
                .filter(Balance.ticker == deploy.ticker, Balance.balance != 0)
                .scalar()
                or 0
            )
        else:
            # For normal BRC-20 tokens, use total_minted
            # If total_minted = max_supply, then current_supply = max_supply
            from src.utils.amounts import compare_amounts

            if compare_amounts(str(total_minted), deploy.max_supply) >= 0:
                # Fully minted: current_supply = max_supply
                current_supply = float(deploy.max_supply)
            else:
                # Not fully minted: current_supply = total_minted
                current_supply = float(total_minted)

        holder_count = self.db.query(Balance).filter(Balance.ticker == deploy.ticker, Balance.balance != 0).count()

        # Calculate total locked in active swap positions
        # amount_locked represents the amount of src_ticker that is locked
        # So we only need to sum positions where src_ticker = deploy.ticker
        total_locked = (
            self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
            .filter(SwapPosition.src_ticker == deploy.ticker, SwapPosition.status == "active")
            .scalar()
            or 0
        )

        # Include staked WTF in Curve if this ticker is staking_ticker
        # Avoid infinite loop on yTokens (do not process tickers starting with 'y')
        curve_staked = Decimal("0")
        if not deploy.ticker.startswith("y"):  # Éviter boucle infinie sur yTokens
            curve_staked_result = (
                self.db.query(func.coalesce(func.sum(CurveConstitution.total_staked), 0))
                .filter(CurveConstitution.staking_ticker == deploy.ticker)
                .scalar()
            )
            curve_staked = Decimal(str(curve_staked_result)) if curve_staked_result else Decimal("0")

        total_locked = float(total_locked) + float(curve_staked)
        locked_in_curve = float(curve_staked)

        # Use total_minted for is_completed check (not current_supply which may include excess)
        from src.utils.amounts import compare_amounts

        is_completed = compare_amounts(str(total_minted), deploy.max_supply) >= 0

        # Calculate circulating supply: current_supply - total_locked
        circulating_supply = float(current_supply) - total_locked

        # Ensure circulating_supply is not negative
        circulating_supply = max(0, circulating_supply)

        # Check if this ticker is a Curve reward token (OPI-2)
        is_curve = (
            self.db.query(CurveConstitution).filter(CurveConstitution.ticker == deploy.ticker).first() is not None
        )

        # For Curve reward tokens, they are minted via swap.exe (claim), not via standard mint operations
        # Therefore, use sum of balances for minted and current_supply
        if is_curve:
            # Calculate current_supply from balances (Curve tokens are minted via swap.exe)
            current_supply_curve = (
                self.db.query(func.coalesce(func.sum(Balance.balance), 0))
                .filter(Balance.ticker == deploy.ticker, Balance.balance != 0)
                .scalar()
                or 0
            )
            # For Curve tokens: minted = current_supply (sum of balances)
            total_minted = float(current_supply_curve)
            current_supply = float(current_supply_curve)
            # Curve reward tokens are not locked in swap positions, they are distributed
            # circulating_supply = current_supply (all tokens are in circulation)
            circulating_supply = float(current_supply_curve)
            # is_completed: Curve tokens are always "fully minted" in the sense that they're algorithmically emitted
            # But we check if current_supply >= max_supply for display purposes
            is_completed = compare_amounts(str(current_supply_curve), deploy.max_supply) >= 0

        return {
            "tick": deploy.ticker,
            "max": deploy.max_supply,
            "max_supply": deploy.max_supply,
            "remaining_supply": str(deploy.remaining_supply) if deploy.remaining_supply is not None else None,
            "limit": deploy.limit_per_op,
            "minted": str(total_minted),  # For Curve: sum of balances. For normal tokens: total_minted from operations
            "current_supply": str(
                current_supply
            ),  # For Curve: sum of balances. For normal tokens: total_minted (or max_supply if fully minted). For special tokens: sum of balances
            "total_locked": str(total_locked),  # Total locked in active swap positions + Curve staking
            "locked_in_curve": str(locked_in_curve),  # Amount staked in Curve (for staking_ticker tokens)
            "circulating_supply": str(circulating_supply),  # Tokens available on market (not locked)
            "holders": holder_count,
            "deploy_txid": deploy.deploy_txid,
            "deploy_height": deploy.deploy_height,
            "deploy_time": int(deploy.deploy_timestamp.timestamp()),
            "deployer": deploy.deployer_address or "",
            "is_completed": is_completed,
            "decimals": 9,
            "is_curve": is_curve,  # OPI-2 Curve Extension
        }

    def _calculate_ticker_stats_batch(self, deploys: List[Deploy]) -> List[Dict]:
        """Optimized batch version that reduces N+1 queries to ~5 batch queries"""
        from src.utils.amounts import compare_amounts

        if not deploys:
            return []

        tickers = [d.ticker for d in deploys]

        # Batch query 1: Get total_minted for all tickers
        total_minted_results = (
            self.db.query(
                BRC20Operation.ticker, func.coalesce(func.sum(BRC20Operation.amount), 0).label("total_minted")
            )
            .filter(
                BRC20Operation.ticker.in_(tickers),
                BRC20Operation.operation.in_(["mint", "mint_stones"]),
                BRC20Operation.is_valid == True,
            )
            .group_by(BRC20Operation.ticker)
            .all()
        )
        total_minted_map = {row.ticker: float(row.total_minted) for row in total_minted_results}

        # Batch query 2: Get holder counts for all tickers
        holder_results = (
            self.db.query(Balance.ticker, func.count(Balance.address).label("holder_count"))
            .filter(Balance.ticker.in_(tickers), Balance.balance != 0)
            .group_by(Balance.ticker)
            .all()
        )
        holder_map = {row.ticker: row.holder_count for row in holder_results}

        # Batch query 3: Get total_locked in swap positions for all tickers
        total_locked_results = (
            self.db.query(
                SwapPosition.src_ticker, func.coalesce(func.sum(SwapPosition.amount_locked), 0).label("total_locked")
            )
            .filter(SwapPosition.src_ticker.in_(tickers), SwapPosition.status == "active")
            .group_by(SwapPosition.src_ticker)
            .all()
        )
        total_locked_map = {row.src_ticker: float(row.total_locked) for row in total_locked_results}

        # Batch query 4: Get curve_staked for all tickers (staking_ticker)
        curve_staked_results = (
            self.db.query(
                CurveConstitution.staking_ticker,
                func.coalesce(func.sum(CurveConstitution.total_staked), 0).label("curve_staked"),
            )
            .filter(CurveConstitution.staking_ticker.in_(tickers))
            .group_by(CurveConstitution.staking_ticker)
            .all()
        )
        curve_staked_map = {row.staking_ticker: float(row.curve_staked) for row in curve_staked_results}

        # Batch query 5: Get curve token info (ticker)
        curve_tickers = self.db.query(CurveConstitution.ticker).filter(CurveConstitution.ticker.in_(tickers)).all()
        curve_ticker_set = {row.ticker for row in curve_tickers}

        # Batch query 6: Get current_supply for special tokens (W, STONES) and Curve tokens
        special_tickers = []
        for deploy in deploys:
            is_wrap = deploy.ticker == "W" or (deploy.max_supply == 0 and deploy.limit_per_op == 0)
            is_stones = deploy.ticker == "STONES" or (
                deploy.max_supply == 0 and deploy.limit_per_op == 1 and not is_wrap
            )
            if is_wrap or is_stones or deploy.ticker in curve_ticker_set:
                special_tickers.append(deploy.ticker)

        current_supply_map = {}
        if special_tickers:
            current_supply_results = (
                self.db.query(Balance.ticker, func.coalesce(func.sum(Balance.balance), 0).label("current_supply"))
                .filter(Balance.ticker.in_(special_tickers), Balance.balance != 0)
                .group_by(Balance.ticker)
                .all()
            )
            current_supply_map = {row.ticker: float(row.current_supply) for row in current_supply_results}

        # Build stats for each deploy using batch data
        ticker_data = []
        for deploy in deploys:
            ticker = deploy.ticker
            is_wrap_token = ticker == "W" or (deploy.max_supply == 0 and deploy.limit_per_op == 0)
            is_stones_token = ticker == "STONES" or (
                deploy.max_supply == 0 and deploy.limit_per_op == 1 and not is_wrap_token
            )
            is_special_token = is_wrap_token or is_stones_token
            is_curve = ticker in curve_ticker_set

            # Get total_minted
            total_minted = total_minted_map.get(ticker, 0)

            # Get current_supply
            if is_curve:
                current_supply = current_supply_map.get(ticker, 0)
                total_minted = current_supply  # For Curve: minted = current_supply
            elif is_special_token:
                current_supply = current_supply_map.get(ticker, 0)
            else:
                if compare_amounts(str(total_minted), deploy.max_supply) >= 0:
                    current_supply = float(deploy.max_supply)
                else:
                    current_supply = float(total_minted)

            # Get holder_count
            holder_count = holder_map.get(ticker, 0)

            # Get total_locked
            total_locked = total_locked_map.get(ticker, 0)
            curve_staked = curve_staked_map.get(ticker, 0)
            total_locked = float(total_locked) + float(curve_staked)
            locked_in_curve = float(curve_staked)

            # Calculate is_completed
            is_completed = compare_amounts(str(total_minted), deploy.max_supply) >= 0

            # Calculate circulating_supply
            circulating_supply = float(current_supply) - total_locked
            circulating_supply = max(0, circulating_supply)

            ticker_data.append(
                {
                    "tick": ticker,
                    "max": deploy.max_supply,
                    "max_supply": deploy.max_supply,
                    "remaining_supply": str(deploy.remaining_supply) if deploy.remaining_supply is not None else None,
                    "limit": deploy.limit_per_op,
                    "minted": str(total_minted),
                    "current_supply": str(current_supply),
                    "total_locked": str(total_locked),
                    "locked_in_curve": str(locked_in_curve),
                    "circulating_supply": str(circulating_supply),
                    "holders": holder_count,
                    "deploy_txid": deploy.deploy_txid,
                    "deploy_height": deploy.deploy_height,
                    "deploy_time": int(deploy.deploy_timestamp.timestamp()),
                    "deployer": deploy.deployer_address or "",
                    "is_completed": is_completed,
                    "decimals": 9,
                    "is_curve": is_curve,
                }
            )

        return ticker_data

    def get_ticker_holders(self, ticker: str, start: int = 0, size: int = 50) -> Dict:
        try:
            normalized_ticker = ticker.upper()

            query = (
                self.db.query(Balance)
                .filter(Balance.ticker == normalized_ticker, Balance.balance != 0)
                .order_by(Balance.balance.desc())
            )

            total = query.count()
            holders = query.offset(start).limit(size).all()

            holder_addresses = [h.address for h in holders]
            latest_transfers = {}

            if holder_addresses:
                subquery = (
                    self.db.query(
                        BRC20Operation.to_address,
                        func.max(BRC20Operation.block_height).label("max_height"),
                    )
                    .filter(
                        BRC20Operation.ticker == normalized_ticker,
                        BRC20Operation.to_address.in_(holder_addresses),
                        BRC20Operation.is_valid.is_(True),
                    )
                    .group_by(BRC20Operation.to_address)
                    .subquery()
                )

                transfers = (
                    self.db.query(BRC20Operation)
                    .join(
                        subquery,
                        and_(
                            BRC20Operation.to_address == subquery.c.to_address,
                            BRC20Operation.block_height == subquery.c.max_height,
                        ),
                    )
                    .filter(
                        BRC20Operation.ticker == normalized_ticker,
                        BRC20Operation.is_valid.is_(True),
                    )
                    .all()
                )

                latest_transfers = {t.to_address: t for t in transfers}

            holder_data = []
            virtual_data = []

            for holder in holders:
                transfer = latest_transfers.get(holder.address)
                holder_data.append(
                    {
                        "address": holder.address,
                        "balance": holder.balance,
                        "transfer_txid": transfer.txid if transfer else "",
                        "transfer_height": transfer.block_height if transfer else 0,
                        "transfer_time": (int(transfer.timestamp.timestamp()) if transfer else 0),
                    }
                )

                # Calculate virtual_accounting entry for POOL addresses if partial_amount > 0
                if holder.address.startswith("POOL::") and not holder.address.startswith("POOL:PARTIAL::"):
                    # Extract pool_id from address (POOL::LOL-WTF -> LOL-WTF)
                    pool_id = holder.address.replace("POOL::", "")

                    # Get total locked for this pool and ticker
                    total_locked_result = (
                        self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
                        .filter(
                            SwapPosition.pool_id == pool_id,
                            SwapPosition.src_ticker == normalized_ticker,
                            SwapPosition.status == SwapPositionStatus.active,
                        )
                        .scalar()
                    )
                    total_locked = (
                        Decimal(str(total_locked_result)) if total_locked_result is not None else Decimal("0")
                    )

                    # Calculate partial amount
                    real_balance = Decimal(str(holder.balance))
                    partial_amount = total_locked - real_balance
                    if partial_amount > 0:
                        # Add virtual_accounting entry to separate list
                        virtual_address = f"POOL:PARTIAL::{pool_id}"
                        virtual_data.append(
                            {
                                "address": virtual_address,
                                "balance": str(partial_amount),
                                "transfer_txid": "",
                                "transfer_height": 0,
                                "transfer_time": 0,
                            }
                        )

            return {
                "total": total,
                "start": start,
                "size": size,
                "data": holder_data,
                "virtual_accounting": virtual_data,
            }

        except Exception as e:
            logger.error("Failed to get ticker holders", ticker=ticker, error=str(e))
            raise

    def get_ticker_transactions(self, ticker: str, start: int = 0, size: int = 100000) -> Dict:
        try:
            normalized_ticker = ticker.upper()

            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    BRC20Operation.ticker == normalized_ticker,
                    BRC20Operation.is_valid.is_(True),
                )
                .order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())
            )

            total = query.count()
            results = query.offset(start).limit(size).all()

            transaction_data = []
            for tx, block_hash in results:
                operation_data = self._map_operation_to_op_model(tx, block_hash)
                transaction_data.append(operation_data)

            return {
                "total": total,
                "start": start,
                "size": size,
                "data": transaction_data,
            }

        except Exception as e:
            logger.error("Failed to get ticker transactions", ticker=ticker, error=str(e))
            raise

    def get_address_balances(self, address: str, start: int = 0, size: int = 50) -> Dict:
        try:
            # Import validator for dynamic yToken balance calculation
            from src.models.validator import BRC20Validator
            from src.models.curve import CurveConstitution, CurveUserInfo
            from src.models.block import ProcessedBlock
            from src.services.curve_service import CurveService
            from decimal import ROUND_DOWN

            validator = BRC20Validator(self.db)

            # 1. Get standard balances from Balance table
            query = (
                self.db.query(Balance)
                .filter(Balance.address == address, Balance.balance != 0)
                .order_by(Balance.balance.desc())
            )

            standard_balances = query.all()

            # 2. Get yToken balances from CurveUserInfo
            # Find all CurveUserInfo records for this address
            user_infos = self.db.query(CurveUserInfo).filter(CurveUserInfo.user_address == address).all()

            # Get latest block for liquidity_index update
            latest_block = self.db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()
            current_block = latest_block.height if latest_block else None

            ytoken_balances = []
            RAY = Decimal("10") ** 27

            for user_info in user_infos:
                # Get CurveConstitution for this reward_ticker
                constitution = self.db.query(CurveConstitution).filter_by(ticker=user_info.ticker).first()
                if not constitution:
                    continue

                self.db.refresh(constitution)
                liquidity_index = Decimal(str(constitution.liquidity_index))

                # Calculate real yToken balance
                scaled_balance = Decimal(str(user_info.scaled_balance))
                if liquidity_index > 0:
                    real_balance = (scaled_balance * liquidity_index) / RAY
                    real_balance = real_balance.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                else:
                    real_balance = Decimal("0")

                # Only include if balance > 0
                if real_balance > 0:
                    # Construct yToken ticker from staking_ticker (preserve 'y' lowercase)
                    ytoken_ticker = "y" + constitution.staking_ticker.upper()
                    ytoken_balances.append(
                        {
                            "ticker": ytoken_ticker,
                            "balance": real_balance,
                            "is_ytoken": True,
                            "reward_ticker": constitution.ticker,
                            "staking_ticker": constitution.staking_ticker,
                        }
                    )

            # 3. Combine standard balances and yToken balances
            all_tickers = [b.ticker for b in standard_balances] + [yt["ticker"] for yt in ytoken_balances]
            latest_transfers = {}

            if all_tickers:
                subquery = (
                    self.db.query(
                        BRC20Operation.ticker,
                        func.max(BRC20Operation.block_height).label("max_height"),
                    )
                    .filter(
                        BRC20Operation.to_address == address,
                        BRC20Operation.ticker.in_(all_tickers),
                        BRC20Operation.is_valid.is_(True),
                    )
                    .group_by(BRC20Operation.ticker)
                    .subquery()
                )

                transfers = (
                    self.db.query(BRC20Operation)
                    .join(
                        subquery,
                        and_(
                            BRC20Operation.ticker == subquery.c.ticker,
                            BRC20Operation.block_height == subquery.c.max_height,
                        ),
                    )
                    .filter(
                        BRC20Operation.to_address == address,
                        BRC20Operation.is_valid.is_(True),
                    )
                    .all()
                )

                latest_transfers = {t.ticker: t for t in transfers}

            balance_data = []

            # Add standard balances
            for balance in standard_balances:
                transfer = latest_transfers.get(balance.ticker)

                # Detect if this is a Curve yToken (lowercase 'y' prefix)
                ticker = balance.ticker
                if ticker and len(ticker) > 0 and ticker[0] == "y":
                    # Use get_balance() for dynamic calculation of yTokens
                    balance_value = validator.get_balance(address, ticker)
                else:
                    # Normal token
                    balance_value = balance.balance

                balance_data.append(
                    {
                        "tick": ticker,
                        "balance": balance_value,
                        "transfer_txid": transfer.txid if transfer else "",
                        "transfer_height": transfer.block_height if transfer else 0,
                        "transfer_time": (int(transfer.timestamp.timestamp()) if transfer else 0),
                    }
                )

            # Add yToken balances (only if not already in standard balances)
            existing_tickers = {b["tick"] for b in balance_data}
            for yt in ytoken_balances:
                ytoken_ticker = yt["ticker"]
                if ytoken_ticker not in existing_tickers:
                    transfer = latest_transfers.get(ytoken_ticker)
                    balance_data.append(
                        {
                            "tick": ytoken_ticker,
                            "balance": yt["balance"],
                            "transfer_txid": transfer.txid if transfer else "",
                            "transfer_height": transfer.block_height if transfer else 0,
                            "transfer_time": (int(transfer.timestamp.timestamp()) if transfer else 0),
                        }
                    )

            # Sort by balance descending and apply pagination
            balance_data.sort(key=lambda x: x["balance"], reverse=True)
            total = len(balance_data)
            paginated_data = balance_data[start : start + size]

            return {"total": total, "start": start, "size": len(paginated_data), "data": paginated_data}

        except Exception as e:
            logger.error("Failed to get address balances", address=address, error=str(e))
            raise

    def get_address_transactions(self, address: str, start: int = 0, size: int = 100000) -> Dict:
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    or_(
                        BRC20Operation.from_address == address,
                        BRC20Operation.to_address == address,
                    ),
                    BRC20Operation.is_valid.is_(True),
                )
                .order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())
            )

            total = query.count()
            results = query.offset(start).limit(size).all()

            transaction_data = []
            for tx, block_hash in results:
                operation_data = self._map_operation_to_op_model(tx, block_hash)
                transaction_data.append(operation_data)

            return {
                "total": total,
                "start": start,
                "size": size,
                "data": transaction_data,
            }

        except Exception as e:
            logger.error("Failed to get address transactions", address=address, error=str(e))
            raise

    def get_indexer_status(self) -> Dict:
        try:
            latest_block = self.db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()
            latest_brc20_op = self.db.query(BRC20Operation).order_by(BRC20Operation.block_height.desc()).first()

            return {
                "current_block_height_network": (latest_block.height if latest_block else 0),
                "last_indexed_block_main_chain": (latest_block.height if latest_block else 0),
                "last_indexed_brc20_op_block": (latest_brc20_op.block_height if latest_brc20_op else 0),
            }
        except Exception as e:
            logger.error("Failed to get indexer status", error=str(e))
            raise

    def get_operations_by_height(self, height: int, skip: int = 0, limit: int = 100000) -> List[Dict]:
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    BRC20Operation.block_height == height,
                    BRC20Operation.is_valid.is_(True),
                )
                .order_by(BRC20Operation.tx_index.asc())
            )

            results = query.offset(skip).limit(limit).all()

            result = []
            for op, block_hash in results:
                operation_data = self._map_operation_to_op_model(op, block_hash)
                result.append(operation_data)

            return result

        except Exception as e:
            logger.error("Failed to get operations by height", height=height, error=str(e))
            raise

    def get_transaction_operations(self, ticker: str, txid: str) -> List[Dict]:
        try:
            results = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    BRC20Operation.ticker == ticker.upper(),
                    BRC20Operation.txid == txid,
                    BRC20Operation.is_valid.is_(True),
                )
                .order_by(BRC20Operation.tx_index.asc())
                .all()
            )

            result = []
            for op, block_hash in results:
                operation_data = self._map_operation_to_op_model(op, block_hash)
                result.append(operation_data)

            return result
        except Exception as e:
            logger.error(
                "Failed to get transaction operations",
                ticker=ticker,
                txid=txid,
                error=str(e),
            )
            raise

    def get_address_ticker_history(
        self,
        address: str,
        ticker: str,
        op_type: str = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict]:
        """Get operations for specific address and ticker"""
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    or_(
                        BRC20Operation.from_address == address,
                        BRC20Operation.to_address == address,
                    ),
                    BRC20Operation.ticker == ticker.upper(),
                    BRC20Operation.is_valid.is_(True),
                )
            )

            if op_type:
                query = query.filter(BRC20Operation.operation == op_type)

            results = (
                query.order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )

            result = []
            for op, block_hash in results:
                result.append(
                    {
                        "id": op.id,
                        "op": op.operation,
                        "ticker": op.ticker,
                        "amount": op.amount or "",
                        "from_address": op.from_address or "",
                        "to_address": op.to_address or "",
                        "block_height": op.block_height,
                        "block_hash": block_hash,
                        "timestamp": (op.timestamp.isoformat() + "Z" if op.timestamp else ""),
                        "valid": op.is_valid,
                    }
                )

            return result
        except Exception as e:
            logger.error(
                "Failed to get address ticker history",
                address=address,
                ticker=ticker,
                error=str(e),
            )
            raise

    def get_single_address_balance(self, address: str, ticker: str) -> Dict:
        """Get balance for specific address and ticker"""
        try:
            # Detect if this is a Curve yToken (lowercase 'y' prefix)
            if ticker and len(ticker) > 0 and ticker[0] == "y":
                # Use get_balance() for dynamic calculation of yTokens
                from src.models.validator import BRC20Validator

                validator = BRC20Validator(self.db)
                balance_value = validator.get_balance(address, ticker)
                normalized_ticker = "y" + ticker[1:].upper()
            else:
                # Normal token: read from Balance table
                balance = (
                    self.db.query(Balance).filter(Balance.address == address, Balance.ticker == ticker.upper()).first()
                )
                balance_value = balance.balance if balance else Decimal("0")
                normalized_ticker = ticker.upper()

            if balance_value == 0:
                return {
                    "pkscript": "",
                    "ticker": normalized_ticker,
                    "wallet": address,
                    "overall_balance": "0",
                    "available_balance": "0",
                    "block_height": 0,
                }

            latest_transfer = (
                self.db.query(BRC20Operation)
                .filter(
                    BRC20Operation.to_address == address,
                    BRC20Operation.ticker == normalized_ticker,
                    BRC20Operation.is_valid.is_(True),
                )
                .order_by(BRC20Operation.block_height.desc())
                .first()
            )

            # Format balance to 8 decimals (BRC-20 precision)
            from decimal import ROUND_DOWN

            balance_formatted = balance_value.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

            return {
                "pkscript": "",
                "ticker": normalized_ticker,
                "wallet": address,
                "overall_balance": str(balance_formatted),
                "available_balance": str(balance_formatted),
                "block_height": latest_transfer.block_height if latest_transfer else 0,
            }
        except Exception as e:
            logger.error(
                "Failed to get single address balance",
                address=address,
                ticker=ticker,
                error=str(e),
            )
            raise

    def get_address_history_complete(
        self,
        address: str,
        ticker: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Op]:
        """Get complete address history with all Op model fields populated"""
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    or_(
                        BRC20Operation.from_address == address,
                        BRC20Operation.to_address == address,
                    ),
                    BRC20Operation.is_valid.is_(True),
                )
            )

            if ticker:
                query = query.filter(BRC20Operation.ticker == ticker.upper())

            results = (
                query.order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )

            operations = []
            for db_op, block_hash in results:
                op_data = self._map_operation_to_op_model(db_op, block_hash)
                operations.append(Op(**op_data))

            return operations

        except Exception as e:
            logger.error(
                "Failed to get complete address history",
                address=address,
                ticker=ticker,
                error=str(e),
            )
            raise

    def get_ticker_operations_complete(self, ticker: str, skip: int = 0, limit: int = 100) -> List[Op]:
        """Get complete operations for a ticker with all Op model fields populated"""
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    BRC20Operation.ticker == ticker.upper(),
                    BRC20Operation.is_valid.is_(True),
                )
            )

            results = (
                query.order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )

            operations = []
            for db_op, block_hash in results:
                op_data = self._map_operation_to_op_model(db_op, block_hash)
                operations.append(Op(**op_data))

            return operations

        except Exception as e:
            logger.error("Failed to get complete ticker operations", ticker=ticker, error=str(e))
            raise

    def get_operation_by_id_complete(self, operation_id: int) -> Optional[Op]:
        """Get a single operation by ID with all Op model fields populated"""
        try:
            result = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(BRC20Operation.id == operation_id)
                .first()
            )

            if not result:
                return None

            db_op, block_hash = result
            op_data = self._map_operation_to_op_model(db_op, block_hash)
            return Op(**op_data)

        except Exception as e:
            logger.error("Failed to get operation by ID", operation_id=operation_id, error=str(e))
            raise

    def _map_operation_to_op_model(self, db_op: BRC20Operation, block_hash: str) -> Dict:
        """Map database operation to Op model data with all required fields"""
        return {
            "id": db_op.id,
            "tx_id": db_op.txid,
            "txid": db_op.txid,
            "op": db_op.operation,
            "ticker": db_op.ticker,
            "amount": db_op.amount if db_op.amount else None,
            "block_height": db_op.block_height,
            "block_hash": block_hash,
            "tx_index": db_op.tx_index,
            "timestamp": db_op.timestamp.isoformat() + "Z" if db_op.timestamp else "",
            "from_address": db_op.from_address,
            "to_address": db_op.to_address,
            "valid": db_op.is_valid,
            "is_marketplace": db_op.is_marketplace if hasattr(db_op, "is_marketplace") else False,
        }

    def get_history_by_height(self, height: int, start: int = 0, size: int = 100000) -> Dict:
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    BRC20Operation.block_height == height,
                    BRC20Operation.is_valid.is_(True),
                )
                .order_by(BRC20Operation.tx_index.asc())
            )

            total = query.count()
            results = query.offset(start).limit(size).all()

            transaction_data = []
            for tx, block_hash in results:
                operation_data = self._map_operation_to_op_model(tx, block_hash)
                transaction_data.append(operation_data)

            return {
                "total": total,
                "start": start,
                "size": size,
                "data": transaction_data,
            }

        except Exception as e:
            logger.error("Failed to get history by height", height=height, error=str(e))
            raise

    def get_all_tickers_with_stats_unlimited(self, max_results: Optional[int] = None) -> Dict:
        try:
            query = self.db.query(Deploy).order_by(Deploy.deploy_height.desc())
            total = query.count()

            if max_results:
                deploys = query.limit(max_results).all()
            else:
                deploys = query.all()

            ticker_data = []
            for deploy in deploys:
                stats = self._calculate_ticker_stats(deploy)
                if stats:
                    ticker_data.append(stats)

            return {
                "total": total,
                "start": 0,
                "size": len(ticker_data),
                "data": ticker_data,
            }
        except Exception as e:
            logger.error("Failed to get all tickers", error=str(e))
            raise

    def get_all_ticker_holders_unlimited(self, ticker: str, max_results: Optional[int] = None) -> Dict:
        try:
            normalized_ticker = ticker.upper()

            query = (
                self.db.query(Balance)
                .filter(Balance.ticker == normalized_ticker, Balance.balance != 0)
                .order_by(Balance.balance.desc())
            )

            total = query.count()

            if max_results:
                holders = query.limit(max_results).all()
            else:
                holders = query.all()

            holder_addresses = [h.address for h in holders]
            latest_transfers = {}

            if holder_addresses:
                subquery = (
                    self.db.query(
                        BRC20Operation.to_address,
                        func.max(BRC20Operation.block_height).label("max_height"),
                    )
                    .filter(
                        BRC20Operation.ticker == normalized_ticker,
                        BRC20Operation.to_address.in_(holder_addresses),
                        BRC20Operation.is_valid.is_(True),
                    )
                    .group_by(BRC20Operation.to_address)
                    .subquery()
                )

                transfers = (
                    self.db.query(BRC20Operation)
                    .join(
                        subquery,
                        and_(
                            BRC20Operation.to_address == subquery.c.to_address,
                            BRC20Operation.block_height == subquery.c.max_height,
                        ),
                    )
                    .filter(
                        BRC20Operation.ticker == normalized_ticker,
                        BRC20Operation.is_valid.is_(True),
                    )
                    .all()
                )

                latest_transfers = {t.to_address: t for t in transfers}

            holder_data = []
            virtual_data = []

            for holder in holders:
                transfer = latest_transfers.get(holder.address)
                holder_data.append(
                    {
                        "address": holder.address,
                        "balance": holder.balance,
                        "transfer_txid": transfer.txid if transfer else "",
                        "transfer_height": transfer.block_height if transfer else 0,
                        "transfer_time": (int(transfer.timestamp.timestamp()) if transfer else 0),
                    }
                )

                # Calculate virtual_accounting entry for POOL addresses if partial_amount > 0
                if holder.address.startswith("POOL::") and not holder.address.startswith("POOL:PARTIAL::"):
                    # Extract pool_id from address (POOL::LOL-WTF -> LOL-WTF)
                    pool_id = holder.address.replace("POOL::", "")

                    # Get total locked for this pool and ticker
                    total_locked_result = (
                        self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
                        .filter(
                            SwapPosition.pool_id == pool_id,
                            SwapPosition.src_ticker == normalized_ticker,
                            SwapPosition.status == SwapPositionStatus.active,
                        )
                        .scalar()
                    )
                    total_locked = (
                        Decimal(str(total_locked_result)) if total_locked_result is not None else Decimal("0")
                    )

                    # Calculate partial amount
                    real_balance = Decimal(str(holder.balance))
                    partial_amount = total_locked - real_balance
                    if partial_amount > 0:
                        # Add virtual_accounting entry to separate list
                        virtual_address = f"POOL:PARTIAL::{pool_id}"
                        virtual_data.append(
                            {
                                "address": virtual_address,
                                "balance": str(partial_amount),
                                "transfer_txid": "",
                                "transfer_height": 0,
                                "transfer_time": 0,
                            }
                        )

            return {
                "total": total,
                "start": 0,
                "size": len(holder_data),
                "data": holder_data,
                "virtual_accounting": virtual_data,
            }

        except Exception as e:
            logger.error("Failed to get all ticker holders", ticker=ticker, error=str(e))
            raise

    def get_all_ticker_transactions_unlimited(
        self,
        ticker: str,
        max_results: Optional[int] = None,
        include_invalid: bool = False,
    ) -> Dict:
        try:
            normalized_ticker = ticker.upper()

            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(BRC20Operation.ticker == normalized_ticker)
            )

            if not include_invalid:
                query = query.filter(BRC20Operation.is_valid.is_(True))

            query = query.order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())

            total = query.count()

            if max_results:
                results = query.limit(max_results).all()
            else:
                results = query.all()

            transaction_data = []
            for tx, block_hash in results:
                operation_data = self._map_operation_to_op_model(tx, block_hash)
                transaction_data.append(operation_data)

            return {
                "total": total,
                "start": 0,
                "size": len(transaction_data),
                "data": transaction_data,
            }

        except Exception as e:
            logger.error("Failed to get all ticker transactions", ticker=ticker, error=str(e))
            raise

    def get_all_address_transactions_unlimited(
        self,
        address: str,
        max_results: Optional[int] = None,
        include_invalid: bool = False,
    ) -> Dict:
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(
                    or_(
                        BRC20Operation.from_address == address,
                        BRC20Operation.to_address == address,
                    )
                )
            )

            if not include_invalid:
                query = query.filter(BRC20Operation.is_valid.is_(True))

            query = query.order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())

            total = query.count()

            if max_results:
                results = query.limit(max_results).all()
            else:
                results = query.all()

            transaction_data = []
            for tx, block_hash in results:
                operation_data = self._map_operation_to_op_model(tx, block_hash)
                transaction_data.append(operation_data)

            return {
                "total": total,
                "start": 0,
                "size": len(transaction_data),
                "data": transaction_data,
            }

        except Exception as e:
            logger.error("Failed to get all address transactions", address=address, error=str(e))
            raise

    def get_all_history_by_height_unlimited(
        self,
        height: int,
        max_results: Optional[int] = None,
        include_invalid: bool = False,
    ) -> Dict:
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height)
                .filter(BRC20Operation.block_height == height)
            )

            if not include_invalid:
                query = query.filter(BRC20Operation.is_valid.is_(True))

            query = query.order_by(BRC20Operation.tx_index.asc())

            total = query.count()

            if max_results:
                results = query.limit(max_results).all()
            else:
                results = query.all()

            transaction_data = []
            for tx, block_hash in results:
                operation_data = self._map_operation_to_op_model(tx, block_hash)
                transaction_data.append(operation_data)

            return {
                "total": total,
                "start": 0,
                "size": len(transaction_data),
                "data": transaction_data,
            }

        except Exception as e:
            logger.error("Failed to get all history by height", height=height, error=str(e))
            raise
