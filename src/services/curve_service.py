"""
Curve Service for OPI-2 Curve Extension (yWTF Stable with RAY).

Manages Curve program state, rebasing index algorithm, and emission calculations.
"""

from decimal import Decimal
from typing import Tuple, Dict, Optional
import structlog
from sqlalchemy.orm import Session

from src.models.curve import CurveConstitution, CurveUserInfo

logger = structlog.get_logger(__name__)

RAY = Decimal("10") ** 27  # Aave Standard Precision


class CurveService:
    """
    Service for managing Curve program state and calculations with RAY precision.

    IMPORTANT: This service assumes sequential block processing.
    update_index() MUST be called before every operation (stake/claim/transfer).
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def _get_linear_rate(self, max_supply: Decimal, lock_duration: int) -> Decimal:
        if lock_duration == 0:
            return Decimal(0)
        return max_supply / Decimal(lock_duration)

    def get_emission_in_range(self, const: CurveConstitution, from_block: int, to_block: int) -> Decimal:
        """
        Calculate total emission between two blocks.

        Handles transitions between exponential phases correctly.
        """
        if to_block <= from_block:
            return Decimal(0)

        # Program boundaries
        end_block = const.start_block + const.lock_duration
        effective_to = min(to_block, end_block)
        effective_from = max(from_block, const.start_block)

        if effective_from >= effective_to:
            return Decimal(0)

        linear_rate = self._get_linear_rate(Decimal(str(const.max_supply)), const.lock_duration)

        # Linear curve: constant emission
        if const.curve_type == "linear":
            blocks = effective_to - effective_from
            return linear_rate * Decimal(blocks)

        # Exponential curve: 4 phases with different rates
        elif const.curve_type == "exponential":
            total_emission = Decimal(0)
            current_block = effective_from

            # Phase boundaries according to OPI-2 specification (relative to start_block)
            # Phase 1: 0-10% (50% supply)
            # Phase 2: 10-30% (25% supply)
            # Phase 3: 30-60% (12.5% supply)
            # Phase 4: 60-100% (12.5% supply)
            phase1_end = const.start_block + int(const.lock_duration * Decimal("0.1"))
            phase2_end = const.start_block + int(const.lock_duration * Decimal("0.3"))
            phase3_end = const.start_block + int(const.lock_duration * Decimal("0.6"))

            while current_block < effective_to:
                # Determine current phase and calculate emission
                if current_block < phase1_end:
                    phase_end = min(phase1_end, effective_to)
                    blocks = phase_end - current_block
                    total_emission += linear_rate * Decimal("5") * Decimal(blocks)
                elif current_block < phase2_end:
                    phase_end = min(phase2_end, effective_to)
                    blocks = phase_end - current_block
                    total_emission += linear_rate * Decimal("1.25") * Decimal(blocks)
                elif current_block < phase3_end:
                    phase_end = min(phase3_end, effective_to)
                    blocks = phase_end - current_block
                    total_emission += linear_rate * Decimal("0.416666666666666667") * Decimal(blocks)
                else:
                    phase_end = min(effective_to, end_block)
                    blocks = phase_end - current_block
                    total_emission += linear_rate * Decimal("0.3125") * Decimal(blocks)

                current_block = phase_end

            return total_emission
        else:
            logger.error("Unknown curve type", curve_type=const.curve_type, ticker=const.ticker)
            return Decimal(0)

    def update_index(self, ticker: str, current_block: int) -> CurveConstitution:
        """
        Update liquidity index (rebasing accumulator).

        According to OPI-2 specification, rewards are calculated based on
        the state at the end of the previous block (b-1) to prevent flash-stake attacks.
        Therefore, total_staked MUST be retrieved from the database BEFORE any
        modifications from process_stake() in the current block.

        Void Rule: If total_staked == 0, emission is lost (not accumulated).

        Formula: index_increase = growth_value / total_staked_at_block_start
        Where growth_value = emission / rho_g (yWTF units added to pool)

        Args:
            ticker: Reward token ticker
            current_block: Current block height

        Returns:
            Updated CurveConstitution instance
        """
        const = self.db.query(CurveConstitution).filter_by(ticker=ticker).first()
        if not const:
            logger.warning("CurveConstitution not found", ticker=ticker)
            raise ValueError(f"CurveConstitution not found for ticker: {ticker}")

        # Check last_reward_block via a separate query to avoid refreshing the entire object.
        last_reward_block_from_db = self.db.query(CurveConstitution.last_reward_block).filter_by(ticker=ticker).scalar()
        if last_reward_block_from_db is not None and current_block <= last_reward_block_from_db:
            # Already updated for this block, return without modifying const
            return const

        # Get total_staked from DB BEFORE using const object.
        # According to OPI-2 spec, rewards are calculated with S_total(b-1) - the state
        # at the end of the previous block. process_stake() modifies const.total_staked
        # in memory, but we need the value BEFORE those modifications.
        total_staked_at_block_start = self.db.query(CurveConstitution.total_staked).filter_by(ticker=ticker).scalar()

        # Void Rule: If no stakers, emission is lost
        total_staked_decimal = (
            Decimal(str(total_staked_at_block_start)) if total_staked_at_block_start else Decimal("0")
        )
        if total_staked_decimal == 0:
            const.last_reward_block = current_block
            self.db.flush()
            return const

        # Calculate total emission for the period
        emission = self.get_emission_in_range(const, const.last_reward_block, current_block)

        # Calculate rho_g (genesis density ratio)
        if not const.rho_g and not const.max_stake_supply:
            logger.error(
                "rho_g and max_stake_supply are both NULL - cannot calculate growth_value correctly",
                ticker=ticker,
                max_supply=const.max_supply,
            )

            from src.models.deploy import Deploy

            staking_deploy = self.db.query(Deploy).filter_by(ticker=const.staking_ticker).first()
            if staking_deploy:
                const.max_stake_supply = Decimal(str(staking_deploy.max_supply))
                const.rho_g = Decimal(str(const.max_supply)) / Decimal(str(const.max_stake_supply))
                logger.info(
                    "Auto-calculated rho_g from staking_ticker Deploy",
                    ticker=ticker,
                    rho_g=const.rho_g,
                    max_stake_supply=const.max_stake_supply,
                )

        rho_g = (
            Decimal(str(const.rho_g))
            if const.rho_g
            else (
                Decimal(str(const.max_supply)) / Decimal(str(const.max_stake_supply))
                if const.max_stake_supply
                else Decimal("1")
            )
        )

        # Growth value in yWTF units
        growth_value = emission / rho_g if rho_g > 0 else Decimal("0")

        # liquidity_index is in RAY (1e27 = 1.0); index_increase = (growth_value / total_staked) * RAY
        if total_staked_decimal == 0:
            index_increase = Decimal("0")
        else:
            index_increase_nominal = growth_value / total_staked_decimal
            index_increase = index_increase_nominal * RAY

        liquidity_index_decimal = Decimal(str(const.liquidity_index))
        const.liquidity_index = liquidity_index_decimal + index_increase
        const.last_reward_block = current_block

        self.db.flush()
        return const

    def _get_or_create_user(self, user_address: str, ticker: str) -> CurveUserInfo:
        """
        Get or create CurveUserInfo for a user.

        Args:
            user_address: User Bitcoin address
            ticker: Reward token ticker

        Returns:
            CurveUserInfo instance
        """
        user = self.db.query(CurveUserInfo).filter_by(ticker=ticker, user_address=user_address).first()

        if not user:
            user = CurveUserInfo(
                ticker=ticker, user_address=user_address, staked_amount=Decimal("0"), scaled_balance=Decimal("0")
            )
            self.db.add(user)
            self.db.flush()

        return user

    def process_stake(self, user_address: str, ticker: str, amount: Decimal, current_block: int) -> Decimal:
        """
        Process a stake operation (deposit).

        BEFORE processing yToken balances, ensuring the index is calculated with the correct
        total_staked (including all stakes in the current block).

        Args:
            user_address: User Bitcoin address
            ticker: Reward token ticker
            amount: Amount to stake
            current_block: Current block height

        Returns:
            Decimal('0') - No pending rewards in rebasing model
        """
        # Get current constitution (liquidity_index will be updated in flush_balances_from_state)
        const = self.db.query(CurveConstitution).filter_by(ticker=ticker).first()
        if not const:
            logger.warning("CurveConstitution not found", ticker=ticker)
            raise ValueError(f"CurveConstitution not found for ticker: {ticker}")

        user = self._get_or_create_user(user_address, ticker)

        # Refresh to get latest liquidity_index
        self.db.refresh(const)

        # Calculate scaled amount: scaled = (amount * RAY) / liquidity_index
        liquidity_index_decimal = Decimal(str(const.liquidity_index))
        scaled_amount = (amount * RAY) / liquidity_index_decimal

        # Update user state
        user.scaled_balance = Decimal(str(user.scaled_balance)) + scaled_amount
        user.staked_amount = Decimal(str(user.staked_amount)) + amount

        # Update global state
        const.total_scaled_staked = Decimal(str(const.total_scaled_staked)) + scaled_amount
        const.total_staked = Decimal(str(const.total_staked)) + amount

        self.db.flush()
        return Decimal("0")

    def process_claim(
        self, user_address: str, ticker: str, amount_ytoken_burn: Decimal, current_block: int
    ) -> Tuple[Decimal, Decimal]:
        """
        Process a claim operation (withdraw/unstake).

        BEFORE processing yToken balances, ensuring the index is calculated with the correct
        total_staked (including all stakes in the current block).

        Uses Nash correction: principal_out = user.staked_amount * burn_ratio

        Args:
            user_address: User Bitcoin address
            ticker: Reward token ticker
            amount_ytoken_burn: Amount of yToken to burn (nominal)
            current_block: Current block height

        Returns:
            Tuple[principal_out, crv_out]
            - principal_out: Amount of staking token (WTF) to return
            - crv_out: Amount of reward token (CRV) to mint
        """
        # Get current constitution (liquidity_index will be updated in flush_balances_from_state)
        const = self.db.query(CurveConstitution).filter_by(ticker=ticker).first()
        if not const:
            logger.warning("CurveConstitution not found", ticker=ticker)
            raise ValueError(f"CurveConstitution not found for ticker: {ticker}")

        # Refresh to get latest liquidity_index (updated by flush_balances_from_state at block start)
        self.db.refresh(const)

        user = self.db.query(CurveUserInfo).filter_by(ticker=ticker, user_address=user_address).first()

        if not user:
            raise ValueError(f"User {user_address} has no staked balance for ticker {ticker}")

        liquidity_index_decimal = Decimal(str(const.liquidity_index))
        scaled_balance_decimal = Decimal(str(user.scaled_balance))

        # Calculate current real balance
        current_real_balance = (scaled_balance_decimal * liquidity_index_decimal) / RAY

        # Tolerance for rounding errors
        if current_real_balance < amount_ytoken_burn:
            if current_real_balance >= amount_ytoken_burn * Decimal("0.999999"):
                amount_ytoken_burn = current_real_balance
            else:
                raise ValueError(f"Insufficient yToken balance: {current_real_balance} < {amount_ytoken_burn}")

        # Calculate scaled to burn
        scaled_burn = (amount_ytoken_burn * RAY) / liquidity_index_decimal
        if scaled_balance_decimal < scaled_burn:
            if scaled_balance_decimal >= scaled_burn * Decimal("0.999999"):
                scaled_burn = scaled_balance_decimal
            else:
                raise ValueError(f"Insufficient scaled balance: {scaled_balance_decimal} < {scaled_burn}")

        # Calculate burn ratio and principal
        burn_ratio = amount_ytoken_burn / current_real_balance if current_real_balance > 0 else Decimal(0)
        principal_out = Decimal(str(user.staked_amount)) * burn_ratio

        # Yield = difference between nominal burned and principal returned
        yield_ytoken = amount_ytoken_burn - principal_out
        if yield_ytoken < 0:
            yield_ytoken = Decimal("0")

        # Convert yield to CRV via rho_g
        rho_g = (
            Decimal(str(const.rho_g))
            if const.rho_g
            else (
                Decimal(str(const.max_supply)) / Decimal(str(const.max_stake_supply))
                if const.max_stake_supply
                else Decimal("1")
            )
        )
        crv_out = yield_ytoken * rho_g

        # Update user state
        user.scaled_balance = scaled_balance_decimal - scaled_burn
        user.staked_amount = max(Decimal("0"), Decimal(str(user.staked_amount)) - principal_out)

        # Update global state
        const.total_scaled_staked = max(Decimal("0"), Decimal(str(const.total_scaled_staked)) - scaled_burn)
        const.total_staked = max(Decimal("0"), Decimal(str(const.total_staked)) - principal_out)

        self.db.commit()
        return principal_out, crv_out

    def process_transfer(self, from_address: str, to_address: str, ticker: str, amount: Decimal, current_block: int):
        """
        Process transfer of yTokens with proportional principal transfer.

        BEFORE processing yToken balances, ensuring the index is calculated with the correct
        total_staked (including all stakes in the current block).

        This allows the new owner to inherit accumulated rewards
        (conforms to OPI-2 specification).

        Args:
            from_address: Sender Bitcoin address
            to_address: Recipient Bitcoin address
            ticker: Reward token ticker
            amount: Amount of yToken to transfer (nominal)
            current_block: Current block height
        """
        # Get current constitution (liquidity_index will be updated in flush_balances_from_state)
        const = self.db.query(CurveConstitution).filter_by(ticker=ticker).first()
        if not const:
            logger.warning("CurveConstitution not found", ticker=ticker)
            raise ValueError(f"CurveConstitution not found for ticker: {ticker}")

        # Refresh to get latest liquidity_index (updated by flush_balances_from_state at block start)
        self.db.refresh(const)

        # Get sender
        user_from = self._get_or_create_user(from_address, ticker)

        liquidity_index_decimal = Decimal(str(const.liquidity_index))
        scaled_balance_from_decimal = Decimal(str(user_from.scaled_balance))

        # Calculate real balance from scaled balance for validation
        real_balance_from = (scaled_balance_from_decimal * liquidity_index_decimal) / RAY

        if real_balance_from < amount:
            raise ValueError(f"Insufficient yToken balance for transfer: {real_balance_from} < {amount}")

        # Calculate scaled to transfer
        scaled_to_transfer = (amount * RAY) / liquidity_index_decimal
        transfer_ratio = (
            scaled_to_transfer / scaled_balance_from_decimal if scaled_balance_from_decimal > 0 else Decimal(0)
        )

        # Calculate principal to transfer
        principal_transfer = Decimal(str(user_from.staked_amount)) * transfer_ratio

        # Update sender
        user_from.scaled_balance = scaled_balance_from_decimal - scaled_to_transfer
        user_from.staked_amount = max(Decimal("0"), Decimal(str(user_from.staked_amount)) - principal_transfer)

        # Get receiver
        user_to = self._get_or_create_user(to_address, ticker)
        scaled_balance_to_decimal = Decimal(str(user_to.scaled_balance))

        # Update receiver (inherits scaled balance and principal)
        user_to.scaled_balance = scaled_balance_to_decimal + scaled_to_transfer
        user_to.staked_amount = Decimal(str(user_to.staked_amount)) + principal_transfer

        self.db.flush()

    def get_tokens_locked_summary(self, min_amount: Optional[Decimal] = None) -> Dict:
        """
        Get summary of all tokens locked in Curve programs.

        Returns for each reward token (CRV):
        - Total amount locked (with rebasing applied)
        - Staking ticker (e.g., "WTF" for CRV)
        - Number of stakers
        - Liquidity index
        - Percentage of max_supply locked (if available)

        This endpoint uses the current DB values, which may be up to 1 block
        behind (acceptable for display purposes).

        Args:
            min_amount: Optional minimum locked amount filter

        Returns:
            Dict with total_tokens and list of tokens with their locked info
        """
        from src.models.deploy import Deploy
        from sqlalchemy import func

        # Get all CurveConstitution records
        constitutions = self.db.query(CurveConstitution).all()

        result_tokens = []

        for constitution in constitutions:
            # (indexer updates liquidity_index in flush_balances_from_state())
            self.db.refresh(constitution)

            # Calculate real yWTF amount with rebasing
            # Formula: total_scaled_staked × (liquidity_index / RAY)
            total_scaled_staked = Decimal(str(constitution.total_scaled_staked))
            liquidity_index = Decimal(str(constitution.liquidity_index))
            total_ytoken_circulating = (total_scaled_staked * liquidity_index) / RAY

            # Get total WTF staked (collateral/principal)
            total_staked_collateral = Decimal(str(constitution.total_staked))

            # Apply min_amount filter if provided (use yWTF amount for filter)
            if min_amount is not None and total_ytoken_circulating < min_amount:
                continue

            # Count number of stakers
            stakers_count = (
                self.db.query(func.count(CurveUserInfo.id))
                .filter(CurveUserInfo.ticker == constitution.ticker)
                .filter(CurveUserInfo.scaled_balance > 0)
                .scalar()
            ) or 0

            # Get max_supply for percentage calculation
            deploy = self.db.query(Deploy).filter_by(ticker=constitution.ticker).first()
            locked_percentage = None

            if deploy and deploy.max_supply and deploy.max_supply > 0:
                try:
                    max_supply = Decimal(str(deploy.max_supply))
                    if max_supply > 0:
                        # Calculate percentage based on yWTF circulating (with rebasing)
                        percentage = (total_ytoken_circulating / max_supply) * Decimal("100")
                        locked_percentage = str(percentage.quantize(Decimal("0.01")))
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

            result_tokens.append(
                {
                    "reward_ticker": constitution.ticker,
                    "staking_ticker": constitution.staking_ticker,
                    "total_staked_collateral": str(
                        total_staked_collateral.quantize(Decimal("0.00000001"))
                    ),  # Initially staked WTF
                    "total_ytoken_circulating": str(
                        total_ytoken_circulating.quantize(Decimal("0.00000001"))
                    ),  # yWTF actuel avec rebasing
                    "total_scaled_staked": str(total_scaled_staked),
                    "liquidity_index": str(liquidity_index),
                    "stakers_count": stakers_count,
                    "locked_percentage_of_supply": locked_percentage,
                    "curve_type": constitution.curve_type,
                    "lock_duration": constitution.lock_duration,
                }
            )

        # Sort by total_ytoken_circulating descending
        result_tokens.sort(key=lambda x: Decimal(x["total_ytoken_circulating"]), reverse=True)

        return {
            "total_tokens": len(result_tokens),
            "tokens": result_tokens,
        }
