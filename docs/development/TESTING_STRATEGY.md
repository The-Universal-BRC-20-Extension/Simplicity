# 🧪 **Testing Strategy: Real Object Testing Integration**

## **Overview**

This document outlines the comprehensive testing strategy that balances **real object testing** with **controlled test environments** to ensure robust, maintainable tests that catch real regressions.

## **Test Categories**

### **1. Unit Tests (Isolated)**
- **Location**: `tests/unit/test_services_isolated.py`
- **Purpose**: Test individual services in complete isolation
- **Mocking**: Heavy mocking of all dependencies
- **Use Case**: Testing service logic without external dependencies

```bash
# Run unit tests
python scripts/run_tests.py --category unit
```

### **2. Integration Tests (Real Validation)**
- **Location**: `tests/integration/test_real_validation.py`
- **Purpose**: Test real validation logic with minimal mocking
- **Mocking**: Only external dependencies (APIs, network calls)
- **Use Case**: Testing business logic integration

```bash
# Run integration tests
python scripts/run_tests.py --category integration
```

### **3. Real Validation Tests**
- **Location**: Mixed across existing test files
- **Purpose**: Test with real objects where it matters most
- **Mocking**: Minimal mocking, real validation services
- **Use Case**: Catching real regressions in validation logic

```bash
# Run real validation tests
python scripts/run_tests.py --category real-validation
```

### **4. Legacy Validation Tests**
- **Location**: `tests/test_processor.py`
- **Purpose**: Test legacy validation specifically
- **Mocking**: Controlled mocking of legacy service responses
- **Use Case**: Ensuring legacy validation works correctly

```bash
# Run legacy validation tests
python scripts/run_tests.py --category legacy
```

## **Test Fixtures**

### **Real Object Fixtures** (`tests/conftest.py`)

```python
@pytest.fixture
def real_legacy_service():
    """Real LegacyTokenService for integration testing"""
    return LegacyTokenService()

@pytest.fixture
def real_validator(db_session, real_legacy_service, real_supply_service):
    """Real BRC20Validator with real services"""
    return BRC20Validator(db_session, real_legacy_service, real_supply_service)

@pytest.fixture
def real_processor(db_session, mock_bitcoin_rpc, real_validator):
    """Real BRC20Processor with real validator"""
    processor = BRC20Processor(db_session, mock_bitcoin_rpc)
    processor.validator = real_validator
    return processor
```

### **Test Data Generators**

```python
@pytest.fixture
def unique_ticker_generator():
    """Generate unique tickers for testing to avoid conflicts"""
    def generate_ticker(prefix="TEST"):
        timestamp = int(time.time() * 1000)
        random_suffix = random.randint(1000, 9999)
        return f"{prefix}{timestamp}{random_suffix}"
    return generate_ticker
```

## **Testing Principles**

### **✅ Real Object Testing Benefits**

1. **Catches Real Regressions**: Tests fail when actual validation logic changes
2. **Tests Real Integration**: Exercises actual service interactions
3. **Reflects Production Behavior**: Tests mirror production scenarios
4. **Future-Proof**: Tests remain valuable as codebase evolves

### **🔧 Controlled Test Environment**

1. **Unique Test Data**: Uses unique tickers to avoid conflicts
2. **Isolated Database**: Each test gets a clean database state
3. **Mocked External Dependencies**: Only external APIs are mocked
4. **Real Business Logic**: Core validation and processing logic is real

## **Test Implementation Examples**

### **Real Validation Test Example**

```python
def test_deploy_success_real_validation(self, real_processor, db_session, unique_ticker_generator):
    """Test deploy with real validation - should succeed for unique ticker"""
    ticker = unique_ticker_generator("REAL")
    operation = {"op": "deploy", "tick": ticker, "m": "1000000", "l": "1000"}
    
    tx_info = {
        "txid": f"real_test_txid_{ticker}_1234567890123456789012345678901234567890123456789012345678901234",
        "block_height": 800000,
        "vin": [{"address": "test_deployer_address"}],
        "vout": [{"n": 0, "scriptPubKey": {"type": "pubkeyhash", "addresses": ["1TestAddress"]}}],
    }
    
    with patch.object(real_processor, "get_first_input_address", return_value="test_deployer_address"):
        with patch.object(real_processor, "log_operation"):
            result = real_processor.process_deploy(operation, tx_info, "test_hex_data")
            
            assert result.is_valid is True
            # Verify Deploy object was created with real validation
            deploy_calls = [call[0][0] for call in db_session.add.call_args_list]
            deploy_obj = next((obj for obj in deploy_calls if isinstance(obj, Deploy)), None)
            assert deploy_obj is not None
            assert deploy_obj.ticker == ticker
```

### **Legacy Blocked Test Example**

```python
def test_deploy_blocked_by_legacy_real_validation(self, real_processor, db_session):
    """Test deploy blocked by real legacy validation - ORDI exists on legacy"""
    operation = {"op": "deploy", "tick": "ORDI", "m": "21000000", "l": "1000"}
    
    tx_info = {
        "txid": "legacy_blocked_txid_1234567890123456789012345678901234567890123456789012345678901234",
        "block_height": 800000,
        "vin": [{"address": "test_deployer_address"}],
        "vout": [{"n": 0, "scriptPubKey": {"type": "pubkeyhash", "addresses": ["1TestAddress"]}}],
    }
    
    with patch.object(real_processor, "get_first_input_address", return_value="test_deployer_address"):
        with patch.object(real_processor, "log_operation"):
            result = real_processor.process_deploy(operation, tx_info, "test_hex_data")
            
            assert not result.is_valid
            assert "LEGACY_TOKEN_EXISTS" in result.error_code
            # Should NOT add a Deploy object
            deploy_calls = [call[0][0] for call in db_session.add.call_args_list]
            deploy_obj = next((obj for obj in deploy_calls if isinstance(obj, Deploy)), None)
            assert deploy_obj is None
```

## **Running Tests**

### **Quick Commands**

```bash
# Run all tests
python scripts/run_tests.py --category all

# Run only real validation tests
python scripts/run_tests.py --category real-validation

# Run with coverage
python scripts/run_tests.py --category all --coverage

# Run with verbose output
python scripts/run_tests.py --category integration --verbose
```

### **Direct Pytest Commands**

```bash
# Run specific test file
pipenv run pytest tests/integration/test_real_validation.py -v

# Run specific test method
pipenv run pytest tests/test_processor.py::TestBRC20Processor::test_process_deploy_success_real_integration -v

# Run with coverage
pipenv run pytest tests/ --cov=src --cov-report=html
```

## **Test Maintenance**

### **Adding New Tests**

1. **Unit Tests**: Add to `tests/unit/test_services_isolated.py` for isolated service testing
2. **Integration Tests**: Add to `tests/integration/test_real_validation.py` for real validation testing
3. **Real Validation Tests**: Add to existing test files with `_real_integration` suffix
4. **Legacy Tests**: Add to existing test files with legacy-specific naming

### **Test Data Guidelines**

1. **Use Unique Tickers**: Always use `unique_ticker_generator()` for test data
2. **Valid Transaction IDs**: Use 64-character hex strings for txids
3. **Realistic Block Heights**: Use realistic block heights (800000+)
4. **Proper Addresses**: Use valid Bitcoin addresses for testing

### **Mocking Guidelines**

1. **Mock External Dependencies**: Only mock external APIs and network calls
2. **Real Business Logic**: Keep validation and processing logic real
3. **Controlled Responses**: Mock external services with realistic responses
4. **Isolated Tests**: Each test should be independent and isolated

## **Success Metrics**

### **Test Coverage Goals**

- ✅ **100% Business Logic Coverage**: All validation and processing logic tested
- ✅ **Real Integration Coverage**: All service interactions tested with real objects
- ✅ **Legacy Validation Coverage**: All legacy validation scenarios tested
- ✅ **Error Handling Coverage**: All error paths tested with real validation

### **Performance Goals**

- ✅ **Fast Unit Tests**: Unit tests run in < 1 second
- ✅ **Reasonable Integration Tests**: Integration tests run in < 10 seconds
- ✅ **Isolated Tests**: No test interference or shared state
- ✅ **Reliable Tests**: Tests are deterministic and repeatable

## **Troubleshooting**

### **Common Issues**

1. **Test Conflicts**: Use unique tickers and transaction IDs
2. **Database State**: Ensure proper database cleanup between tests
3. **Mocking Issues**: Verify mocks are applied to the correct objects
4. **Legacy API Issues**: Check legacy service configuration and responses

### **Debugging Tips**

1. **Verbose Output**: Use `-v` flag for detailed test output
2. **Single Test**: Run individual tests to isolate issues
3. **Mock Verification**: Check that mocks are called as expected
4. **Database Inspection**: Verify database state after test execution

## **Future Enhancements**

### **Planned Improvements**

1. **Performance Testing**: Add performance benchmarks for real validation
2. **Stress Testing**: Add tests with large datasets and high concurrency
3. **API Testing**: Add comprehensive API endpoint testing
4. **End-to-End Testing**: Add full workflow testing from API to database

### **Continuous Integration**

1. **Automated Testing**: Integrate with CI/CD pipeline
2. **Coverage Reporting**: Automated coverage reports
3. **Test Parallelization**: Run tests in parallel for faster execution
4. **Quality Gates**: Enforce minimum coverage and test quality standards 