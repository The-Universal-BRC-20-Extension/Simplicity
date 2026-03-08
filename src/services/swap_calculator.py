from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class SwapCalculationResult:
    """Result of a swap calculation using AMM constant product formula"""

    final_amount_in: Decimal
    amount_to_user: Decimal
    amount_out_before_fees: Decimal
    slippage: Decimal
    expected_rate: Decimal
    actual_rate: Decimal
    reserve_in_before: Decimal
    reserve_out_before: Decimal
    reserve_in_after: Decimal
    reserve_out_after: Decimal
    k_constant: Decimal
    is_partial_fill: bool = False
    protocol_fee: Decimal = Decimal("0")


class SwapCalculator:
    """
    AMM Constant Product Calculator for swap operations.

    Formula: k = x * y (where k is constant)

    For swapping Δx tokens:
    - New reserve_in = reserve_in + Δx
    - New reserve_out = k / new_reserve_in
    - Amount out = reserve_out - new_reserve_out

    Architecture: Simple 3-step pipeline
    1. Calculate full execution
    2. Validate slippage against user tolerance
    3. If slippage too high, calculate exact partial fill
    """

    # Protocol fee rate (0.3%)
    PROTOCOL_FEE_RATE = Decimal("0.003")

    @staticmethod
    def _calculate_execution(
        reserve_in: Decimal,
        reserve_out: Decimal,
        amount_in: Decimal,
    ) -> Tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        """
        Pure function that calculates a swap execution without validation.

        This function isolates the core AMM calculation logic. It is stateless,
        deterministic, and easily testable.

        Args:
            reserve_in: Reserve of input token before swap
            reserve_out: Reserve of output token before swap
            amount_in: Amount of input token to swap

        Returns:
            Tuple of:
            - amount_to_user: Amount received by user (after protocol fees)
            - protocol_fee: Protocol fee collected (0.3% of output)
            - slippage_percent: Slippage percentage (0-100)
            - actual_rate: Actual execution rate (amount_out / amount_in)
            - reserve_in_after: Reserve in after swap
            - reserve_out_after: Reserve out after swap
            - amount_out_before_fees: Amount out before fees (for executor credit)

        Raises:
            ValueError: If reserves or amount_in are invalid
        """
        # Validate inputs
        if reserve_in <= 0 or reserve_out <= 0 or amount_in <= 0:
            raise ValueError("Reserves and input amount must be positive")

        # Calculate k constant (constant product)
        k_constant = reserve_in * reserve_out

        # Calculate new reserves after swap
        new_reserve_in = reserve_in + amount_in
        new_reserve_out = k_constant / new_reserve_in

        # Calculate amount out (before fees)
        amount_out_before_fees = reserve_out - new_reserve_out

        # Apply protocol fee (0.3% of output)
        protocol_fee = amount_out_before_fees * SwapCalculator.PROTOCOL_FEE_RATE
        amount_to_user = amount_out_before_fees - protocol_fee

        # Validate output is positive
        if amount_to_user <= 0:
            # Return zero amounts with maximum slippage to indicate failure
            expected_rate = reserve_out / reserve_in if reserve_in > 0 else Decimal(0)
            return (
                Decimal(0),
                Decimal(0),
                Decimal(100),  # Maximum slippage indicates failure
                Decimal(0),
                reserve_in,
                reserve_out,
                Decimal(0),  # amount_out_before_fees = 0
            )

        # Calculate rates and slippage
        expected_rate = reserve_out / reserve_in if reserve_in > 0 else Decimal(0)
        # Slippage measures price impact from AMM, not protocol fees
        actual_rate_before_fees = amount_out_before_fees / amount_in if amount_in > 0 else Decimal(0)
        actual_rate = amount_to_user / amount_in if amount_in > 0 else Decimal(0)

        # Calculate slippage percentage (using rate BEFORE fees)
        # Slippage = |(expected_rate - actual_rate_before_fees) / expected_rate| * 100
        if expected_rate > 0:
            slippage_percent = abs((expected_rate - actual_rate_before_fees) / expected_rate) * Decimal(100)
        else:
            slippage_percent = Decimal(0)

        # Calculate final reserves
        # Note: Reserves reflect the AMM state after swap
        # Fees are collected separately and don't affect the AMM constant product
        final_reserve_in = new_reserve_in
        final_reserve_out = new_reserve_out

        return (
            amount_to_user,
            protocol_fee,
            slippage_percent,
            actual_rate,
            final_reserve_in,
            final_reserve_out,
            amount_out_before_fees,
        )

    @staticmethod
    def calculate_swap_with_slippage_from_reserves(
        reserve_a: Decimal,
        reserve_b: Decimal,
        token_in_ticker: str,
        token_a_ticker: str,
        requested_amount_in: Decimal,
        max_slippage_str: str,
    ) -> SwapCalculationResult:
        """
        Calculate swap output using AMM constant product formula.

        Architecture: Simple 3-step pipeline
        1. Calculate full execution
        2. Validate slippage against user tolerance
        3. If slippage too high, calculate exact partial fill

        Args:
            reserve_a: Reserve of token A in the pool
            reserve_b: Reserve of token B in the pool
            token_in_ticker: Ticker of the token being swapped in
            token_a_ticker: Ticker of token A (determines which reserve is which)
            requested_amount_in: Amount of token_in to swap
            max_slippage_str: Maximum acceptable slippage as string (0-100)

        Returns:
            SwapCalculationResult with all calculation details

        Raises:
            ValueError: If reserves are invalid or calculation fails
        """
        # Determine which reserve is input and which is output
        if token_in_ticker.upper() == token_a_ticker.upper():
            reserve_in = reserve_a
            reserve_out = reserve_b
        else:
            reserve_in = reserve_b
            reserve_out = reserve_a

        # Validate reserves
        if reserve_in <= 0 or reserve_out <= 0:
            raise ValueError("Reserves must be positive")

        if requested_amount_in <= 0:
            raise ValueError("Requested amount must be positive")

        # Calculate k constant
        k_constant = reserve_in * reserve_out

        # Calculate expected rate (spot price before swap)
        expected_rate = reserve_out / reserve_in if reserve_in > 0 else Decimal(0)

        # Convert max_slippage to decimal
        max_slippage_percent = Decimal(str(max_slippage_str))
        if max_slippage_percent < 0 or max_slippage_percent > 100:
            raise ValueError("Slippage tolerance must be between 0 and 100")

        max_slippage_factor = max_slippage_percent / Decimal(100)

        # Step 1: Total execution
        # Calculate what would happen if the full order was executed
        (
            full_amount_to_user,
            full_protocol_fee,
            full_slippage_percent,
            full_actual_rate,
            full_reserve_in_after,
            full_reserve_out_after,
            full_amount_out_before_fees,
        ) = SwapCalculator._calculate_execution(
            reserve_in=reserve_in,
            reserve_out=reserve_out,
            amount_in=requested_amount_in,
        )

        # Validate full execution succeeded
        if full_amount_to_user <= 0:
            raise ValueError("Swap would result in zero or negative output")

        # Step 2: Slippage validation
        # Check if slippage is acceptable
        if full_slippage_percent <= max_slippage_percent:
            # Slippage is acceptable, execute full order
            return SwapCalculationResult(
                final_amount_in=requested_amount_in,
                amount_to_user=full_amount_to_user,
                amount_out_before_fees=full_amount_out_before_fees,
                slippage=full_slippage_percent,
                expected_rate=expected_rate,
                actual_rate=full_actual_rate,
                reserve_in_before=reserve_in,
                reserve_out_before=reserve_out,
                reserve_in_after=full_reserve_in_after,
                reserve_out_after=full_reserve_out_after,
                k_constant=k_constant,
                is_partial_fill=False,
                protocol_fee=full_protocol_fee,
            )

        # Step 3: Partial fill
        # Slippage exceeds tolerance, calculate exact partial fill amount
        try:
            # Formula: partial_amount_in = sqrt((reserve_in^2) * s_factor) - reserve_in
            # where s_factor = 1 / (1 - max_slippage_factor)
            s_factor = Decimal("1") / (Decimal("1") - max_slippage_factor)

            if s_factor <= 0:
                raise ValueError("Invalid slippage factor: slippage tolerance must be less than 100%")

            term_under_sqrt = (reserve_in**2) * s_factor
            partial_amount_in = (term_under_sqrt ** Decimal("0.5")) - reserve_in

            # Ensure partial_amount_in is positive and doesn't exceed requested amount
            partial_amount_in = max(Decimal("0"), min(requested_amount_in, partial_amount_in))

            if partial_amount_in <= 0:
                raise ValueError("Cannot perform partial fill: calculated amount is zero or negative")

        except (ValueError, ArithmeticError) as e:
            # If analytical formula fails, raise clear error
            raise ValueError(f"Cannot calculate partial fill for slippage tolerance {max_slippage_percent}%: {str(e)}")

        # Recalculate execution with partial amount
        (
            partial_amount_to_user,
            partial_protocol_fee,
            partial_slippage_percent,
            partial_actual_rate,
            partial_reserve_in_after,
            partial_reserve_out_after,
            partial_amount_out_before_fees,
        ) = SwapCalculator._calculate_execution(
            reserve_in=reserve_in,
            reserve_out=reserve_out,
            amount_in=partial_amount_in,
        )

        # Validate partial execution succeeded
        if partial_amount_to_user <= 0:
            raise ValueError("Partial fill calculation resulted in zero or negative output")

        # Return partial fill result
        return SwapCalculationResult(
            final_amount_in=partial_amount_in,
            amount_to_user=partial_amount_to_user,
            amount_out_before_fees=partial_amount_out_before_fees,
            slippage=partial_slippage_percent,
            expected_rate=expected_rate,
            actual_rate=partial_actual_rate,
            reserve_in_before=reserve_in,
            reserve_out_before=reserve_out,
            reserve_in_after=partial_reserve_in_after,
            reserve_out_after=partial_reserve_out_after,
            k_constant=k_constant,
            is_partial_fill=True,
            protocol_fee=partial_protocol_fee,
        )

    @staticmethod
    def calculate_simple_amm_output(
        reserve_in: Decimal,
        reserve_out: Decimal,
        amount_in: Decimal,
    ) -> Decimal:
        """
        Simple AMM calculation without slippage validation.
        Used for internal calculations.

        Formula: amount_out = reserve_out - (k / (reserve_in + amount_in))
        where k = reserve_in * reserve_out
        """
        if reserve_in <= 0 or reserve_out <= 0 or amount_in <= 0:
            return Decimal(0)

        k = reserve_in * reserve_out
        new_reserve_in = reserve_in + amount_in
        new_reserve_out = k / new_reserve_in
        amount_out = reserve_out - new_reserve_out

        # Apply protocol fee
        protocol_fee = amount_out * SwapCalculator.PROTOCOL_FEE_RATE
        return amount_out - protocol_fee
