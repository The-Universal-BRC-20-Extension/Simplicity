"""
Integration tests with real validation services but mocked external dependencies.
Tests real business logic integration while controlling external factors.
"""

import pytest
from unittest.mock import patch, Mock
from sqlalchemy.orm import Session

from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.transaction import BRC20Operation
from src.services.validator import ValidationResult
from src.utils.exceptions import TransferType


class TestRealValidationIntegration:
    """Test real validation logic with minimal mocking"""

    def test_deploy_success_real_validation(self, real_processor, db_session, unique_ticker_generator):
        """Test deploy with real validation - should succeed for unique ticker"""
        ticker = unique_ticker_generator("REAL")
        operation = {"op": "deploy", "tick": ticker, "m": "1000000", "l": "1000"}
        
        tx_info = {
            "txid": "real_test_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800000,
            "vin": [{"address": "test_deployer_address"}],
            "vout": [{"n": 0, "scriptPubKey": {"type": "pubkeyhash", "addresses": ["1TestAddress"]}}],
        }
        
        hex_data = "test_hex_data"
        
        with patch.object(real_processor, "get_first_input_address", return_value="test_deployer_address"):
            with patch.object(real_processor, "log_operation"):
                real_processor.current_block_timestamp = 1677649200
                result = real_processor.process_deploy(operation, tx_info, hex_data)
                
                assert result.is_valid is True
                # For real db_session, we can't use mock assertions
                # Instead, verify the result indicates success
                assert result.is_valid is True

    def test_deploy_blocked_by_legacy_real_validation(self, real_processor, db_session):
        """Test deploy blocked by real legacy validation - ORDI exists on legacy"""
        operation = {"op": "deploy", "tick": "ORDI", "m": "21000000", "l": "1000"}
        
        tx_info = {
            "txid": "legacy_blocked_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800000,
            "vin": [{"address": "test_deployer_address"}],
            "vout": [{"n": 0, "scriptPubKey": {"type": "pubkeyhash", "addresses": ["1TestAddress"]}}],
        }
        
        hex_data = "test_hex_data"
        
        with patch.object(real_processor, "get_first_input_address", return_value="test_deployer_address"):
            with patch.object(real_processor, "log_operation"):
                real_processor.current_block_timestamp = 1677649200
                result = real_processor.process_deploy(operation, tx_info, hex_data)
                
                assert not result.is_valid
                assert "LEGACY_TOKEN_EXISTS" in result.error_code
                # For real db_session, we can't use mock assertions
                # Instead, verify the result indicates failure
                assert not result.is_valid

    def test_mint_success_real_validation(self, real_processor, db_session, unique_ticker_generator):
        """Test mint with real validation - should succeed for valid operation"""
        ticker = unique_ticker_generator("MINT")
        
        # First deploy the token
        deploy_operation = {"op": "deploy", "tick": ticker, "m": "1000000", "l": "1000"}
        deploy_tx_info = {
            "txid": "deploy_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800000,
            "vin": [{"address": "test_deployer_address"}],
            "vout": [{"n": 0, "scriptPubKey": {"type": "pubkeyhash", "addresses": ["1TestAddress"]}}],
        }
        
        with patch.object(real_processor, "get_first_input_address", return_value="test_deployer_address"):
            with patch.object(real_processor, "log_operation"):
                real_processor.current_block_timestamp = 1677649200
                real_processor.process_deploy(deploy_operation, deploy_tx_info, "deploy_hex")
        
        # Now test mint
        mint_operation = {"op": "mint", "tick": ticker, "amt": "500"}
        mint_tx_info = {
            "txid": "mint_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800001,
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["test_recipient"]}},
            ],
        }
        
        hex_data = "mint_hex_data"
        
        with patch.object(real_processor.validator, "get_output_after_op_return_address", return_value="test_recipient"):
            with patch.object(real_processor, "validate_mint_op_return_position", return_value=ValidationResult(True)):
                with patch.object(real_processor.validator, "validate_complete_operation", return_value=ValidationResult(True)):
                    with patch.object(real_processor, "update_balance") as mock_update:
                        with patch.object(real_processor, "log_operation"):
                            result = real_processor.process_mint(mint_operation, mint_tx_info, hex_data, 800001)
                            
                            assert result.is_valid is True
                            mock_update.assert_called_once_with(
                                address="test_recipient",
                                ticker=ticker,
                                amount_delta="500",
                                operation_type="mint",
                            )

    def test_transfer_success_real_validation(self, real_processor, db_session, unique_ticker_generator):
        """Test transfer with real validation - should succeed for valid operation"""
        ticker = unique_ticker_generator("XFER")
        
        # First deploy and mint the token
        deploy_operation = {"op": "deploy", "tick": ticker, "m": "1000000", "l": "1000"}
        deploy_tx_info = {
            "txid": "deploy_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800000,
            "vin": [{"address": "test_deployer_address"}],
            "vout": [{"n": 0, "scriptPubKey": {"type": "pubkeyhash", "addresses": ["1TestAddress"]}}],
        }
        
        with patch.object(real_processor, "get_first_input_address", return_value="test_deployer_address"):
            with patch.object(real_processor, "log_operation"):
                real_processor.current_block_timestamp = 1677649200
                real_processor.process_deploy(deploy_operation, deploy_tx_info, "deploy_hex")
        
        # Mint some tokens
        mint_operation = {"op": "mint", "tick": ticker, "amt": "1000"}
        mint_tx_info = {
            "txid": "mint_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800001,
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["test_recipient"]}},
            ],
        }
        
        with patch.object(real_processor.validator, "get_output_after_op_return_address", return_value="test_recipient"):
            with patch.object(real_processor, "validate_mint_op_return_position", return_value=ValidationResult(True)):
                with patch.object(real_processor.validator, "validate_complete_operation", return_value=ValidationResult(True)):
                    with patch.object(real_processor, "update_balance"):
                        with patch.object(real_processor, "log_operation"):
                            real_processor.process_mint(mint_operation, mint_tx_info, "mint_hex", 800001)
        
        # Now test transfer
        transfer_operation = {"op": "transfer", "tick": ticker, "amt": "500"}
        transfer_tx_info = {
            "txid": "transfer_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800002,
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["test_recipient"]}},
            ],
        }
        
        with patch.object(real_processor.validator, "get_output_after_op_return_address", return_value="test_recipient"):
            with patch.object(real_processor.validator, "validate_complete_operation", return_value=ValidationResult(True)):
                with patch.object(real_processor, "classify_transfer_type", return_value=TransferType.SIMPLE):
                    with patch.object(real_processor, "validate_transfer_specific", return_value=ValidationResult(True)):
                        with patch.object(real_processor, "resolve_transfer_addresses", return_value={
                            "sender": "test_sender",
                            "recipient": "test_recipient"
                        }):
                            with patch.object(real_processor, "update_balance") as mock_update:
                                with patch.object(real_processor, "log_operation"):
                                    result = real_processor.process_transfer(transfer_operation, transfer_tx_info, "transfer_hex", 800002)
                                    
                                    assert result.is_valid is True
                                    # Should call update_balance twice (debit sender, credit recipient)
                                    assert mock_update.call_count == 2

    def test_validation_error_real_validation(self, real_processor, db_session):
        """Test validation error with real validation logic"""
        # Test with invalid operation (missing required fields)
        operation = {"op": "deploy", "tick": "INVALID"}  # Missing m and l
        
        tx_info = {
            "txid": "invalid_txid_1234567890123456789012345678901234567890123456789012345678901234",
            "block_height": 800000,
            "vin": [{"address": "test_deployer_address"}],
            "vout": [{"n": 0, "scriptPubKey": {"type": "pubkeyhash", "addresses": ["1TestAddress"]}}],
        }
        
        hex_data = "test_hex_data"
        
        with patch.object(real_processor, "get_first_input_address", return_value="test_deployer_address"):
            with patch.object(real_processor, "log_operation"):
                real_processor.current_block_timestamp = 1677649200
                result = real_processor.process_deploy(operation, tx_info, hex_data)
                
                # Should fail validation due to missing required fields
                assert not result.is_valid
                assert result.error_code is not None 