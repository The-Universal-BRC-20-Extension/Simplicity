# Simplicity Indexer API Reference

## Interactive Documentation
- [Swagger UI](http://localhost:8080/docs)
- [ReDoc](http://localhost:8080/redoc)

## BRC-20 Endpoints

### Health & Status
- **GET** `/v1/indexer/brc20/health` — Get Health Check
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/health
  # Expected output:
  # { "status": "ok" }
  ```
- **GET** `/v1/indexer/brc20/status` — Get Indexer Status
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/status
  # Expected output:
  # {
  #   "current_block_height_network": 840000,
  #   "last_indexed_block_main_chain": 839999,
  #   "last_indexed_brc20_op_block": 839998
  # }
  ```

### Token Listing & Info
- **GET** `/v1/indexer/brc20/list` — Get BRC-20 List
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/list
  # Expected output: [ { ...Brc20InfoItem }, ... ]
  ```
- **GET** `/v1/indexer/brc20/{ticker}/info` — Get Ticker Info
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/BTC/info
  # Expected output: { ...Brc20InfoItem }
  ```
- **GET** `/v1/indexer/brc20/{ticker}/holders` — Get Ticker Holders
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/BTC/holders
  # Expected output: [ { ...AddressBalance }, ... ]
  ```
- **GET** `/v1/indexer/brc20/{ticker}/history` — Get Ticker History
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/BTC/history
  # Expected output: [ { ...Op }, ... ]
  ```
- **GET** `/v1/indexer/brc20/{ticker}/tx/{txid}/history` — Get Ticker Tx History
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/BTC/tx/abcd1234/history
  # Expected output: [ { ...Op }, ... ]
  ```

### Address Endpoints
- **GET** `/v1/indexer/address/{address}/brc20/{ticker}/info` — Get Address Ticker Balance
  ```bash
  curl http://localhost:8080/v1/indexer/address/bc1q.../brc20/BTC/info
  # Expected output: { ...AddressBalance }
  ```
- **GET** `/v1/indexer/address/{address}/history` — Get Address History General
  ```bash
  curl http://localhost:8080/v1/indexer/address/bc1q.../history
  # Expected output: [ { ...Op }, ... ]
  ```
- **GET** `/v1/indexer/address/{address}/brc20/{ticker}/history` — Get Address Ticker History
  ```bash
  curl http://localhost:8080/v1/indexer/address/bc1q.../brc20/BTC/history
  # Expected output: [ { ...Op }, ... ]
  ```

### History by Block Height
- **GET** `/v1/indexer/brc20/history-by-height/{height}` — Get History By Height
  ```bash
  curl http://localhost:8080/v1/indexer/brc20/history-by-height/840000
  # Expected output: [ { ...Op }, ... ]
  ```

### Root
- **GET** `/` — Root
  ```bash
  curl http://localhost:8080/
  # Expected output: { "message": "Simplicity Indexer API" }
  ```

## Schemas

### AddressBalance
```json
{
  "pkscript": "string",
  "ticker": "string",
  "wallet": "string",
  "overall_balance": "string",
  "available_balance": "string",
  "block_height": 123456
}
```

### Brc20InfoItem
```json
{
  "ticker": "string",
  "decimals": 18,
  "max_supply": "string",
  "limit_per_mint": "string",
  "actual_deploy_txid_for_api": "string",
  "deploy_tx_id": "string",
  "deploy_block_height": 123456,
  "deploy_timestamp": "2025-07-08T13:00:00Z",
  "creator_address": "string",
  "remaining_supply": "string",
  "current_supply": "string",
  "holders": 123
}
```

### IndexerStatus
```json
{
  "current_block_height_network": 840000,
  "last_indexed_block_main_chain": 839999,
  "last_indexed_brc20_op_block": 839998
}
```

### Op
```json
{
  "id": 1,
  "tx_id": "string",
  "txid": "string|null",
  "op": "deploy|mint|transfer",
  "ticker": "string",
  "amount_str": "string|null",
  "block_height": 123456,
  "block_hash": "string",
  "tx_index": 0,
  "timestamp": "2025-07-08T13:00:00Z",
  "from_address": "string|null",
  "to_address": "string|null",
  "valid": true
}
```

### HTTPValidationError
```json
{
  "detail": [
    {
      "loc": ["string", 0],
      "msg": "string",
      "type": "string"
    }
  ]
}
```

