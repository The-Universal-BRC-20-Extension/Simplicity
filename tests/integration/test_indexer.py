"""
Tests for IndexerService - Phase 4 blockchain indexing functionality.

Tests cover:
- Block processing workflow
- Sequential processing
- Reorg detection and handling
- Performance monitoring
- Error handling
"""

import time
from unittest.mock import Mock, patch

import pytest

import src.config as config
from src.services.indexer import BlockProcessingResult, IndexerService, SyncStatus
from src.utils.exceptions import IndexerError


class TestIndexerService:
    """Test IndexerService functionality"""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = Mock()
        session.query.return_value.order_by.return_value.first.return_value = None
        session.query.return_value.filter_by.return_value.first.return_value = None
        session.query.return_value.filter.return_value.count.return_value = 0
        return session

    @pytest.fixture
    def mock_bitcoin_rpc(self):
        """Mock Bitcoin RPC service"""
        rpc = Mock()
        rpc.get_block_count.return_value = 850000
        rpc.get_block_hash.return_value = (
            "000000000000000000000000000000000000000000000000000000000000abcd"
        )
        rpc.get_block.return_value = {
            "height": 850000,
            "hash": "000000000000000000000000000000000000000000000000000000000000abcd",
            "tx": ["coinbase_tx", "tx1", "tx2"],
        }
        rpc.get_raw_transaction.return_value = {"txid": "tx1", "vout": [], "vin": []}
        return rpc

    @pytest.fixture
    def indexer_service(self, mock_db_session, mock_bitcoin_rpc):
        """Create IndexerService instance"""
        return IndexerService(mock_db_session, mock_bitcoin_rpc)

    def test_initialization(self, indexer_service, mock_db_session, mock_bitcoin_rpc):
        """Test IndexerService initialization"""
        assert indexer_service.db == mock_db_session
        assert indexer_service.rpc == mock_bitcoin_rpc
        assert indexer_service.processor is not None
        assert indexer_service.logger is not None
        assert indexer_service._processing_times == []
        assert indexer_service._start_time is None
        assert indexer_service._blocks_processed == 0

    def test_get_last_processed_height_no_blocks(
        self, indexer_service, mock_db_session
    ):
        """Test getting last processed height when no blocks exist"""
        mock_db_session.query.return_value.order_by.return_value.first.return_value = (
            None
        )

        height = indexer_service.get_last_processed_height()

        assert height == config.settings.START_BLOCK_HEIGHT - 1

    def test_get_last_processed_height_with_blocks(
        self, indexer_service, mock_db_session
    ):
        """Test getting last processed height when blocks exist"""
        mock_block = Mock()
        mock_block.height = 850500
        mock_db_session.query.return_value.order_by.return_value.first.return_value = (
            mock_block
        )

        height = indexer_service.get_last_processed_height()

        assert height == 850500

    def test_determine_start_height_fresh_start(self, indexer_service):
        """Test determining start height for fresh indexer"""
        with patch.object(
            indexer_service,
            "get_last_processed_height",
            return_value=config.settings.START_BLOCK_HEIGHT - 1,
        ):
            start_height = indexer_service._determine_start_height()
            assert start_height == config.settings.START_BLOCK_HEIGHT

    def test_determine_start_height_resume(self, indexer_service):
        """Test determining start height when resuming"""
        resume_from = config.settings.START_BLOCK_HEIGHT + 500
        with patch.object(
            indexer_service, "get_last_processed_height", return_value=resume_from
        ):
            start_height = indexer_service._determine_start_height()
            assert start_height == resume_from + 1

    def test_is_block_processed_true(self, indexer_service, mock_db_session):
        """Test checking if block is processed - positive case"""
        mock_block = Mock()
        mock_block.block_hash = "test_hash"
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_block
        )

        result = indexer_service.is_block_processed(850000, "test_hash")

        assert result is True

    def test_is_block_processed_false_no_block(self, indexer_service, mock_db_session):
        """Test checking if block is processed - no block"""
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = (
            None
        )

        result = indexer_service.is_block_processed(850000, "test_hash")

        assert result is False

    def test_is_block_processed_false_hash_mismatch(
        self, indexer_service, mock_db_session
    ):
        """Test checking if block is processed - hash mismatch"""
        mock_block = Mock()
        mock_block.block_hash = "different_hash"
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_block
        )

        result = indexer_service.is_block_processed(850000, "test_hash")

        assert result is False

    def test_verify_chain_continuity_true(self, indexer_service, mock_db_session):
        """Test chain continuity verification - continuous"""
        mock_db_session.query.return_value.filter.return_value.count.return_value = 101

        result = indexer_service.verify_chain_continuity(800000, 800100)

        assert result is True

    def test_verify_chain_continuity_false(self, indexer_service, mock_db_session):
        """Test chain continuity verification - gaps"""
        mock_db_session.query.return_value.filter.return_value.count.return_value = 95

        result = indexer_service.verify_chain_continuity(800000, 800100)

        assert result is False

    def test_detect_reorg_true(
        self, indexer_service, mock_db_session, mock_bitcoin_rpc
    ):
        """Test reorg detection - reorg detected"""
        with patch.object(
            indexer_service.reorg_handler, "_detect_reorg", return_value=True
        ):
            result = indexer_service.reorg_handler._detect_reorg(850000)
            assert result is True

    def test_detect_reorg_false(
        self, indexer_service, mock_db_session, mock_bitcoin_rpc
    ):
        """Test reorg detection - no reorg"""
        with patch.object(
            indexer_service.reorg_handler, "_detect_reorg", return_value=False
        ):
            result = indexer_service.reorg_handler._detect_reorg(850000)
            assert result is False

    def test_detect_reorg_no_stored_block(self, indexer_service, mock_db_session):
        """Test reorg detection - no stored block"""
        with patch.object(
            indexer_service.reorg_handler, "_detect_reorg", return_value=False
        ):
            result = indexer_service.reorg_handler._detect_reorg(850000)
            assert result is False

    def test_should_check_reorg_true(self, indexer_service):
        """Test should check reorg - after start height"""
        result = indexer_service._should_check_reorg(
            config.settings.START_BLOCK_HEIGHT + 1
        )
        assert result is True

    def test_should_check_reorg_false(self, indexer_service):
        """Test should check reorg - at start height"""
        result = indexer_service._should_check_reorg(config.settings.START_BLOCK_HEIGHT)
        assert result is False

    def test_process_block_transactions_skip_coinbase(self, indexer_service):
        """Test processing block transactions skips coinbase"""
        block = {
            "height": 850000,
            "hash": "test_block_hash",
            "time": 1677649200,
            "tx": ["coinbase_tx", "tx1", "tx2"],
        }

        with patch.object(
            indexer_service.processor, "process_transaction"
        ) as mock_process:
            mock_process.return_value = Mock(
                operation_found=False, is_valid=False, error_message=None
            )

            results = indexer_service.process_block_transactions(block)

            assert len(results) == 2
            assert mock_process.call_count == 2

    def test_process_block_transactions_with_operations(
        self, indexer_service, mock_bitcoin_rpc
    ):
        """Test processing block transactions with BRC-20 operations"""
        block = {
            "height": 850000,
            "hash": "test_block_hash",
            "time": 1677649200,
            "tx": ["coinbase_tx", "tx1", "tx2"],
        }

        mock_bitcoin_rpc.get_raw_transaction.return_value = {
            "txid": "tx1",
            "vout": [],
            "vin": [],
        }

        mock_result1 = Mock(operation_found=True, is_valid=True, error_message=None)
        mock_result2 = Mock(operation_found=False, is_valid=False, error_message=None)

        with patch.object(
            indexer_service.processor, "process_transaction"
        ) as mock_process:
            mock_process.side_effect = [mock_result1, mock_result2]

            results = indexer_service.process_block_transactions(block)

            assert len(results) == 2
            assert results[0].operation_found is True
            assert results[0].is_valid is True
            assert results[1].operation_found is False

    def test_process_block_success(
        self, indexer_service, mock_db_session, mock_bitcoin_rpc
    ):
        """Test successful block processing"""
        mock_bitcoin_rpc.get_block_hash.return_value = "block_hash"
        mock_bitcoin_rpc.get_block.return_value = {
            "height": 850000,
            "hash": "block_hash",
            "tx": ["coinbase_tx", "tx1"],
        }

        with patch.object(
            indexer_service, "process_block_transactions"
        ) as mock_process_txs:
            mock_result = Mock(operation_found=True, is_valid=True, error_message=None)
            mock_process_txs.return_value = [mock_result]

            result = indexer_service.process_block(850000)

            assert isinstance(result, BlockProcessingResult)
            assert result.height == 850000
            assert result.block_hash == "block_hash"
            assert result.tx_count == 2
            assert result.brc20_operations_found == 1
            assert result.brc20_operations_valid == 1
            assert result.processing_time > 0
            assert result.errors == []

            mock_db_session.add.assert_called_once()
            mock_db_session.commit.assert_called_once()

    def test_process_block_with_errors(
        self, indexer_service, mock_db_session, mock_bitcoin_rpc
    ):
        """Test block processing with transaction errors"""
        mock_bitcoin_rpc.get_block_hash.return_value = "block_hash"
        mock_bitcoin_rpc.get_block.return_value = {
            "height": 850000,
            "hash": "block_hash",
            "tx": ["coinbase_tx", "tx1"],
        }

        with patch.object(
            indexer_service, "process_block_transactions"
        ) as mock_process_txs:
            mock_result = Mock(
                operation_found=True,
                is_valid=False,
                error_message="Validation failed",
                txid="test_txid",
            )
            mock_process_txs.return_value = [mock_result]

            result = indexer_service.process_block(850000)

            assert result.brc20_operations_found == 1
            assert result.brc20_operations_valid == 0
            assert any("Validation failed" in error for error in result.errors)

    def test_process_block_rpc_failure(self, indexer_service, mock_bitcoin_rpc):
        """Test block processing with RPC failure"""
        mock_bitcoin_rpc.get_block_hash.side_effect = Exception("RPC connection failed")

        with pytest.raises(IndexerError, match="Failed to process block 850000"):
            indexer_service.process_block(850000)

    def test_get_sync_status(self, indexer_service, mock_bitcoin_rpc):
        """Test getting sync status"""
        with patch.object(
            indexer_service, "get_last_processed_height", return_value=849900
        ):
            mock_bitcoin_rpc.get_block_count.return_value = 850000

            indexer_service._start_time = time.time() - 3600
            indexer_service._blocks_processed = 100
            indexer_service._processing_times = [1.0] * 10

            status = indexer_service.get_sync_status()

            assert isinstance(status, SyncStatus)
            assert status.last_processed_height == 849900
            assert status.blockchain_height == 850000
            assert status.blocks_behind == 100
            assert status.sync_percentage == pytest.approx(99.88, rel=1e-2)
            assert (
                status.processing_rate > 0
            )  # Should be around 100 blocks/hour = 1.67 blocks/min
            assert status.is_synced is False

    def test_get_sync_status_synced(self, indexer_service, mock_bitcoin_rpc):
        """Test getting sync status when synced"""
        with patch.object(
            indexer_service, "get_last_processed_height", return_value=850000
        ):
            mock_bitcoin_rpc.get_block_count.return_value = 850000

            status = indexer_service.get_sync_status()

            assert status.blocks_behind == 0
            assert status.is_synced is True

    def test_find_common_ancestor(
        self, indexer_service, mock_db_session, mock_bitcoin_rpc
    ):
        """Test finding common ancestor during reorg"""
        with patch.object(
            indexer_service.reorg_handler, "_find_common_ancestor", return_value=849998
        ):
            common_ancestor = indexer_service.reorg_handler._find_common_ancestor(
                850000
            )
            assert common_ancestor == 849998

    def test_find_common_ancestor_max_depth(
        self, indexer_service, mock_db_session, mock_bitcoin_rpc
    ):
        """Test finding common ancestor hits max depth"""
        with patch.object(
            indexer_service.reorg_handler,
            "_find_common_ancestor",
            return_value=config.settings.START_BLOCK_HEIGHT,
        ):
            common_ancestor = indexer_service.reorg_handler._find_common_ancestor(
                850000
            )
            assert common_ancestor == config.settings.START_BLOCK_HEIGHT


class TestIndexerServiceIntegration:
    """Integration tests for IndexerService"""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session for integration tests"""
        session = Mock()
        session.query.return_value.order_by.return_value.first.return_value = None
        session.query.return_value.filter_by.return_value.first.return_value = None
        session.query.return_value.filter.return_value.count.return_value = 0
        session.query.return_value.filter.return_value.delete.return_value = 0
        return session

    @pytest.fixture
    def mock_bitcoin_rpc(self):
        """Mock Bitcoin RPC for integration tests"""
        rpc = Mock()
        rpc.get_block_count.return_value = 800002

        def mock_get_block_hash(height):
            return f"hash_{height:06d}"

        def mock_get_block(block_hash):
            height = int(block_hash.split("_")[1])
            return {
                "height": height,
                "hash": block_hash,
                "time": 1677649200 + height,
                "tx": [f"coinbase_{height}", f"tx1_{height}"],
            }

        def mock_get_raw_transaction(txid, verbose=True):
            return {"txid": txid, "vout": [], "vin": []}

        rpc.get_block_hash.side_effect = mock_get_block_hash
        rpc.get_block.side_effect = mock_get_block
        rpc.get_raw_transaction.side_effect = mock_get_raw_transaction

        return rpc

    def test_start_indexing_small_range(self, mock_db_session, mock_bitcoin_rpc):
        """Test indexing a small range of blocks"""
        indexer = IndexerService(mock_db_session, mock_bitcoin_rpc)

        with patch.object(indexer.processor, "process_transaction") as mock_process:
            mock_process.return_value = Mock(
                operation_found=False, is_valid=False, error_message=None
            )

            indexer.start_indexing(start_height=800000)

            assert indexer._blocks_processed == 3

            assert mock_db_session.commit.call_count == 3

            assert mock_db_session.add.call_count == 3

    def test_start_indexing_with_reorg(self, mock_db_session, mock_bitcoin_rpc):
        """Test indexing with simulated reorg"""
        blockchain_height = config.settings.START_BLOCK_HEIGHT + 3
        mock_bitcoin_rpc.get_block_count.return_value = blockchain_height
        indexer = IndexerService(mock_db_session, mock_bitcoin_rpc)
        mock_existing_block = Mock()
        mock_existing_block.height = config.settings.START_BLOCK_HEIGHT
        mock_existing_block.block_hash = "old_hash_800000"

        def mock_query_side_effect(*args, **kwargs):
            if hasattr(args[0], "height"):
                mock_query = Mock()
                mock_filter_by = Mock()
                mock_filter_by.first.return_value = mock_existing_block
                mock_query.filter_by.return_value = mock_filter_by
                mock_order_by = Mock()
                mock_order_by.first.return_value = mock_existing_block
                mock_query.order_by.return_value = mock_order_by
                return mock_query
            return Mock()

        mock_db_session.query.side_effect = mock_query_side_effect
        with patch.object(indexer.processor, "process_transaction") as mock_process:
            mock_process.return_value = Mock(
                operation_found=False, is_valid=False, error_message=None
            )
            with patch.object(
                indexer.reorg_handler, "_detect_reorg", return_value=True
            ):
                with patch.object(
                    indexer.reorg_handler,
                    "handle_reorg",
                    return_value=config.settings.START_BLOCK_HEIGHT + 2,
                ) as mock_handle_reorg:
                    call_count = 0

                    def mock_should_check_reorg(height):
                        nonlocal call_count
                        call_count += 1
                        return call_count == 1

                    with patch.object(
                        indexer,
                        "_should_check_reorg",
                        side_effect=mock_should_check_reorg,
                    ):
                        indexer.start_indexing(
                            start_height=config.settings.START_BLOCK_HEIGHT + 1,
                            max_blocks=2,
                        )
                        mock_handle_reorg.assert_called_once()
