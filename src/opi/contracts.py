from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple, List, Callable


@dataclass
class StateUpdateCommand:
    """Base class for all state update commands"""

    pass


@dataclass
class BalanceUpdateCommand(StateUpdateCommand):
    address: str
    ticker: str
    delta: Decimal


@dataclass
class TotalMintedUpdateCommand(StateUpdateCommand):
    ticker: str
    delta: Decimal


@dataclass
class DeployCommand(StateUpdateCommand):
    ticker: str
    deploy_data: Dict[str, Any]


@dataclass
class IntermediateState:
    """Container for block pending state. Only BRC20Processor can modify."""

    balances: Dict[Tuple[str, str], Decimal] = field(default_factory=dict)
    total_minted: Dict[str, Decimal] = field(default_factory=dict)
    deploys: Dict[str, Any] = field(default_factory=dict)


class Context:
    """
    The Security Contract. Provides a sandboxed, read-only "view" or "context"
    of the pending state for a processor to use in its logic.

    This class MUST NOT contain any state-mutating methods.
    """

    def __init__(self, state: IntermediateState, validator: Any):
        self._state = state
        self._validator = validator

    def get_balance(self, address: str, ticker: str) -> Decimal:
        """Get balance with read-only access to intermediate state"""
        key = (address, ticker.upper())
        if key in self._state.balances:
            return self._state.balances[key]
        return self._validator.get_balance(address, ticker, intermediate_balances=self._state.balances)

    def get_total_minted(self, ticker: str) -> Decimal:
        """Get total minted with read-only access to intermediate state"""
        normalized_ticker = ticker.upper()
        if normalized_ticker in self._state.total_minted:
            return self._state.total_minted[normalized_ticker]
        return self._validator.get_total_minted(ticker)

    def get_deploy_record(self, ticker: str) -> Optional[Any]:
        """Get deploy record with read-only access to intermediate state"""
        normalized_ticker = ticker.upper()
        if normalized_ticker in self._state.deploys:
            return self._state.deploys[normalized_ticker]
        return self._validator.get_deploy_record(ticker)


@dataclass(frozen=True)
class State:
    """
    The primary Data Contract for returning results.
    It is an immutable directive describing the desired state changes and
    new database objects to be persisted.
    """

    orm_objects: List[Any] = field(default_factory=list)
    state_mutations: List[Callable[["IntermediateState"], None]] = field(default_factory=list)


# Backward compatibility aliases
ReadOnlyStateView = Context
