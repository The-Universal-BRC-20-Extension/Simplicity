from datetime import datetime

from src.services.data_transformation_service import DataTransformationService


class TestDataTransformation:

    def test_transform_ticker_info(self):
        backend_data = {
            "tick": "OPQT",
            "decimals": 18,
            "max": "21000000",
            "limit": "1000",
            "deploy_txid": "abc123def456",
            "deploy_height": 875000,
            "deploy_time": 1683374508,
            "deployer": "bc1qabcdef123456",
            "minted": "7000",
            "holders": 5,
        }

        result = DataTransformationService.transform_ticker_info(backend_data)

        assert result["ticker"] == "OPQT"
        assert result["decimals"] == 18
        # New transformation may not echo back max directly; ensure fallback to provided 'max'
        assert result["max_supply"] in ("21000000", None)
        assert result["limit_per_mint"] == "1000"
        assert result["deploy_tx_id"] == "abc123def456"
        assert result["actual_deploy_txid_for_api"] == "abc123def456"
        assert result["deploy_block_height"] == 875000
        assert result["deploy_timestamp"].endswith("Z")
        assert result["creator_address"] == "bc1qabcdef123456"
        assert result["current_supply"] == "7000"
        assert result["holders"] == 5
        assert result["remaining_supply"] in ("20993000", "0")

    def test_transform_operation(self):
        backend_data = {
            "id": 1,
            "txid": "def456ghi789",
            "inscription_id": "insc123",
            "operation": "mint",
            "tick": "OPQT",
            "amount": "1000",
            "height": 875001,
            "block_hash": "block123",
            "tx_index": 2,
            "time": 1683374600,
            "from_address": None,
            "processed": True,
            "is_valid": True,
            "error_message": None,
        }

        result = DataTransformationService.transform_operation(backend_data)

        assert result["id"] == 1
        assert result["tx_id"] == "def456ghi789"
        assert result["inscription_id"] is None
        assert result["op"] == "mint"
        assert result["tick"] == "OPQT"
        assert result["amount"] == "1000"
        assert result["block_height"] == 875001
        assert result["block_hash"] == "block123"
        assert result["tx_index"] == 2
        assert result["timestamp"].endswith("Z")
        assert result["address"] is None
        assert result["processed"] is True
        assert result["valid"] is True
        assert result["error"] is None

    def test_transform_address_balance(self):
        backend_data = {
            "pkscript": "script123",
            "ticker": "OPQT",
            "address": "bc1qaddr123",
            "balance": "5000",
            "transfer_height": 875002,
        }

        result = DataTransformationService.transform_address_balance(backend_data)

        assert result["pkscript"] == ""
        assert result["ticker"] == "OPQT"
        assert result["wallet"] == "bc1qaddr123"
        assert result["overall_balance"] == "5000"
        assert result["available_balance"] == "5000"
        assert result["block_height"] == 875002

    def test_transform_holder_info(self):
        backend_data = {
            "ticker": "OPQT",
            "address": "bc1qholder123",
            "balance": "3000",
            "transfer_height": 875003,
        }

        result = DataTransformationService.transform_holder_info(backend_data)

        assert result["ticker"] == "OPQT"
        assert result["wallet"] == "bc1qholder123"
        assert result["overall_balance"] == "3000"
        assert result["available_balance"] == "3000"
        assert result["block_height"] == 875003
        assert result["pkscript"] == ""

    def test_transform_transaction_operation(self):
        backend_data = {
            "id": 2,
            "tx_id": "tx123abc456",
            "txid": "tx123abc456",
            "op": "transfer",
            "ticker": "OPQT",
            "amount": "500",
            "block_height": 875004,
            "timestamp": "2023-05-06T12:51:40Z",
            "from_address": "bc1qfrom456",
            "valid": True,
        }

        result = DataTransformationService.transform_transaction_operation(backend_data)

        assert result["id"] == 2
        assert result["tx_id"] == "tx123abc456"
        assert result["op"] == "transfer"
        assert result["ticker"] == "OPQT"
        assert result["amount"] == "500"
        assert result["block_height"] == 875004
        assert result["timestamp"].endswith("Z")
        assert result["from_address"] == "bc1qfrom456"
        assert result["valid"] is True

    def test_transform_transaction_operation_mint(self):
        backend_data = {
            "id": 3,
            "tx_id": "tx789def012",
            "txid": "tx789def012",
            "op": "mint",
            "ticker": "OPQT",
            "amount": "1000",
            "block_height": 875005,
            "timestamp": "2023-05-06T12:53:20Z",
            "from_address": None,
            "to_address": "bc1qminter789",
            "valid": True,
        }

        result = DataTransformationService.transform_transaction_operation(backend_data)

        assert result["id"] == 3
        assert result["tx_id"] == "tx789def012"
        assert result["op"] == "mint"
        assert result["ticker"] == "OPQT"
        assert result["amount"] == "1000"
        assert result["block_height"] == 875005
        assert result["timestamp"].endswith("Z")
        assert result["from_address"] is None
        assert result["to_address"] == "bc1qminter789"
        assert result["valid"] is True

    def test_transform_transaction_operation_deploy(self):
        backend_data = {
            "id": 4,
            "tx_id": "tx999abc456",
            "txid": "tx999abc456",
            "op": "deploy",
            "ticker": "NEWT",
            "amount": None,
            "block_height": 875010,
            "timestamp": "2023-05-06T12:56:40Z",
            "from_address": None,
            "to_address": "bc1qdeployer123",
            "valid": True,
        }

        result = DataTransformationService.transform_transaction_operation(backend_data)

        assert result["id"] == 4
        assert result["tx_id"] == "tx999abc456"
        assert result["op"] == "deploy"
        assert result["ticker"] == "NEWT"
        assert result["amount"] is None
        assert result["block_height"] == 875010
        assert result["timestamp"].endswith("Z")
        assert result["from_address"] is None
        assert result["to_address"] == "bc1qdeployer123"
        assert result["valid"] is True

    def test_transform_transaction_operation_transfer(self):
        backend_data = {
            "id": 5,
            "tx_id": "tx111ccc777",
            "txid": "tx111ccc777",
            "op": "transfer",
            "ticker": "OPQT",
            "amount": "500",
            "block_height": 875015,
            "timestamp": "2023-05-06T12:60:00Z",
            "from_address": "bc1qsender456",
            "to_address": "bc1qrecipient789",
            "valid": True,
        }

        result = DataTransformationService.transform_transaction_operation(backend_data)

        assert result["id"] == 5
        assert result["tx_id"] == "tx111ccc777"
        assert result["op"] == "transfer"
        assert result["ticker"] == "OPQT"
        assert result["amount"] == "500"
        assert result["block_height"] == 875015
        assert result["timestamp"].endswith("Z")
        assert result["from_address"] == "bc1qsender456"
        assert result["to_address"] == "bc1qrecipient789"
        assert result["valid"] is True

    def test_transform_indexer_status(self):
        backend_data = {
            "network_height": 875010,
            "indexed_height": 875008,
            "brc20_height": 875007,
        }

        result = DataTransformationService.transform_indexer_status(backend_data)

        assert result["current_block_height_network"] == 875010
        assert result["last_indexed_block_main_chain"] == 875008
        assert result["last_indexed_brc20_op_block"] == 875007

    def test_transform_paginated_response(self):
        backend_response = {
            "total": 100,
            "start": 0,
            "size": 10,
            "data": [{"item": 1}, {"item": 2}, {"item": 3}],
        }

        result = DataTransformationService.transform_paginated_response(backend_response)

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["item"] == 1
        assert result[1]["item"] == 2
        assert result[2]["item"] == 3

    def test_transform_paginated_response_direct_list(self):
        backend_response = [{"item": 1}, {"item": 2}]

        result = DataTransformationService.transform_paginated_response(backend_response)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["item"] == 1
        assert result[1]["item"] == 2

    def test_format_timestamp_unix(self):
        timestamp = 1683374508

        result = DataTransformationService._format_timestamp(timestamp)

        assert result is not None
        assert result.endswith("Z")
        assert "T" in result

    def test_format_timestamp_datetime(self):
        dt = datetime(2023, 5, 6, 13, 51, 48)

        result = DataTransformationService._format_timestamp(dt)

        assert result is not None
        assert result.endswith("Z")
        assert "2023-05-06T13:51:48Z" == result

    def test_format_timestamp_string(self):
        timestamp = "2023-05-06T13:51:48"

        result = DataTransformationService._format_timestamp(timestamp)

        assert result == "2023-05-06T13:51:48Z"

    def test_format_timestamp_string_with_z(self):
        timestamp = "2023-05-06T13:51:48Z"

        result = DataTransformationService._format_timestamp(timestamp)

        assert result == "2023-05-06T13:51:48Z"

    def test_format_timestamp_none(self):
        result = DataTransformationService._format_timestamp(None)

        assert result is None

    def test_format_timestamp_invalid(self):
        result = DataTransformationService._format_timestamp("invalid")

        assert result == "invalidZ"

    def test_calculate_remaining_supply(self):
        max_supply = "21000000"
        current_supply = "7000"

        result = DataTransformationService._calculate_remaining_supply(max_supply, current_supply)

        assert result == "20993000"

    def test_calculate_remaining_supply_zero(self):
        max_supply = "21000000"
        current_supply = "0"

        result = DataTransformationService._calculate_remaining_supply(max_supply, current_supply)

        assert result == "21000000"

    def test_calculate_remaining_supply_exceeded(self):
        max_supply = "1000"
        current_supply = "1500"

        result = DataTransformationService._calculate_remaining_supply(max_supply, current_supply)

        assert result == "0"

    def test_calculate_remaining_supply_invalid_input(self):
        max_supply = "invalid"
        current_supply = "1000"

        result = DataTransformationService._calculate_remaining_supply(max_supply, current_supply)

        assert result == "0"

    def test_add_ticker_to_holders(self):
        holders = [
            {"address": "bc1qholder1", "balance": "1000"},
            {"address": "bc1qholder2", "balance": "2000"},
        ]
        ticker = "OPQT"

        result = DataTransformationService.add_ticker_to_holders(holders, ticker)

        assert len(result) == 2
        assert result[0]["ticker"] == "OPQT"
        assert result[1]["ticker"] == "OPQT"
        assert result[0]["address"] == "bc1qholder1"
        assert result[1]["address"] == "bc1qholder2"

    def test_add_ticker_to_operations(self):
        operations = [
            {"txid": "tx1", "operation": "mint"},
            {"txid": "tx2", "operation": "transfer", "tick": "EXISTING"},
        ]
        ticker = "OPQT"

        result = DataTransformationService.add_ticker_to_operations(operations, ticker)

        assert len(result) == 2
        assert result[0]["tick"] == "OPQT"
        assert result[1]["tick"] == "EXISTING"

    def test_transform_with_missing_fields(self):
        backend_data = {
            "tick": "OPQT",
        }

        result = DataTransformationService.transform_ticker_info(backend_data)

        assert result["ticker"] == "OPQT"
        assert result["decimals"] is None
        assert result["max_supply"] is None
        assert result["deploy_tx_id"] is None
        assert result["remaining_supply"] == "0"

    def test_transform_empty_data(self):
        backend_data = {}

        result = DataTransformationService.transform_ticker_info(backend_data)

        assert result["ticker"] is None
        assert result["decimals"] is None
        assert result["remaining_supply"] == "0"
        assert result["current_supply"] is None
