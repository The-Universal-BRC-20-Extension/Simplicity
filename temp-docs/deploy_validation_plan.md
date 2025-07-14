# 🟢 **Strategic Plan: Deploy Validation Against Ordinals**

---

## 1. **Overview & Requirements**

### **Problem Statement**
- Need to validate that tokens being deployed in Universal BRC-20 Extension were NOT first deployed on Ordinals
- Example: `OPQT` is valid (deployed on this standard first), but `ORDI` is invalid (already deployed on Ordinals)
- Use OPI-LC endpoint `/v1/brc20/ticker/:tick` to check if token exists on legacy system

### **Key Requirements**
- Add validation during deploy processing
- Store legacy token data in database
- Track both Universal BRC-20 Extension and legacy token supplies
- Calculate remaining supply across both systems

---

## 2. **Database Schema Changes**

### **A. New Table: `legacy_tokens`**
```sql
CREATE TABLE IF NOT EXISTS brc20.legacy_tokens (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(4) UNIQUE NOT NULL,
    max_supply NUMERIC NOT NULL,
    decimals INTEGER NOT NULL DEFAULT 18,
    limit_per_mint NUMERIC,
    deploy_inscription_id VARCHAR(100),
    block_height INTEGER NOT NULL,
    deployer_address VARCHAR(34),
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_verified_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### **B. Enhanced `deploys` Table**
```sql
-- Add new columns to existing deploys table
ALTER TABLE brc20.deploys ADD COLUMN IF NOT EXISTS is_legacy_validated BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE brc20.deploys ADD COLUMN IF NOT EXISTS legacy_validation_result JSONB;
ALTER TABLE brc20.deploys ADD COLUMN IF NOT EXISTS legacy_validation_timestamp TIMESTAMP;
```

### **C. New Table: `token_supply_tracking`**
```sql
CREATE TABLE IF NOT EXISTS brc20.token_supply_tracking (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(4) NOT NULL,
    universal_supply NUMERIC NOT NULL DEFAULT 0,
    legacy_supply NUMERIC NOT NULL DEFAULT 0,
    total_supply NUMERIC NOT NULL DEFAULT 0,
    no_return_amount NUMERIC NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(ticker),
    FOREIGN KEY (ticker) REFERENCES brc20.deployments(ticker)
);
```

---

## 3. **Service Architecture**

### **A. New Service: `LegacyTokenService`**
```python
class LegacyTokenService:
    def __init__(self, opi_lc_url: str = "http://localhost:3004"):
        self.base_url = opi_lc_url
        self.client = httpx.Client(timeout=30.0)
    
    def check_token_exists(self, ticker: str) -> Optional[Dict]:
        """Check if token exists on legacy system via OPI-LC"""
        
    def validate_deploy_against_legacy(self, ticker: str) -> ValidationResult:
        """Validate that token can be deployed (not already on legacy)"""
```

### **B. Enhanced `BRC20Validator`**
```python
class BRC20Validator:
    def __init__(self, db_session: Session, legacy_service: LegacyTokenService):
        self.db = db_session
        self.legacy_service = legacy_service
    
    def validate_deploy(self, operation: Dict[str, Any]) -> ValidationResult:
        """Enhanced deploy validation with legacy check"""
        # 1. Existing validation (ticker not exists, valid amounts)
        # 2. NEW: Legacy validation (not deployed on Ordinals)
        # 3. Store legacy data if validation passes
```

### **C. New Service: `TokenSupplyService`**
```python
class TokenSupplyService:
    def __init__(self, db_session: Session):
        self.db = db_session
    
    def update_supply_tracking(self, ticker: str):
        """Update supply tracking for both Universal and Legacy"""
        
    def get_total_supply_breakdown(self, ticker: str) -> Dict:
        """Get supply breakdown across both systems"""
```

---

## 4. **Implementation Steps**

### **Phase 1: Database Schema Setup**
1. **Create migration files**
   ```bash
   # Create new migration
   alembic revision --autogenerate -m "Add legacy token validation tables"
   ```

2. **Update database schema**
   - Add `legacy_tokens` table
   - Add columns to `deploys` table
   - Add `token_supply_tracking` table
   - Create indexes for performance

### **Phase 2: Core Services Implementation**
1. **Implement `LegacyTokenService`**
   ```python
   # src/services/legacy_token_service.py
   class LegacyTokenService:
       def check_token_exists(self, ticker: str) -> Optional[Dict]:
           """Query OPI-LC endpoint /v1/brc20/ticker/{ticker}"""
           
       def validate_deploy_against_legacy(self, ticker: str) -> ValidationResult:
           """Main validation logic"""
   ```

2. **Enhance `BRC20Validator`**
   ```python
   # src/services/validator.py
   def validate_deploy(self, operation: Dict[str, Any]) -> ValidationResult:
       # Existing validation
       existing_validation = self._validate_existing_deploy_rules(operation)
       if not existing_validation.is_valid:
           return existing_validation
       
       # NEW: Legacy validation
       legacy_validation = self.legacy_service.validate_deploy_against_legacy(
           operation.get("tick")
       )
       if not legacy_validation.is_valid:
           return legacy_validation
       
       return ValidationResult(True)
   ```

3. **Implement `TokenSupplyService`**
   ```python
   # src/services/token_supply_service.py
   class TokenSupplyService:
       def update_supply_tracking(self, ticker: str):
           """Calculate and update supply across both systems"""
           
       def get_total_supply_breakdown(self, ticker: str) -> Dict:
           """Get comprehensive supply information"""
   ```

### **Phase 3: Integration Points**
1. **Update `BRC20Processor.process_deploy()`**
   ```python
   def process_deploy(self, operation: dict, tx_info: dict, hex_data: str) -> ValidationResult:
       # Existing validation
       validation_result = self.validator.validate_complete_operation(...)
       
       if validation_result.is_valid:
           # Store legacy token data if validation passed
           self._store_legacy_token_data(operation.get("tick"))
           
           # Create deploy record
           deploy = Deploy(...)
           self.db.add(deploy)
           
           # Update supply tracking
           self.supply_service.update_supply_tracking(operation.get("tick"))
   ```

2. **Update `OPIProcessor` for no_return operations**
   ```python
   # When processing no_return operations, update supply tracking
   def process_operation(self, operation: dict, tx: dict, db_session: Session):
       # Existing no_return processing
       # ...
       
       # Update supply tracking to reflect no_return amount
       self.supply_service.update_supply_tracking(ticker)
   ```

### **Phase 4: API Enhancements**
1. **Enhanced ticker info endpoint**
   ```python
   # src/api/routers/brc20.py
   @router.get("/brc20/{ticker}/info", response_model=Brc20InfoItem)
   async def get_ticker_info(ticker: str):
       # Include legacy validation status and supply breakdown
       result = calc_service.get_ticker_stats_with_legacy_info(ticker)
   ```

2. **New endpoint for supply breakdown**
   ```python
   @router.get("/brc20/{ticker}/supply-breakdown")
   async def get_supply_breakdown(ticker: str):
       """Get detailed supply breakdown across Universal and Legacy systems"""
   ```

---

## 5. **Validation Logic Flow**

### **A. Deploy Validation Process**
```
1. Parse deploy operation
2. Validate existing rules (ticker format, amounts, etc.)
3. Check if ticker already exists in Universal system
4. NEW: Query OPI-LC endpoint /v1/brc20/ticker/{ticker}
5. If token exists on legacy:
   - Return validation error
   - Log detailed error information
6. If token doesn't exist on legacy:
   - Store legacy validation result
   - Proceed with deploy
   - Initialize supply tracking
```

### **B. OPI-LC Integration**
```python
def check_token_exists(self, ticker: str) -> Optional[Dict]:
    """Query OPI-LC for token existence"""
    try:
        response = self.client.get(f"/v1/brc20/ticker/{ticker}")
        response.raise_for_status()
        data = response.json()
        
        if data.get("error") or not data.get("result"):
            return None  # Token doesn't exist on legacy
            
        return data["result"]  # Token exists, return details
        
    except httpx.RequestError as e:
        logger.error("OPI-LC request failed", ticker=ticker, error=str(e))
        return None
    except Exception as e:
        logger.error("Failed to process OPI-LC response", ticker=ticker, error=str(e))
        return None
```

---

## 6. **Data Storage Strategy**

### **A. Legacy Token Data**
```python
# Store in legacy_tokens table
legacy_token = LegacyToken(
    ticker=ticker.upper(),
    max_supply=legacy_data.get("max_supply"),
    decimals=legacy_data.get("decimals", 18),
    limit_per_mint=legacy_data.get("limit_per_mint"),
    deploy_inscription_id=legacy_data.get("deploy_inscription_id"),
    block_height=legacy_data.get("block_height"),
    deployer_address=legacy_data.get("deployer_address"),
    is_active=True,
    last_verified_at=datetime.utcnow()
)
```

### **B. Deploy Validation Results**
```python
# Store in deploys table
deploy = Deploy(
    ticker=operation["tick"],
    max_supply=operation["m"],
    limit_per_op=operation.get("l"),
    deploy_txid=tx_info["txid"],
    deploy_height=tx_info.get("block_height", 0),
    deploy_timestamp=deploy_timestamp,
    deployer_address=deployer_address,
    is_legacy_validated=True,
    legacy_validation_result={
        "validated_at": datetime.utcnow().isoformat(),
        "legacy_exists": False,
        "validation_source": "OPI-LC"
    },
    legacy_validation_timestamp=datetime.utcnow()
)
```

### **C. Supply Tracking**
```python
# Store in token_supply_tracking table
supply_tracking = TokenSupplyTracking(
    ticker=ticker.upper(),
    universal_supply=universal_minted_amount,
    legacy_supply=legacy_minted_amount,
    total_supply=universal_minted_amount + legacy_minted_amount,
    no_return_amount=no_return_amount,
    last_updated_at=datetime.utcnow()
)
```

---

## 7. **Error Handling & Edge Cases**

### **A. OPI-LC Service Unavailable**
```python
def validate_deploy_against_legacy(self, ticker: str) -> ValidationResult:
    try:
        legacy_data = self.check_token_exists(ticker)
        
        if legacy_data:
            return ValidationResult(
                False,
                "LEGACY_TOKEN_EXISTS",
                f"Token '{ticker}' already deployed on Ordinals"
            )
        
        return ValidationResult(True)
        
    except Exception as e:
        # If OPI-LC is unavailable, log warning but allow deploy
        logger.warning(
            "OPI-LC unavailable, allowing deploy without legacy validation",
            ticker=ticker,
            error=str(e)
        )
        return ValidationResult(True)  # Allow deploy with warning
```

### **B. Network Timeouts**
```python
# Configure appropriate timeouts
self.client = httpx.Client(
    base_url=self.base_url,
    timeout=httpx.Timeout(30.0, connect=10.0)
)
```

### **C. Invalid Response Handling**
```python
def check_token_exists(self, ticker: str) -> Optional[Dict]:
    try:
        response = self.client.get(f"/v1/brc20/ticker/{ticker}")
        
        # Handle various response scenarios
        if response.status_code == 404:
            return None  # Token doesn't exist
            
        if response.status_code != 200:
            logger.error("OPI-LC returned non-200 status", 
                        ticker=ticker, status=response.status_code)
            return None
            
        data = response.json()
        if not data.get("result"):
            return None  # No valid result
            
        return data["result"]
        
    except Exception as e:
        logger.error("OPI-LC query failed", ticker=ticker, error=str(e))
        return None
```

---

## 8. **Testing Strategy**

### **A. Unit Tests**
```python
# tests/test_legacy_token_service.py
class TestLegacyTokenService:
    def test_check_token_exists_success(self):
        """Test successful token existence check"""
        
    def test_check_token_exists_not_found(self):
        """Test when token doesn't exist on legacy"""
        
    def test_check_token_exists_service_unavailable(self):
        """Test handling when OPI-LC is down"""
```

### **B. Integration Tests**
```python
# tests/test_deploy_validation_integration.py
class TestDeployValidationIntegration:
    def test_valid_deploy_not_on_legacy(self):
        """Test deploy of token not on legacy system"""
        
    def test_invalid_deploy_on_legacy(self):
        """Test deploy rejection for token on legacy system"""
        
    def test_supply_tracking_integration(self):
        """Test supply tracking across both systems"""
```

### **C. API Tests**
```python
# tests/test_api_legacy_validation.py
class TestAPILegacyValidation:
    def test_ticker_info_with_legacy_data(self):
        """Test ticker info includes legacy validation status"""
        
    def test_supply_breakdown_endpoint(self):
        """Test supply breakdown endpoint"""
```

---

## 9. **Configuration Updates**

### **A. Settings Enhancement**
```python
# src/config.py
class Settings(BaseSettings):
    # Existing settings...
    
    # Legacy validation settings
    OPI_LC_URL: str = "http://localhost:3004"
    LEGACY_VALIDATION_ENABLED: bool = True
    LEGACY_VALIDATION_TIMEOUT: int = 30
    LEGACY_VALIDATION_MAX_RETRIES: int = 3
    
    # Supply tracking settings
    SUPPLY_TRACKING_ENABLED: bool = True
    SUPPLY_UPDATE_INTERVAL: int = 300  # 5 minutes
```

### **B. Environment Variables**
```bash
# .env
OPI_LC_URL=http://localhost:3004
LEGACY_VALIDATION_ENABLED=true
LEGACY_VALIDATION_TIMEOUT=30
SUPPLY_TRACKING_ENABLED=true
```

---

## 10. **Monitoring & Logging**

### **A. Metrics**
```python
# Track validation metrics
LEGACY_VALIDATION_REQUESTS = Counter(
    "legacy_validation_requests_total",
    "Total legacy validation requests",
    ["ticker", "result"]
)

LEGACY_VALIDATION_DURATION = Histogram(
    "legacy_validation_duration_seconds",
    "Legacy validation request duration",
    ["ticker"]
)
```

### **B. Logging**
```python
logger.info(
    "Legacy validation completed",
    ticker=ticker,
    exists_on_legacy=bool(legacy_data),
    validation_duration=duration,
    opi_lc_response=legacy_data
)
```

---

## 11. **Migration Plan**

### **Phase 1: Schema Migration**
1. Create and run Alembic migration
2. Add new tables and columns
3. Create indexes for performance

### **Phase 2: Service Implementation**
1. Implement `LegacyTokenService`
2. Enhance `BRC20Validator`
3. Implement `TokenSupplyService`

### **Phase 3: Integration**
1. Update `BRC20Processor`
2. Update `OPIProcessor`
3. Add API endpoints

### **Phase 4: Testing & Validation**
1. Run comprehensive test suite
2. Validate with real OPI-LC data
3. Performance testing

### **Phase 5: Deployment**
1. Deploy to staging environment
2. Monitor validation metrics
3. Gradual rollout to production

---

## 12. **Success Criteria**

- ✅ All deploy operations validate against legacy system
- ✅ Legacy token data properly stored and tracked
- ✅ Supply calculations accurate across both systems
- ✅ API endpoints provide comprehensive token information
- ✅ Error handling robust for network issues
- ✅ Performance impact minimal (< 100ms per validation)
- ✅ 100% test coverage for new functionality
- ✅ Monitoring and alerting in place

---

## 13. **Risk Mitigation**

### **A. Performance Risks**
- Implement caching for legacy validation results
- Use connection pooling for OPI-LC requests
- Add circuit breaker pattern for service failures

### **B. Data Consistency Risks**
- Implement retry logic for failed validations
- Add data integrity checks
- Regular reconciliation jobs

### **C. Service Availability Risks**
- Graceful degradation when OPI-LC unavailable
- Fallback validation strategies
- Health checks and monitoring

---

## 14. **Future Enhancements**

### **A. Advanced Features**
- Real-time supply synchronization
- Cross-system transfer tracking
- Advanced analytics and reporting

### **B. Performance Optimizations**
- Background validation jobs
- Caching strategies
- Batch processing capabilities

### **C. Monitoring Enhancements**
- Real-time dashboards
- Alert systems
- Performance analytics

---

This plan provides a comprehensive approach to implementing legacy validation for deploy operations while maintaining system reliability and performance. 

---

# Critical DB/SQL Error Remediation Plan for Universal BRC-20 Logging

## 1. Root Causes Identified

- **A. SUM Type Error:**
  - PostgreSQL error: `function sum(character varying) does not exist`.
  - Cause: `balances.balance` is stored as a string (character varying), but `SUM()` expects a numeric type.
  - Impact: Universal supply calculations and logging fail for tokens like OPQT.

- **B. Transaction Aborted (InFailedSqlTransaction):**
  - Cause: The above SQL error aborts the transaction, so all subsequent queries fail until the transaction is reset.

- **C. SQLAlchemy .astext Attribute Error:**
  - Error: `Neither 'BinaryExpression' object nor 'Comparator' object has an attribute 'astext'`.
  - Cause: Use of `.astext` on SQLAlchemy expressions is not supported in recent SQLAlchemy versions.
  - Impact: Fails to calculate no_return amount and other string conversions in queries.

---

## 2. What Needs to Be Updated (Precise Codebase Locations)

### **A. `src/services/token_supply_service.py`**
- **_calculate_universal_supply:**
  - Change: `func.sum(Balance.balance)` → `func.sum(cast(Balance.balance, Numeric))`
  - Import `cast, Numeric` from SQLAlchemy.
- **_calculate_no_return_amount:**
  - Change: `OPIOperation.operation_data['amount'].astext.cast(func.Numeric)` → `cast(OPIOperation.operation_data['amount'], Numeric)`
  - Change: `OPIOperation.operation_data['ticker'].astext == ticker` → `cast(OPIOperation.operation_data['ticker'], String) == ticker`
  - Import `cast, Numeric, String` from SQLAlchemy.
- **update_supply_tracking (exception handling):**
  - After catching an exception, add `self.db.rollback()` to ensure the session is reset.

### **B. Other Files**
- **`src/services/validator.py` and `src/services/calculation_service.py`:**
  - Already use `.cast(Numeric)` or `.cast(BigInteger)`—no change needed.

---

## 3. Planned Changes (Step-by-Step)

1. **Update SUM Queries:**
   - Refactor all affected queries in `token_supply_service.py` to use explicit numeric casting.
2. **Remove/Replace `.astext` Usage:**
   - Refactor all `.astext` usage to use `.cast(String)` or `.cast(Numeric)` as appropriate.
3. **Add Transaction Rollback:**
   - Ensure all exception handlers in supply tracking roll back the session.
4. **Review and Confirm Other Files:**
   - Confirm that `validator.py` and `calculation_service.py` use correct casting (already done).

---

## 4. Required & Recommended Tests (Industrial-Grade Quality)

### **A. Unit Tests**
- Test `_calculate_universal_supply` with balances as strings and numerics, including edge cases (empty, zero, large values).
- Test `_calculate_no_return_amount` with valid/invalid JSON fields, missing/extra data, and type errors.
- Test that exceptions in `update_supply_tracking` properly roll back the session and do not leave the DB in a failed state.

### **B. Integration Tests**
- End-to-end test for Universal BRC-20 deploy (e.g., OPQT) that:
  - Mints, transfers, and logs supply correctly
  - Handles legacy and universal supply calculations
  - Verifies no_return amount is correct
- Test that a failed supply calculation does not block subsequent DB operations.

### **C. Real-World Scenario Tests**
- Deploy a token with balances as strings (simulate real data)
- Simulate a failed supply calculation and ensure the system recovers and logs the error
- Confirm that all API endpoints relying on supply/balance work as expected

### **D. Regression Tests**
- Add regression tests for the specific errors encountered (SUM type error, .astext error, transaction abort)
- Ensure that future changes to models or DB types are caught by these tests

---

## 5. Summary Table of Changes

| File                                 | Method/Line                        | Change Needed                |
|---------------------------------------|------------------------------------|------------------------------|
| token_supply_service.py               | _calculate_universal_supply        | SUM with cast to Numeric     |
| token_supply_service.py               | _calculate_no_return_amount        | Remove .astext, use cast     |
| token_supply_service.py               | update_supply_tracking (catch)     | Add session rollback         |
| validator.py, calculation_service.py  | (various)                          | Already correct              |

---

## 6. Next Steps

- Await approval of this plan.
- Once approved, proceed to implement the above changes, one step at a time, with clear commit messages and test verification after each step.
- Ensure all new and existing tests pass before merging. 