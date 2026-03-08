"""
Tests for marketplace transfer prioritization functionality in IndexerService.
"""

import pytest
from unittest.mock import Mock, patch
from src.services.indexer import IndexerService
from src.utils.exceptions import TransferType


@pytest.fixture
def mock_indexer():
    """Provides a mocked IndexerService instance."""
    db_session = Mock()
    bitcoin_rpc = Mock()

    # Mock the processor and its methods
    mock_processor = Mock()

    # The key is to mock the classification method
    def classify_side_effect(tx_data, block_height):
        if "marketplace" in tx_data.get("txid", ""):
            return TransferType.MARKETPLACE
        return TransferType.SIMPLE

    mock_processor.classify_transfer_type.side_effect = classify_side_effect

    # Mock the parser to return some data to trigger classification
    def parse_side_effect(hex_data):
        # A simple mock to indicate if it's a brc20 op or not
        if hex_data:
            return {"success": True, "data": {"op": "transfer"}}
        return {"success": False}

    mock_parser = Mock()
    mock_parser.extract_op_return_data.return_value = ("somehex", 0)
    mock_parser.parse_brc20_operation.side_effect = parse_side_effect
    mock_processor.parser = mock_parser

    with patch("src.services.indexer.BRC20Processor", return_value=mock_processor):
        indexer = IndexerService(db_session, bitcoin_rpc)
        # We also need to mock the processor instance on the indexer
        indexer.processor = mock_processor
        yield indexer


def test_processing_order_is_prioritized(mock_indexer):
    """
    Verify that marketplace transactions are processed before simple transactions,
    regardless of their original position in the block.
    """
    # Mock block data with mixed transaction types
    block_data = {
        "height": 800000,
        "hash": "a_block_hash",
        "time": 1677628800,
        "tx": [
            {"txid": "coinbase_tx", "vout": []},  # Coinbase
            {
                "txid": "simple_tx_1",
                "vout": [
                    {
                        "scriptPubKey": {
                            "type": "nulldata",
                            "hex": "6a4c547b2270223a226272632d3230222c226f70223a227472616e73666572222c227469636b223a2254455354222c22616d74223a22313030227d",
                        }
                    }
                ],
            },
            {
                "txid": "marketplace_tx_1",
                "vout": [
                    {
                        "scriptPubKey": {
                            "type": "nulldata",
                            "hex": "6a4c547b2270223a226272632d3230222c226f70223a227472616e73666572222c227469636b223a2254455354222c22616d74223a22323030227d",
                        }
                    }
                ],
            },
            {
                "txid": "simple_tx_2",
                "vout": [
                    {
                        "scriptPubKey": {
                            "type": "nulldata",
                            "hex": "6a4c547b2270223a226272632d3230222c226f70223a227472616e73666572222c227469636b223a2254455354222c22616d74223a22333030227d",
                        }
                    }
                ],
            },
            {
                "txid": "marketplace_tx_2",
                "vout": [
                    {
                        "scriptPubKey": {
                            "type": "nulldata",
                            "hex": "6a4c547b2270223a226272632d3230222c226f70223a227472616e73666572222c227469636b223a2254455354222c22616d74223a22343030227d",
                        }
                    }
                ],
            },
        ],
    }

    # Mock the transaction processing result
    mock_indexer.processor.process_transaction.return_value = Mock(operation_found=True, is_valid=True)

    # Execute the method to be tested
    mock_indexer.process_block_transactions(block_data)

    # --- Verification ---
    # Check the calls to process_transaction to confirm the execution order
    calls = mock_indexer.processor.process_transaction.call_args_list

    # Extract the txid from the first argument (tx_data) of each call
    # CORRECTION: calls[0] is a tuple of (args, kwargs), so we need args[0]
    processed_txids_order = [call[0][0]["txid"] for call in calls]

    # Expected order: marketplace transactions first, then simple transactions
    expected_order = [
        "marketplace_tx_1",
        "marketplace_tx_2",
        "simple_tx_1",
        "simple_tx_2",
    ]

    assert processed_txids_order == expected_order, (
        f"Expected marketplace transactions to be processed first. "
        f"Got: {processed_txids_order}, Expected: {expected_order}"
    )


def test_results_are_in_original_block_order(mock_indexer):
    """
    Verify that the final list of results is sorted back into the original
    transaction order of the block.
    """
    # Mock block data
    transactions = [
        {"txid": "coinbase_tx"},
        {"txid": "simple_tx_1"},
        {"txid": "marketplace_tx_1"},
    ]
    block_data = {
        "height": 800000,
        "hash": "a_block_hash",
        "time": 1677628800,
        "tx": transactions,
    }

    # Mock process_transaction to return a mock result that includes the txid
    def process_transaction_side_effect(tx_data, **kwargs):
        mock_result = Mock()
        # Attach txid to the mock_result to identify it later
        mock_result.txid = tx_data["txid"]
        return mock_result

    mock_indexer.processor.process_transaction.side_effect = process_transaction_side_effect

    # Execute
    final_results = mock_indexer.process_block_transactions(block_data)

    # --- Verification ---
    # Extract txids from the final returned results
    final_result_order_txids = [res.txid for res in final_results]

    # The final order should match the original order in the block (minus coinbase)
    expected_final_order = ["simple_tx_1", "marketplace_tx_1"]

    assert final_result_order_txids == expected_final_order
    print("\nFinal result order is correct (matches original block order).")
    for i, txid in enumerate(expected_final_order):
        print(f"  {i+1}. {txid}")
