"""
Tests for BRC-20 validator functionality.
"""

import os
import sys
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from src.services.validator import BRC20Validator  # noqa: E402
from src.utils.exceptions import BRC20ErrorCodes  # noqa: E402


class TestBRC20Validator:
    """Test BRC-20 validation functionality"""

    def setup_method(self):
        """Setup test fixtures"""
        self.mock_db_session = Mock()
        self.validator = BRC20Validator(self.mock_db_session)

    def test_validate_deploy_new_ticker(self):
        """Test valid deploy validation for new ticker"""
        mock_query = self.mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = None

        operation = {"tick": "OPQT", "m": "21000000", "l": "1000"}

        result = self.validator.validate_deploy(operation)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_validate_deploy_existing_ticker(self):
        """Test deploy validation for existing ticker (should fail)"""
        existing_deploy = Mock()
        mock_query = self.mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = existing_deploy

        operation = {"tick": "OPQT", "m": "21000000", "l": "1000"}

        result = self.validator.validate_deploy(operation)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.TICKER_ALREADY_EXISTS
        assert "already deployed" in result.error_message

    def test_validate_deploy_invalid_max_supply(self):
        """Test deploy with invalid max supply"""
        mock_query = self.mock_db_session.query.return_value
        mock_query.filter.return_value.first.return_value = None

        operation = {"tick": "OPQT", "m": "invalid", "l": "1000"}

        result = self.validator.validate_deploy(operation)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.INVALID_AMOUNT
        assert "Invalid max supply" in result.error_message

    def test_validate_mint_valid(self):
        """Test valid mint validation"""
        mock_deploy = Mock()
        mock_deploy.limit_per_op = "1000"
        mock_deploy.max_supply = "21000000"

        mock_query = self.mock_db_session.query.return_value
        mock_query.filter.return_value.scalar.return_value = 1000000

        operation = {"tick": "OPQT", "amt": "500"}

        current_supply = "1000000"

        result = self.validator.validate_mint(operation, mock_deploy, current_supply)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_validate_mint_no_deploy(self):
        """Test mint validation when ticker not deployed"""
        operation = {"tick": "OPQT", "amt": "500"}

        current_supply = "0"

        result = self.validator.validate_mint(operation, None, current_supply)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.TICKER_NOT_DEPLOYED
        assert "not deployed" in result.error_message

    def test_validate_mint_exceeds_limit(self):
        """Test mint validation when amount exceeds limit - CRITICAL RULE"""
        mock_deploy = Mock()
        mock_deploy.limit_per_op = "1000"
        mock_deploy.max_supply = "21000000"

        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            1000000
        )

        operation = {"tick": "OPQT", "amt": "2000"}

        current_supply = "1000000"

        result = self.validator.validate_mint(operation, mock_deploy, current_supply)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.EXCEEDS_MINT_LIMIT
        assert "exceeds limit" in result.error_message

    def test_validate_mint_exceeds_max_supply(self):
        """Test mint validation when would exceed max supply"""
        mock_deploy = Mock()
        mock_deploy.limit_per_op = "1000"
        mock_deploy.max_supply = "21000000"

        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            20999999
        )

        operation = {"tick": "OPQT", "amt": "500"}

        current_supply = "20999999"

        result = self.validator.validate_mint(operation, mock_deploy, current_supply)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.EXCEEDS_MAX_SUPPLY
        assert "exceed max supply" in result.error_message

    def test_validate_transfer_valid(self):
        """Test valid transfer validation"""
        mock_deploy = Mock()

        operation = {"tick": "OPQT", "amt": "250"}

        sender_balance = "1000"

        result = self.validator.validate_transfer(
            operation, sender_balance, mock_deploy
        )

        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_validate_transfer_insufficient_balance(self):
        """Test transfer validation with insufficient balance"""
        mock_deploy = Mock()

        operation = {"tick": "OPQT", "amt": "1500"}

        sender_balance = "1000"

        result = self.validator.validate_transfer(
            operation, sender_balance, mock_deploy
        )

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.INSUFFICIENT_BALANCE
        assert "Insufficient balance" in result.error_message

    def test_validate_transfer_no_deploy(self):
        """Test transfer validation when ticker not deployed"""
        operation = {"tick": "OPQT", "amt": "250"}

        sender_balance = "1000"

        result = self.validator.validate_transfer(operation, sender_balance, None)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.TICKER_NOT_DEPLOYED
        assert "not deployed" in result.error_message

    def test_validate_transfer_can_exceed_mint_limit(self):
        """Test transfer can exceed mint limit - CRITICAL RULE"""
        mock_deploy = Mock()
        mock_deploy.limit_per_op = "100"

        operation = {"tick": "OPQT", "amt": "500"}

        sender_balance = "1000"

        result = self.validator.validate_transfer(
            operation, sender_balance, mock_deploy
        )

        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_validate_output_addresses_valid(self):
        """Test output address validation with valid outputs"""
        tx_outputs = [
            {
                "scriptPubKey": {
                    "type": "pubkeyhash",
                    "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                },
                "value": 0.001,
            },
            {"scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
        ]

        result = self.validator.validate_output_addresses(tx_outputs)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_validate_output_addresses_no_standard_outputs(self):
        """Test output address validation with no standard outputs"""
        tx_outputs = [{"scriptPubKey": {"type": "nulldata", "hex": "6a..."}}]

        result = self.validator.validate_output_addresses(tx_outputs)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.NO_STANDARD_OUTPUT
        assert "No standard outputs" in result.error_message

    def test_get_first_standard_output_address(self):
        """Test getting first standard output address"""
        tx_outputs = [
            {"scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
            {
                "scriptPubKey": {
                    "type": "pubkeyhash",
                    "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                },
                "value": 0.001,
            },
            {
                "scriptPubKey": {
                    "type": "pubkeyhash",
                    "addresses": ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"],
                },
                "value": 0.002,
            },
        ]

        address = self.validator.get_first_standard_output_address(tx_outputs)

        assert address == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

    def test_get_current_supply(self):
        """Test getting current supply"""
        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            1000000
        )
        self.mock_db_session.func = Mock()
        self.mock_db_session.BigInteger = Mock()

        supply = self.validator.get_current_supply("OPQT")

        assert supply == "1000000"

    def test_get_balance(self):
        """Test getting balance for address and ticker"""
        mock_balance = Mock()
        mock_balance.balance = "500"
        self.mock_db_session.query.return_value.filter.return_value.first.return_value = (  # noqa: E501
            mock_balance
        )

        balance = self.validator.get_balance(
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "OPQT"
        )

        assert balance == "500"

    def test_get_balance_not_found(self):
        """Test getting balance when record not found"""
        self.mock_db_session.query.return_value.filter.return_value.first.return_value = (  # noqa: E501
            None
        )

        balance = self.validator.get_balance(
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "OPQT"
        )

        assert balance == "0"

    def test_get_deploy_record(self):
        """Test getting deploy record"""
        mock_deploy = Mock()
        self.mock_db_session.query.return_value.filter.return_value.first.return_value = (  # noqa: E501
            mock_deploy
        )

        deploy = self.validator.get_deploy_record("OPQT")

        assert deploy == mock_deploy

    def test_validate_complete_operation_deploy(self):
        """Test complete operation validation for deploy"""
        self.mock_db_session.query.return_value.filter.return_value.first.return_value = (  # noqa: E501
            None
        )

        operation = {"op": "deploy", "tick": "OPQT", "m": "21000000", "l": "1000"}

        tx_outputs = [
            {
                "scriptPubKey": {
                    "type": "pubkeyhash",
                    "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                },
                "value": 0.001,
            }
        ]

        result = self.validator.validate_complete_operation(operation, tx_outputs)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_validate_mint_overflow_exact_case(self):
        """Test the exact failing OPQT transaction scenario"""

        mock_deploy = Mock()
        mock_deploy.max_supply = "21000000"
        mock_deploy.limit_per_op = "1000"

        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            20999624
        )

        operation = {"tick": "OPQT", "amt": "1000"}

        result = self.validator.validate_mint(operation, mock_deploy, "20999624")

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.EXCEEDS_MAX_SUPPLY
        assert "624" in result.error_message
        assert "Mint would exceed max supply" in result.error_message

    def test_validate_mint_overflow_just_under_limit(self):
        """Test mint that exactly reaches max supply"""

        mock_deploy = Mock()
        mock_deploy.max_supply = "21000000"
        mock_deploy.limit_per_op = "1000"

        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            20999624
        )

        operation = {"tick": "OPQT", "amt": "376"}

        result = self.validator.validate_mint(operation, mock_deploy, "20999624")

        assert result.is_valid is True
        assert result.error_code is None

    def test_validate_mint_overflow_at_limit(self):
        """Test mint when already at max supply"""

        mock_deploy = Mock()
        mock_deploy.max_supply = "21000000"
        mock_deploy.limit_per_op = "1000"

        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            21000000
        )

        operation = {"tick": "OPQT", "amt": "1"}

        result = self.validator.validate_mint(operation, mock_deploy, "21000000")

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.EXCEEDS_MAX_SUPPLY

    def test_get_total_minted_calculation(self):
        """Test total minted calculation from database"""
        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            5000000
        )

        total = self.validator.get_total_minted("OPQT")

        assert total == "5000000"
        self.mock_db_session.query.assert_called()

    def test_get_total_minted_no_mints(self):
        """Test total minted when no mints exist"""
        self.mock_db_session.query.return_value.filter.return_value.scalar.return_value = (  # noqa: E501
            None
        )

        total = self.validator.get_total_minted("NEWTOKEN")

        assert total == "0"
