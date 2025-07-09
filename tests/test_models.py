from datetime import datetime

from src.models.balance import Balance
from src.models.block import ProcessedBlock
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation


def test_models_import():
    """Test that all models can be imported"""
    assert Deploy is not None
    assert Balance is not None
    assert BRC20Operation is not None
    assert ProcessedBlock is not None


def test_deploy_model():
    """Test Deploy model creation"""
    deploy = Deploy(
        ticker="TEST",
        max_supply="1000000",
        limit_per_op="1000",
        deploy_txid="abc123",
        deploy_height=800000,
        deploy_timestamp=datetime.now(),
    )
    assert deploy.ticker == "TEST"
    assert deploy.max_supply == "1000000"
    assert deploy.limit_per_op == "1000"
    assert deploy.deploy_txid == "abc123"
    assert deploy.deploy_height == 800000


def test_balance_model():
    """Test Balance model creation"""
    balance = Balance(
        address="bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        ticker="TEST",
        balance="5000",
    )
    assert balance.address == "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"
    assert balance.ticker == "TEST"
    assert balance.balance == "5000"


def test_brc20_operation_model():
    """Test BRC20Operation model creation"""
    operation = BRC20Operation(
        txid="def456",
        vout_index=0,
        operation="mint",
        ticker="TEST",
        amount="1000",
        from_address=None,
        to_address="bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        block_height=800001,
        block_hash="000000000000000000000123",
        tx_index=1,
        timestamp=datetime.now(),
        is_valid=True,
        error_code=None,
        error_message=None,
        raw_op_return="6a4c50...",
        parsed_json='{"p":"brc-20","op":"mint","tick":"TEST","amt":"1000"}',
    )
    assert operation.txid == "def456"
    assert operation.operation == "mint"
    assert operation.ticker == "TEST"
    assert operation.amount == "1000"
    assert operation.is_valid is True


def test_brc20_operation_invalid():
    """Test BRC20Operation model with invalid operation (ticker=NULL)"""
    operation = BRC20Operation(
        txid="ghi789",
        vout_index=0,
        operation="unknown",
        ticker=None,
        amount=None,
        from_address=None,
        to_address=None,
        block_height=800002,
        block_hash="000000000000000000000124",
        tx_index=2,
        timestamp=datetime.now(),
        is_valid=False,
        error_code="INVALID_JSON",
        error_message="Malformed JSON in OP_RETURN",
        raw_op_return="6a4c50...",
        parsed_json=None,
    )
    assert operation.ticker is None
    assert operation.is_valid is False
    assert operation.error_code == "INVALID_JSON"


def test_processed_block_model():
    """Test ProcessedBlock model creation"""
    block = ProcessedBlock(
        height=800000,
        block_hash="000000000000000000000123",
        tx_count=2500,
        brc20_operations_found=15,
        brc20_operations_valid=12,
    )
    assert block.height == 800000
    assert block.block_hash == "000000000000000000000123"
    assert block.tx_count == 2500
    assert block.brc20_operations_found == 15
    assert block.brc20_operations_valid == 12


def test_critical_rules_compliance():
    """Test that models comply with critical rules"""

    deploy = Deploy(
        ticker="TEST",
        max_supply="21000000000000000000",
        limit_per_op="1000000000000000",
        deploy_txid="abc123",
        deploy_height=800000,
        deploy_timestamp=datetime.now(),
    )
    assert isinstance(deploy.max_supply, str)
    assert isinstance(deploy.limit_per_op, str)

    balance = Balance(
        address="bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        ticker="TEST",
        balance="999999999999999999999",
    )
    assert isinstance(balance.balance, str)

    operation = BRC20Operation(
        txid="test123",
        vout_index=0,
        operation="invalid",
        ticker=None,
        amount=None,
        from_address=None,
        to_address=None,
        block_height=800000,
        block_hash="000000000000000000000123",
        tx_index=0,
        timestamp=datetime.now(),
        is_valid=False,
        error_code="EMPTY_TICKER",
        error_message="Empty ticker not allowed",
        raw_op_return="6a4c50...",
        parsed_json=None,
    )
    assert operation.ticker is None
    valid_operation = BRC20Operation(
        txid="test456",
        vout_index=0,
        operation="deploy",
        ticker="0",
        amount=None,
        from_address=None,
        to_address=None,
        block_height=800000,
        block_hash="000000000000000000000123",
        tx_index=1,
        timestamp=datetime.now(),
        is_valid=True,
        error_code=None,
        error_message=None,
        raw_op_return="6a4c50...",
        parsed_json='{"p":"brc-20","op":"deploy","tick":"0","m":"1000"}',
    )
    assert valid_operation.ticker == "0"
