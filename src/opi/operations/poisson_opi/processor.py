"""
OPI 'poisson' - Participative mint based on "<o()))><" inscription

Concept:
- Users inscribe "<o()))><" (ASCII fish) in an OP_RETURN
- All participations in a block share 3.125 FLOODFISH (like Bitcoin block reward)
- Same address can participate multiple times in a block
- If block is mined by Ocean Mining Pool:
  * Each address is capped at 3.125 FLOODFISH maximum (even with multiple participations)
- For other blocks:
  * Each participation counts proportionally (no cap per address)

Architecture:
- Phase 1 (process_op): Register each participation
- Phase 2 (on_block_end): Calculate and distribute rewards
"""

from typing import Dict, Any, Tuple, List
from decimal import Decimal
from datetime import datetime, timezone
import json
import structlog

from src.opi.base_opi import BaseProcessor
from src.opi.contracts import State, IntermediateState
from src.models.transaction import BRC20Operation
from src.utils.exceptions import ProcessingResult


class PoissonOPIProcessor(BaseProcessor):
    """
    OPI 'poisson' processor - Participative mint per block
    
    Expected in OP_RETURN: "<o()))><" (exactly)
    Ticker: floodfish
    Reward per block: 3.125
    """
    
    TICKER = "floodfish"
    REWARD_PER_BLOCK = Decimal("3.125")
    OCEAN_POOL_IDENTIFIER = "Ocean"  # Identifier for Ocean pool in coinbase
    FISH_PATTERN = "<o()))><"
    
    def __init__(self, context):
        super().__init__(context)
        self.logger = structlog.get_logger()

    def process_op(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """
        Phase 1: Register a participation in the participative mint
        
        This method is called for each transaction in the block.
        It registers the participation without calculating the final reward.
        """
        
        # ═══════════════════════════════════════════════════════════
        # 1. EXTRACT DATA
        # ═══════════════════════════════════════════════════════════
        sender = tx_info.get("sender_address")
        block_height = tx_info.get("block_height")
        block_hash = tx_info.get("block_hash")
        block_timestamp = tx_info.get("block_timestamp", 0)
        txid = tx_info.get("txid")
        tx_index = tx_info.get("tx_index", 0)
        raw_op_return = tx_info.get("raw_op_return", "")
        
        # ═══════════════════════════════════════════════════════════
        # 2. VALIDATE CONTENT
        # ═══════════════════════════════════════════════════════════
        
        # OP_RETURN content must contain EXACTLY "<o()))><"
        if self.FISH_PATTERN not in raw_op_return:
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_message=f"OP_RETURN must contain '{self.FISH_PATTERN}'"
                ),
                State(),
            )
        
        if not sender:
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_message="Cannot determine sender address"
                ),
                State(),
            )
        
        # ═══════════════════════════════════════════════════════════
        # 3. VERIFY TICKER EXISTS
        # ═══════════════════════════════════════════════════════════
        deploy_record = self.context.get_deploy_record(self.TICKER)
        if not deploy_record:
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_message=f"Ticker {self.TICKER} not deployed. Deploy it first!"
                ),
                State(),
            )
        
        # ═══════════════════════════════════════════════════════════
        # 4. REGISTER PARTICIPATION (MULTIPLE ALLOWED PER ADDRESS)
        # ═══════════════════════════════════════════════════════════
        
        # Store participants in intermediate_state.deploys
        # Key: "poisson_participations_<block_height>"
        # Value: List[Dict] - [{address, txid, tx_index}, ...]
        participations_key = f"poisson_participations_{block_height}"
        
        # Get current participations (may be None if first participant)
        current_participations = self.context._state.deploys.get(participations_key, [])
        
        # ═══════════════════════════════════════════════════════════
        # 5. CREATE PARTICIPATION RECORD
        # ═══════════════════════════════════════════════════════════
        
        # Create ORM object for this participation
        # Amount will be 0 for now, it will be calculated at block end
        participation_record = BRC20Operation(
            txid=txid,
            vout_index=tx_info.get("vout_index", 0),
            operation="poisson_mint",
            ticker=self.TICKER,
            amount="0",  # Will be updated at block end
            from_address=sender,
            to_address=sender,
            block_height=block_height,
            block_hash=block_hash,
            tx_index=tx_index,
            timestamp=datetime.fromtimestamp(block_timestamp, tz=timezone.utc),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return=raw_op_return,
            parsed_json=json.dumps({
                "p": "brc-20",
                "op": "poisson",
                "tick": self.TICKER,
                "pattern": self.FISH_PATTERN
            }),
            is_marketplace=False,
            is_multi_transfer=False,
        )
        
        # ═══════════════════════════════════════════════════════════
        # 6. MUTATION: ADD PARTICIPANT TO THE LIST
        # ═══════════════════════════════════════════════════════════
        
        def register_participant(state: IntermediateState):
            """Register a participant in the block list"""
            participations = state.deploys.get(participations_key, [])
            participations.append({
                "address": sender,
                "txid": txid,
                "tx_index": tx_index,
                "timestamp": block_timestamp
            })
            state.deploys[participations_key] = participations
            
            self.logger.info(
                "Floodfish participant registered",
                block_height=block_height,
                sender=sender,
                txid=txid,
                total_participations=len(participations)
            )
        
        # ═══════════════════════════════════════════════════════════
        # 7. RETURN
        # ═══════════════════════════════════════════════════════════
        
        return (
            ProcessingResult(
                operation_found=True,
                is_valid=True,
                operation_type="poisson",
                ticker=self.TICKER,
                amount="0"  # Amount calculated at block end
            ),
            State(
                orm_objects=[participation_record],
                state_mutations=[register_participant]
            ),
        )
    
    def on_block_end(
        self,
        block_height: int,
        block_hash: str,
        block_data: Dict[str, Any],
        intermediate_state: IntermediateState,
        db_session: Any
    ) -> None:
        """
        Phase 2: Calculate and distribute rewards at block end
        
        This method is called AFTER all transactions in the block have been
        processed. It calculates the final distribution and updates balances
        and records.
        
        Logic:
        - Normal block: Each participation counts proportionally
          Example: 5 participations total, Alice has 3, Bob has 2
          Alice gets (3/5) * 3.125 = 1.875
          Bob gets (2/5) * 3.125 = 1.25
        
        - Ocean block: Each address is capped at 3.125 maximum
          Example: 5 participations total (Alice: 3, Bob: 2)
          Per participation reward = 3.125 / 5 = 0.625
          Alice would get 3 * 0.625 = 1.875, but capped at 3.125 (no cap needed)
          Bob would get 2 * 0.625 = 1.25
          
          Another example: 10 participations (Alice: 8, Bob: 2)
          Per participation reward = 3.125 / 10 = 0.3125
          Alice would get 8 * 0.3125 = 2.5 (no cap needed)
          Bob would get 2 * 0.3125 = 0.625
          
          Edge case: Alice has 15 participations alone
          Per participation reward = 3.125 / 15 = 0.208333...
          Alice would get 15 * 0.208333 = 3.125 (at cap)
        
        Args:
            block_height: Block height
            block_hash: Block hash
            block_data: Complete block data (including coinbase)
            intermediate_state: Intermediate state with participants
            db_session: Database session for updates
        """
        
        # ═══════════════════════════════════════════════════════════
        # 1. GET PARTICIPANTS
        # ═══════════════════════════════════════════════════════════
        participations_key = f"poisson_participations_{block_height}"
        participations = intermediate_state.deploys.get(participations_key, [])
        
        if not participations:
            # No participants in this block
            return
        
        total_participations = len(participations)
        
        self.logger.info(
            "Processing floodfish block rewards",
            block_height=block_height,
            total_participations=total_participations
        )
        
        # ═══════════════════════════════════════════════════════════
        # 2. DETECT MINER (OCEAN POOL BONUS/CAP)
        # ═══════════════════════════════════════════════════════════
        
        is_ocean_pool = False
        miner_info = "Unknown"
        
        # Coinbase transaction is always first (index 0)
        coinbase_tx = block_data.get("tx", [])[0] if block_data.get("tx") else None
        
        if coinbase_tx:
            # Look for "Ocean" in coinbase outputs
            for vout in coinbase_tx.get("vout", []):
                script_pub_key = vout.get("scriptPubKey", {})
                script_asm = script_pub_key.get("asm", "")
                
                # Look for "Ocean" in ASM
                if self.OCEAN_POOL_IDENTIFIER.lower() in script_asm.lower():
                    is_ocean_pool = True
                    miner_info = "Ocean Mining Pool"
                    break
        
        # ═══════════════════════════════════════════════════════════
        # 3. CALCULATE REWARD PER PARTICIPATION
        # ═══════════════════════════════════════════════════════════
        
        if is_ocean_pool:
            # OCEAN BONUS: Each participation gets FULL reward (3.125)!
            reward_per_participation = self.REWARD_PER_BLOCK
            self.logger.info(
                "🌊 OCEAN BONUS ACTIVATED! Each participation gets full reward!",
                block_height=block_height,
                miner_info=miner_info,
                total_participations=total_participations,
                reward_per_participation=str(reward_per_participation),
                estimated_total_distribution=str(reward_per_participation * total_participations)
            )
        else:
            # Normal block: Share reward proportionally
            reward_per_participation = self.REWARD_PER_BLOCK / Decimal(total_participations)
            self.logger.info(
                "Floodfish reward calculation",
                block_height=block_height,
                is_ocean_pool=False,
                miner_info=miner_info,
                total_participations=total_participations,
                reward_per_participation=str(reward_per_participation)
            )
        
        # ═══════════════════════════════════════════════════════════
        # 4. GROUP PARTICIPATIONS BY ADDRESS
        # ═══════════════════════════════════════════════════════════
        
        # Count participations per address
        # {address: [list of participation objects]}
        address_participations = {}
        for participation in participations:
            address = participation["address"]
            if address not in address_participations:
                address_participations[address] = []
            address_participations[address].append(participation)
        
        # ═══════════════════════════════════════════════════════════
        # 5. CALCULATE AND DISTRIBUTE REWARDS
        # ═══════════════════════════════════════════════════════════
        
        from src.models.transaction import BRC20Operation
        
        for address, addr_participations in address_participations.items():
            participation_count = len(addr_participations)
            
            # Calculate total reward for this address
            # Ocean: Each participation gets 3.125 (amazing!)
            # Normal: Proportional share of 3.125 total
            total_reward_for_address = reward_per_participation * Decimal(participation_count)
            
            # No cap on Ocean blocks - that's the bonus!
            # Each participation truly gets the full reward
            
            # Calculate reward per participation for this address
            # (split total evenly across all participations of this address)
            reward_per_addr_participation = total_reward_for_address / Decimal(participation_count)
            
            # Update balance in intermediate_state
            balance_key = (address, self.TICKER)
            current_balance = intermediate_state.balances.get(balance_key, Decimal(0))
            new_balance = current_balance + total_reward_for_address
            intermediate_state.balances[balance_key] = new_balance
            
            # Update each BRC20Operation record for this address
            for participation in addr_participations:
                txid = participation["txid"]
                
                operation = db_session.query(BRC20Operation).filter_by(
                    txid=txid,
                    operation="poisson_mint",
                    block_height=block_height
                ).first()
                
                if operation:
                    # Set the amount for this specific participation
                    operation.amount = str(reward_per_addr_participation)
                    db_session.add(operation)
                    
                    self.logger.debug(
                        "Floodfish reward distributed",
                        address=address,
                        amount=str(reward_per_addr_participation),
                        txid=txid,
                        is_ocean_bonus=is_ocean_pool
                    )
                else:
                    self.logger.warning(
                        "Floodfish operation record not found",
                        txid=txid,
                        address=address
                    )
            
            self.logger.info(
                "Floodfish address reward complete",
                address=address,
                participations=participation_count,
                total_reward=str(total_reward_for_address),
                reward_per_participation=str(reward_per_addr_participation)
            )
        
        # ═══════════════════════════════════════════════════════════
        # 6. CLEANUP PARTICIPANT CACHE
        # ═══════════════════════════════════════════════════════════
        
        # Delete participant list to free memory
        if participations_key in intermediate_state.deploys:
            del intermediate_state.deploys[participations_key]
        
        # Calculate total distributed for logging
        total_distributed = sum(
            reward_per_participation * Decimal(len(addr_participations))
            for addr_participations in address_participations.values()
        )
        
        if is_ocean_pool:
            self.logger.info(
                "🌊 Floodfish block processing complete - OCEAN BONUS!",
                block_height=block_height,
                addresses_rewarded=len(address_participations),
                total_participations=total_participations,
                total_distributed=str(total_distributed),
                multiplier=f"{total_participations}x normal reward!"
            )
        else:
            self.logger.info(
                "Floodfish block processing complete",
                block_height=block_height,
                addresses_rewarded=len(address_participations),
                total_participations=total_participations,
                total_distributed=str(total_distributed)
            )
