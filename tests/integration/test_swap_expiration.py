"""SKIPPED: SwapPositionStatus. Phase B."""

import pytest

pytestmark = pytest.mark.skip(reason="SwapPositionStatus; Phase B")

from decimal import Decimal
from unittest.mock import MagicMock

from src.services.indexer import IndexerService
from src.models.swap_position import SwapPosition, SwapPositionStatus
from types import MethodType


def test_preblock_expiration_flow(db_session):
    # Minimal harness: instantiate indexer with mocked bitcoin rpc
    bitcoin_rpc = MagicMock()
    indexer = IndexerService(db_session, bitcoin_rpc)

    # Mock DB query for expired positions
    pos = MagicMock(spec=SwapPosition)
    pos.status = SwapPositionStatus.active
    pos.unlock_height = 100
    pos.src_ticker = "LOL"
    pos.amount_locked = Decimal("10")

    q = MagicMock()
    q.filter.return_value.with_for_update.return_value.all.return_value = [pos]

    # Monkeypatch Session.query to return our q chain
    def _query(self, *args, **kwargs):
        return q

    db_session.query = MethodType(_query, db_session)

    block = {"height": 100, "hash": "h", "tx": [], "time": 123}

    # This should run pre-block expiration without raising
    indexer.process_block_transactions(block)


def test_preblock_expiration_rollback_on_error(db_session):
    bitcoin_rpc = MagicMock()
    indexer = IndexerService(db_session, bitcoin_rpc)

    # Position to expire
    pos = MagicMock(spec=SwapPosition)
    pos.status = SwapPositionStatus.active
    pos.unlock_height = 100
    pos.src_ticker = "LOL"
    pos.amount_locked = Decimal("10")
    pos.owner_address = "addr"

    # Query chain
    q = MagicMock()
    q.filter.return_value.with_for_update.return_value.all.return_value = [pos]

    # Monkeypatch session methods
    def _query(self, *args, **kwargs):
        return q

    db_session.query = MethodType(_query, db_session)

    # Force validator to return None deploy to trigger fail-fast and rollback
    indexer.processor.validator.get_deploy_record = MagicMock(return_value=None)

    block = {"height": 100, "hash": "h", "tx": [], "time": 123}

    # Should handle error and not raise
    indexer.process_block_transactions(block)
