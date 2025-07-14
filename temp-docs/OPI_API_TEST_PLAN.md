# 🟢 **Strategic Plan: Passing All OPI API Test Suites**

---

## 1. **General Principles**

- **Use the real SQLite test DB** (as set up in `conftest.py`) for all API/integration tests.
- **Never use mocks for the DB** in API tests; only use them in pure unit tests.
- **Populate the DB with exactly the right data for each test** (no more, no less).
- **Always use valid, schema-compliant data** (e.g., `txid` must be exactly 64 chars).
- **Clean up after each test** (handled by the `db_session` fixture).
- **Test both happy paths and error/edge cases**.

---

## 2. **DB Item Requirements**

### **A. OPIConfiguration**

- **Required fields:**
  - `opi_id`: string, 1-50 chars, unique, e.g. `"OPI-000"`
  - `is_enabled`: bool, e.g. `True`
  - `version`: string, 1-20 chars, e.g. `"1.0"`
  - `description`: string, e.g. `"No Return Operations"`
  - `configuration`: dict/JSON, e.g. `{"enabled": True}`
  - `created_at`, `updated_at`: auto (let SQLAlchemy handle)

### **B. OPIOperation**

- **Required fields:**
  - `opi_id`: string, must match an existing OPIConfiguration
  - `txid`: string, **exactly 64 chars** (e.g. `"a"*64` or `f"{i:064d}"`)
  - `block_height`: int, >= 0 (e.g. `905040`)
  - `vout_index`: int, >= 0 (e.g. `0`)
  - `operation_type`: string, <= 50 chars (e.g. `"no_return"`)
  - `operation_data`: dict/JSON, must include at least:
    - `"legacy_txid"`: string
    - `"legacy_inscription_id"`: string
    - `"ticker"`: string
    - `"amount"`: string
    - `"sender_address"`: string
  - `created_at`, `updated_at`: auto

---

## 3. **Test Data Patterns**

- **For each test, create only the data needed for that test.**
- **For error/404/400 tests, do NOT create the corresponding DB item.**
- **For pagination, create enough items to test skip/limit logic.**
- **For "not found" or "invalid" cases, use txids or opi_ids that are not present in the DB.**

---

## 4. **Test Implementation Steps**

### **A. Setup**

- Use the `client` and `db_session` fixtures in every test.
- For each test, add the required `OPIConfiguration` and/or `OPIOperation` objects to `db_session` and commit.

### **B. Test Patterns**

#### **1. List OPIs**
- Add at least one `OPIConfiguration`.
- GET `/v1/indexer/brc20/opi` → expect 200, list contains your opi_id.

#### **2. Get OPI Details**
- Add `OPIConfiguration` and N `OPIOperation` with matching `opi_id`.
- GET `/v1/indexer/brc20/opi/{opi_id}` → expect 200, correct opi_id, correct count.

#### **3. Get OPI Details Not Found**
- Do NOT add the `OPIConfiguration`.
- GET `/v1/indexer/brc20/opi/NONEXISTENT` → expect 404.

#### **4. List No Return Transactions**
- Add N `OPIOperation` with `opi_id="OPI-000"`, `operation_type="no_return"`.
- GET `/v1/indexer/brc20/opi/no_return/transactions` → expect 200, correct count.

#### **5. Pagination**
- Add >20 `OPIOperation` as above.
- GET `/v1/indexer/brc20/opi/no_return/transactions?skip=10&limit=10` → expect 10 results, skip/limit correct.

#### **6. Get No Return Transfer Data**
- Add one `OPIOperation` with known `txid`.
- GET `/v1/indexer/brc20/opi/no_return/transfers/{txid}` → expect 200, correct data.

#### **7. Get No Return Transfer Data Not Found**
- Do NOT add the `OPIOperation` for the tested `txid`.
- GET `/v1/indexer/brc20/opi/no_return/transfers/{missing_txid}` → expect 404.

#### **8. Get No Return Transfer Data Invalid TXID**
- Use a txid with wrong length or format.
- GET `/v1/indexer/brc20/opi/no_return/transfers/invalid` → expect 400.

#### **9. Security/Validation**
- Try SQLi or invalid input in opi_id/txid.
- Ensure no sensitive info is leaked in error messages.

---

## 5. **Common Pitfalls to Avoid**

- **txid must be exactly 64 chars**: Use `"a"*64` or `f"{i:064d}"`.
- **block_height must be >= 0**.
- **Do not reuse the same txid for multiple operations**.
- **Always commit after adding to db_session**.
- **Do not use mocks for DB in API tests**.

---

## 6. **Test Suite Execution**

- Run: `pipenv run python -m pytest tests/test_opi_api.py -v`
- If any test fails:
  - Check the DB data for that test.
  - Check for schema validation errors (e.g., txid length).
  - Check for missing required fields.

---

## 7. **Example: Minimal Passing Test**

```python
def test_list_no_return_transactions_with_data(client, db_session):
    op = OPIOperation(
        opi_id="OPI-000",
        txid="a"*64,
        block_height=905040,
        vout_index=0,
        operation_type="no_return",
        operation_data={
            "legacy_txid": "legacy_txid",
            "legacy_inscription_id": "legacy_txid:i0",
            "ticker": "TEST",
            "amount": "100",
            "sender_address": "1TestAddress1234567890abcdef1234567890abcdef",
        }
    )
    db_session.add(op)
    db_session.commit()
    response = client.get("/v1/indexer/brc20/opi/no_return/transactions")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["transactions"][0]["txid"] == "a"*64
```

---

## 8. **Final Checklist**

- [ ] All `txid` are 64 chars
- [ ] All required fields are present
- [ ] No mocks for DB in API tests
- [ ] Each test only creates the data it needs
- [ ] All error cases are covered
- [ ] All tests use `client` and `db_session` fixtures

---

## 9. **If a Test Fails**

- Read the error: is it a validation error? (Check field lengths, types)
- Is the DB item missing? (Check if you added/committed it)
- Is the error code correct? (Check your API error handling)
- Is the test data isolated? (No leftover data from other tests)

---

## 10. **Implementation Strategy**

### **Phase 1: Fix Data Validation Issues**
1. Ensure all `txid` are exactly 64 characters
2. Verify all required fields are present
3. Test with minimal data sets

### **Phase 2: Implement Error Handling Tests**
1. Test 404 cases (no data in DB)
2. Test 400 cases (invalid input)
3. Test 422 cases (validation errors)

### **Phase 3: Add Comprehensive Coverage**
1. Test pagination with multiple records
2. Test security scenarios
3. Test response format validation

### **Phase 4: Performance and Edge Cases**
1. Test with large datasets
2. Test boundary conditions
3. Test concurrent access scenarios

---

## 11. **Success Metrics**

- ✅ All tests pass without mocks
- ✅ 100% API endpoint coverage
- ✅ All error scenarios covered
- ✅ Response format validation
- ✅ Security testing completed
- ✅ Performance within acceptable limits
