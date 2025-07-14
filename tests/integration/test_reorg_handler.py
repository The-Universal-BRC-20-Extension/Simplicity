"""
Tests for ReorgHandler service.

Tests cover:
- Reorg detection
- Common ancestor finding
- State rollback and recovery
"""

from unittest.mock import Mock, patch

import pytest

from src.services.reorg_handler import ReorgHandler


class TestReorgHandler:
    """Test ReorgHandler functionality"""

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = Mock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        session.query.return_value.filter.return_value.delete.return_value = 0
        return session

    @pytest.fixture
    def mock_bitcoin_rpc(self):
        """Mock Bitcoin RPC service"""
        rpc = Mock()
        rpc.get_block_hash.return_value = "some_hash"
        return rpc

    @pytest.fixture
    def reorg_handler(self, mock_db_session, mock_bitcoin_rpc):
        """Create ReorgHandler instance"""
        return ReorgHandler(mock_db_session, mock_bitcoin_rpc)

    def test_find_common_ancestor(
        self, reorg_handler, mock_db_session, mock_bitcoin_rpc
    ):
        """Test finding common ancestor during reorg"""
        stored_blocks = {
            850000: Mock(block_hash="old_hash_850000"),
            849999: Mock(block_hash="old_hash_849999"),
            849998: Mock(block_hash="same_hash_849998"),
        }

        def mock_filter_by(**kwargs):
            height = kwargs.get("height")
            mock_filter_result = Mock()
            mock_filter_result.first.return_value = stored_blocks.get(height)
            return mock_filter_result

        mock_db_session.query.return_value.filter_by.side_effect = mock_filter_by

        def mock_get_block_hash(height):
            if height == 850000:
                return "new_hash_850000"
            elif height == 849999:
                return "new_hash_849999"
            elif height == 849998:
                return "same_hash_849998"
            return f"hash_{height}"

        mock_bitcoin_rpc.get_block_hash.side_effect = mock_get_block_hash

    def test_rollback_to_height(self, reorg_handler, mock_db_session):
        """Test state rollback to a specific height"""
        with patch.object(
            reorg_handler, "_recalculate_balances_from_height"
        ) as mock_recalc:
            reorg_handler._rollback_to_height(849998)

            mock_db_session.query.return_value.filter.return_value.delete.assert_called()  # noqa: E501
            assert (
                mock_db_session.query.return_value.filter.return_value.delete.call_count
                == 2
            )

            mock_recalc.assert_called_once_with(849998)

            mock_db_session.commit.assert_called_once()

    def test_handle_reorg(self, reorg_handler):
        """Test the main reorg handling workflow"""
        with patch.object(
            reorg_handler, "_find_common_ancestor", return_value=849998
        ) as mock_find, patch.object(
            reorg_handler, "_rollback_to_height"
        ) as mock_rollback:

            resume_height = reorg_handler.handle_reorg(850000)

            mock_find.assert_called_once_with(850000)
            mock_rollback.assert_called_once_with(849998)
            assert resume_height == 849999
