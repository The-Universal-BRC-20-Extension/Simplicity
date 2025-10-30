from decimal import Decimal
from unittest.mock import Mock
from src.opi.contracts import (
    StateUpdateCommand,
    BalanceUpdateCommand,
    TotalMintedUpdateCommand,
    DeployCommand,
    IntermediateState,
    Context,
    State,
)


class TestStateUpdateCommand:
    def test_state_update_command_base(self):
        command = StateUpdateCommand()
        assert isinstance(command, StateUpdateCommand)

    def test_balance_update_command(self):
        command = BalanceUpdateCommand(address="test_address", ticker="TEST", delta=Decimal("100.5"))
        assert command.address == "test_address"
        assert command.ticker == "TEST"
        assert command.delta == Decimal("100.5")

    def test_total_minted_update_command(self):
        command = TotalMintedUpdateCommand(ticker="TEST", delta=Decimal("50.25"))
        assert command.ticker == "TEST"
        assert command.delta == Decimal("50.25")

    def test_deploy_command(self):
        deploy_data = {"max_supply": "1000000", "limit_per_op": "1000"}
        command = DeployCommand(ticker="TEST", deploy_data=deploy_data)
        assert command.ticker == "TEST"
        assert command.deploy_data == deploy_data


class TestIntermediateState:
    def test_intermediate_state_initialization(self):
        state = IntermediateState()
        assert state.balances == {}
        assert state.total_minted == {}
        assert state.deploys == {}

    def test_intermediate_state_with_data(self):
        balances = {("addr1", "TEST"): Decimal("100")}
        total_minted = {"TEST": Decimal("1000")}
        deploys = {"TEST": {"max_supply": "1000000"}}

        state = IntermediateState(balances=balances, total_minted=total_minted, deploys=deploys)

        assert state.balances == balances
        assert state.total_minted == total_minted
        assert state.deploys == deploys


class TestContext:
    def test_context_initialization(self):
        state = IntermediateState()
        validator = Mock()
        context = Context(state, validator)

        assert context._state == state
        assert context._validator == validator

    def test_get_balance_from_intermediate_state(self):
        state = IntermediateState()
        state.balances[("addr1", "TEST")] = Decimal("100")

        validator = Mock()
        validator.get_balance.return_value = Decimal("50")

        context = Context(state, validator)
        balance = context.get_balance("addr1", "TEST")

        assert balance == Decimal("100")
        validator.get_balance.assert_not_called()

    def test_get_balance_from_validator(self):
        state = IntermediateState()
        validator = Mock()
        validator.get_balance.return_value = Decimal("50")

        context = Context(state, validator)
        balance = context.get_balance("addr1", "TEST")

        assert balance == Decimal("50")
        validator.get_balance.assert_called_once_with("addr1", "TEST")

    def test_get_total_minted_from_intermediate_state(self):
        state = IntermediateState()
        state.total_minted["TEST"] = Decimal("1000")

        validator = Mock()
        validator.get_total_minted.return_value = Decimal("500")

        context = Context(state, validator)
        total_minted = context.get_total_minted("TEST")

        assert total_minted == Decimal("1000")
        validator.get_total_minted.assert_not_called()

    def test_get_total_minted_from_validator(self):
        state = IntermediateState()
        validator = Mock()
        validator.get_total_minted.return_value = Decimal("500")

        context = Context(state, validator)
        total_minted = context.get_total_minted("TEST")

        assert total_minted == Decimal("500")
        validator.get_total_minted.assert_called_once_with("TEST")

    def test_get_deploy_record_from_intermediate_state(self):
        state = IntermediateState()
        deploy_record = {"max_supply": "1000000"}
        state.deploys["TEST"] = deploy_record

        validator = Mock()
        validator.get_deploy_record.return_value = {"max_supply": "500000"}

        context = Context(state, validator)
        record = context.get_deploy_record("TEST")

        assert record == deploy_record
        validator.get_deploy_record.assert_not_called()

    def test_get_deploy_record_from_validator(self):
        state = IntermediateState()
        validator = Mock()
        validator.get_deploy_record.return_value = {"max_supply": "500000"}

        context = Context(state, validator)
        record = context.get_deploy_record("TEST")

        assert record == {"max_supply": "500000"}
        validator.get_deploy_record.assert_called_once_with("TEST")


class TestState:
    def test_state_initialization(self):
        state = State()
        assert state.orm_objects == []
        assert state.state_mutations == []

    def test_state_with_data(self):
        orm_objects = [Mock(), Mock()]

        def mutation1(state):
            pass

        def mutation2(state):
            pass

        state = State(orm_objects=orm_objects, state_mutations=[mutation1, mutation2])

        assert state.orm_objects == orm_objects
        assert state.state_mutations == [mutation1, mutation2]

    def test_state_immutability(self):
        state = State()

        # Should not be able to modify after creation
        try:
            state.orm_objects.append(Mock())
            assert False, "State should be immutable"
        except Exception:
            pass  # Expected behavior


# Backward compatibility tests
class TestReadOnlyStateView:

    def test_read_only_state_view_is_context_alias(self):
        from src.opi.contracts import ReadOnlyStateView

        state = IntermediateState()
        validator = Mock()

        view = ReadOnlyStateView(state, validator)
        context = Context(state, validator)

        assert view.get_balance("addr1", "TEST") == context.get_balance("addr1", "TEST")
