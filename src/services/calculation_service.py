from typing import Dict, List, Optional

import structlog
from sqlalchemy import and_, func, or_, Numeric
from sqlalchemy.orm import Session

from src.api.models import Op
from src.models.balance import Balance
from src.models.block import ProcessedBlock
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.utils.amounts import compare_amounts

logger = structlog.get_logger()


def get_regex_operator(db):
    if hasattr(db.bind, 'dialect') and db.bind.dialect.name == 'postgresql':
        return '~'
    return 'regexp'

class BRC20CalculationService:
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_all_tickers_with_stats(self, start: int = 0, size: int = 50) -> Dict:
        """Get all tickers with calculated statistics - OPTIMIZED"""
        try:
            query = self.db.query(Deploy).order_by(Deploy.deploy_height.desc())
            total = query.count()
            deploys = query.offset(start).limit(size).all()

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
        """Get complete statistics for a single ticker"""
        try:
            normalized_ticker = ticker.upper()

            deploy = (
                self.db.query(Deploy).filter(Deploy.ticker == normalized_ticker).first()
            )

            if not deploy:
                return None

            return self._calculate_ticker_stats(deploy)

        except Exception as e:
            logger.error("Failed to get ticker stats", ticker=ticker, error=str(e))
            raise

    def _calculate_ticker_stats(self, deploy: Deploy) -> Dict:
        """Calculate statistics for a deploy (internal helper)"""
        regex_op = get_regex_operator(self.db)
        current_supply = (
            self.db.query(func.coalesce(func.sum(Balance.balance.cast(Numeric)), 0))
            .filter(Balance.ticker == deploy.ticker, Balance.balance != "0")
            .filter(Balance.balance.op(regex_op)('^[0-9]+$'))  # Cross-DB regex: only numeric balances
            .scalar()
            or "0"
        )

        holder_count = (
            self.db.query(Balance)
            .filter(Balance.ticker == deploy.ticker, Balance.balance != "0")
            .filter(Balance.balance.op(regex_op)('^[0-9]+$'))  # Cross-DB regex: only numeric balances
            .count()
        )

        is_completed = compare_amounts(str(current_supply), deploy.max_supply) >= 0

        return {
            "tick": deploy.ticker,
            "max": deploy.max_supply,
            "limit": deploy.limit_per_op,
            "minted": str(current_supply),
            "holders": holder_count,
            "deploy_txid": deploy.deploy_txid,
            "deploy_height": deploy.deploy_height,
            "deploy_time": int(deploy.deploy_timestamp.timestamp()),
            "deployer": deploy.deployer_address or "",
            "is_completed": is_completed,
            "decimals": deploy.decimals if hasattr(deploy, "decimals") else 18,
        }

    def get_ticker_holders(self, ticker: str, start: int = 0, size: int = 50) -> Dict:
        """Get holders for ticker with latest transfer info"""
        try:
            normalized_ticker = ticker.upper()

            regex_op = get_regex_operator(self.db)

            query = (
                self.db.query(Balance)
                .filter(Balance.ticker == normalized_ticker, Balance.balance != "0")
                .filter(Balance.balance.op(regex_op)('^[0-9]+$'))  # Cross-DB regex: only numeric balances
                .order_by(Balance.balance.cast(Numeric).desc())
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
                        BRC20Operation.is_valid is True,
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
                        BRC20Operation.is_valid is True,
                    )
                    .all()
                )

                latest_transfers = {t.to_address: t for t in transfers}

            holder_data = []
            for holder in holders:
                transfer = latest_transfers.get(holder.address)
                holder_data.append(
                    {
                        "address": holder.address,
                        "balance": holder.balance,
                        "transfer_txid": transfer.txid if transfer else "",
                        "transfer_height": transfer.block_height if transfer else 0,
                        "transfer_time": (
                            int(transfer.timestamp.timestamp()) if transfer else 0
                        ),
                    }
                )

            return {"total": total, "start": start, "size": size, "data": holder_data}

        except Exception as e:
            logger.error("Failed to get ticker holders", ticker=ticker, error=str(e))
            raise

    def get_ticker_transactions(
        self, ticker: str, start: int = 0, size: int = 100000
    ) -> Dict:
        """Get transactions for ticker with proper formatting"""
        try:
            normalized_ticker = ticker.upper()

            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(
                    BRC20Operation.ticker == normalized_ticker,
                    BRC20Operation.is_valid is True,
                )
                .order_by(
                    BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc()
                )
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
            logger.error(
                "Failed to get ticker transactions", ticker=ticker, error=str(e)
            )
            raise

    def get_address_balances(
        self, address: str, start: int = 0, size: int = 50
    ) -> Dict:
        """Get balances for address with latest transfer info"""
        try:
            regex_op = get_regex_operator(self.db)

            query = (
                self.db.query(Balance)
                .filter(Balance.address == address, Balance.balance != "0")
                .filter(Balance.balance.op(regex_op)('^[0-9]+$'))  # Cross-DB regex: only numeric balances
                .order_by(Balance.balance.cast(Numeric).desc())
            )

            total = query.count()
            balances = query.offset(start).limit(size).all()

            tickers = [b.ticker for b in balances]
            latest_transfers = {}

            if tickers:
                subquery = (
                    self.db.query(
                        BRC20Operation.ticker,
                        func.max(BRC20Operation.block_height).label("max_height"),
                    )
                    .filter(
                        BRC20Operation.to_address == address,
                        BRC20Operation.ticker.in_(tickers),
                        BRC20Operation.is_valid is True,
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
                        BRC20Operation.is_valid is True,
                    )
                    .all()
                )

                latest_transfers = {t.ticker: t for t in transfers}

            balance_data = []
            for balance in balances:
                transfer = latest_transfers.get(balance.ticker)
                balance_data.append(
                    {
                        "tick": balance.ticker,
                        "balance": balance.balance,
                        "transfer_txid": transfer.txid if transfer else "",
                        "transfer_height": transfer.block_height if transfer else 0,
                        "transfer_time": (
                            int(transfer.timestamp.timestamp()) if transfer else 0
                        ),
                    }
                )

            return {"total": total, "start": start, "size": size, "data": balance_data}

        except Exception as e:
            logger.error(
                "Failed to get address balances", address=address, error=str(e)
            )
            raise

    def get_address_transactions(
        self, address: str, start: int = 0, size: int = 100000
    ) -> Dict:
        """Get transactions for address with proper formatting"""
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(
                    or_(
                        BRC20Operation.from_address == address,
                        BRC20Operation.to_address == address,
                    ),
                    BRC20Operation.is_valid is True,
                )
                .order_by(
                    BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc()
                )
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
            logger.error(
                "Failed to get address transactions", address=address, error=str(e)
            )
            raise

    def get_indexer_status(self) -> Dict:
        """Get blockchain sync status"""
        try:
            latest_block = (
                self.db.query(ProcessedBlock)
                .order_by(ProcessedBlock.height.desc())
                .first()
            )
            latest_brc20_op = (
                self.db.query(BRC20Operation)
                .order_by(BRC20Operation.block_height.desc())
                .first()
            )

            return {
                "current_block_height_network": (
                    latest_block.height if latest_block else 0
                ),
                "last_indexed_block_main_chain": (
                    latest_block.height if latest_block else 0
                ),
                "last_indexed_brc20_op_block": (
                    latest_brc20_op.block_height if latest_brc20_op else 0
                ),
            }
        except Exception as e:
            logger.error("Failed to get indexer status", error=str(e))
            raise

    def get_operations_by_height(
        self, height: int, skip: int = 0, limit: int = 100000
    ) -> List[Dict]:
        """Get all operations at specific block height"""
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(
                    BRC20Operation.block_height == height,
                    BRC20Operation.is_valid is True,
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
            logger.error(
                "Failed to get operations by height", height=height, error=str(e)
            )
            raise

    def get_transaction_operations(self, ticker: str, txid: str) -> List[Dict]:
        """Get all operations in specific transaction for ticker"""
        try:
            results = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(
                    BRC20Operation.ticker == ticker.upper(),
                    BRC20Operation.txid == txid,
                    BRC20Operation.is_valid is True,
                )
                .order_by(BRC20Operation.tx_index.asc())
                .all()
            )

            result = []
            for op, block_hash in results:
                result.append(
                    {
                        "id": op.id,
                        "op": op.operation,
                        "ticker": op.ticker,
                        "amount_str": op.amount or "",
                        "from_address": op.from_address or "",
                        "to_address": op.to_address or "",
                        "block_height": op.block_height,
                        "block_hash": block_hash,
                        "timestamp": (
                            op.timestamp.isoformat() + "Z" if op.timestamp else ""
                        ),
                        "valid": op.is_valid,
                    }
                )

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
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(
                    or_(
                        BRC20Operation.from_address == address,
                        BRC20Operation.to_address == address,
                    ),
                    BRC20Operation.ticker == ticker.upper(),
                    BRC20Operation.is_valid is True,
                )
            )

            if op_type:
                query = query.filter(BRC20Operation.operation == op_type)

            results = (
                query.order_by(
                    BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc()
                )
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
                        "amount_str": op.amount or "",
                        "from_address": op.from_address or "",
                        "to_address": op.to_address or "",
                        "block_height": op.block_height,
                        "block_hash": block_hash,
                        "timestamp": (
                            op.timestamp.isoformat() + "Z" if op.timestamp else ""
                        ),
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
            balance = (
                self.db.query(Balance)
                .filter(Balance.address == address, Balance.ticker == ticker.upper())
                .first()
            )

            if not balance:
                return {
                    "pkscript": "",
                    "ticker": ticker.upper(),
                    "wallet": address,
                    "overall_balance": "0",
                    "available_balance": "0",
                    "block_height": 0,
                }

            latest_transfer = (
                self.db.query(BRC20Operation)
                .filter(
                    BRC20Operation.to_address == address,
                    BRC20Operation.ticker == ticker.upper(),
                    BRC20Operation.is_valid is True,
                )
                .order_by(BRC20Operation.block_height.desc())
                .first()
            )

            return {
                "pkscript": "",
                "ticker": balance.ticker,
                "wallet": balance.address,
                "overall_balance": str(balance.balance),
                "available_balance": str(balance.balance),
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
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(
                    or_(
                        BRC20Operation.from_address == address,
                        BRC20Operation.to_address == address,
                    ),
                    BRC20Operation.is_valid is True,
                )
            )

            if ticker:
                query = query.filter(BRC20Operation.ticker == ticker.upper())

            results = (
                query.order_by(
                    BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc()
                )
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

    def get_ticker_operations_complete(
        self, ticker: str, skip: int = 0, limit: int = 100
    ) -> List[Op]:
        """Get complete operations for a ticker with all Op model fields populated"""
        try:
            query = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(
                    BRC20Operation.ticker == ticker.upper(),
                    BRC20Operation.is_valid is True,
                )
            )

            results = (
                query.order_by(
                    BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc()
                )
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
                "Failed to get complete ticker operations", ticker=ticker, error=str(e)
            )
            raise

    def get_operation_by_id_complete(self, operation_id: int) -> Optional[Op]:
        """Get a single operation by ID with all Op model fields populated"""
        try:
            result = (
                self.db.query(BRC20Operation, ProcessedBlock.block_hash)
                .join(
                    ProcessedBlock, BRC20Operation.block_height == ProcessedBlock.height
                )
                .filter(BRC20Operation.id == operation_id)
                .first()
            )

            if not result:
                return None

            db_op, block_hash = result
            op_data = self._map_operation_to_op_model(db_op, block_hash)
            return Op(**op_data)

        except Exception as e:
            logger.error(
                "Failed to get operation by ID", operation_id=operation_id, error=str(e)
            )
            raise

    def _map_operation_to_op_model(
        self, db_op: BRC20Operation, block_hash: str
    ) -> Dict:
        """Map database operation to Op model data with all required fields"""
        return {
            "id": db_op.id,
            "tx_id": db_op.txid,
            "txid": db_op.txid,
            "op": db_op.operation,
            "ticker": db_op.ticker,
            "amount_str": db_op.amount if db_op.amount else None,
            "block_height": db_op.block_height,
            "block_hash": block_hash,
            "tx_index": db_op.tx_index,
            "timestamp": db_op.timestamp.isoformat() + "Z" if db_op.timestamp else "",
            "from_address": db_op.from_address,
            "to_address": db_op.to_address,
            "valid": db_op.is_valid,
        }
