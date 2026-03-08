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
    block_height: Optional[int] = None
    # Track swap position amount_locked modifications within the block
    # Key: position_id, Value: new amount_locked value
    swap_positions_updates: Dict[int, Decimal] = field(default_factory=dict)

    def preload_balances(self, addresses: List[str], tickers: List[str], validator) -> None:
        """Preload balances for known addresses and tickers from DB."""
        for address in addresses:
            for ticker in tickers:
                key = (address, ticker.upper())
                if key not in self.balances:
                    db_balance = validator.get_balance(address, ticker)
                    self.balances[key] = db_balance


class Context:
    """
    The Security Contract. Provides a sandboxed, read-only "view" or "context"
    of the pending state for a processor to use in its logic.
    """

    def __init__(self, state: IntermediateState, validator: Any):
        self._state = state
        self._validator = validator

    def get_balance(self, address: str, ticker: str) -> Decimal:
        """Get balance with read-only access to intermediate state."""
        import structlog

        logger = structlog.get_logger()

        # REJECT 'Y' uppercase prefix (YTOKEN) - only accept 'y' lowercase (yTOKEN, ytoken)
        if ticker and len(ticker) > 0 and ticker[0] == "y":  # Accept lowercase 'y' only
            normalized_ticker = "y" + ticker[1:].upper()
            key = (address, normalized_ticker)

            if key in self._state.balances:
                cached_balance = self._state.balances[key]
                logger.info(
                    "Context.get_balance returning cached value for yToken",
                    address=address,
                    ticker=ticker,
                    normalized_ticker=normalized_ticker,
                    cached_balance=str(cached_balance),
                    key_repr=repr(key),
                )
                return cached_balance  # Priority 1: In-block mutations

            db_balance = self._validator.get_balance(address, ticker)  # Delegates to Validator for dynamic calc

            return db_balance
        else:
            # Normal token (including YTOKEN which is rejected as yToken)
            normalized_ticker = ticker.upper() if ticker else ticker
            key = (address, normalized_ticker)

            if key in self._state.balances:
                return self._state.balances[key]

            db_balance = self._validator.get_balance(address, ticker)
            self._state.balances[key] = db_balance
            return db_balance

    def get_total_minted(self, ticker: str) -> Decimal:
        """Get total minted with read-only access to intermediate state."""
        # Only Curve staking can create tokens with 'y' prefix
        if ticker and len(ticker) > 0 and ticker[0].lower() == "y":
            normalized_ticker = "y" + ticker[1:].upper()
        else:
            normalized_ticker = ticker.upper()
        if normalized_ticker in self._state.total_minted:
            return self._state.total_minted[normalized_ticker]

        db_total_minted = self._validator.get_total_minted(ticker)
        self._state.total_minted[normalized_ticker] = db_total_minted
        return db_total_minted

    def get_deploy_record(self, ticker: str) -> Optional[Any]:
        """Get deploy record with read-only access to intermediate state."""
        # Only Curve staking can create tokens with 'y' prefix
        if ticker and len(ticker) > 0 and ticker[0].lower() == "y":
            normalized_ticker = "y" + ticker[1:].upper()
        else:
            normalized_ticker = ticker.upper()
        if normalized_ticker in self._state.deploys:
            return self._state.deploys[normalized_ticker]

        db_deploy_record = self._validator.get_deploy_record(ticker)
        if db_deploy_record is not None:
            self._state.deploys[normalized_ticker] = db_deploy_record
        return db_deploy_record


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
