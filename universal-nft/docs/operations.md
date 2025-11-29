# Universal-NFT Operations

This document describes how `mint` and `transfer` operations work within the Universal-NFT extension, and how indexers reconstruct state deterministically.

---

## 1. Mint Operation

### 1.1 Purpose

Creates a new NFT on the Bitcoin blockchain and assigns its initial owner.

### 1.2 Payload Example

{
"p": "nft",
"op": "mint",
"tick":"EXAMPLE",
"meta":"abc",
"sig": "123",
"amt": "1"
}

### 1.3 Transaction Structure (Conceptual)

A valid mint transaction typically includes:

- One OP_RETURN output containing the JSON payload  
- One or more standard outputs (P2WPKH, P2TR, etc.)

Indexers reconstruct state by:

1. Scanning all outputs of the transaction  
2. Detecting an OP_RETURN containing a valid Universal-NFT mint payload  
3. Assigning ownership to the **first standard output after the OP_RETURN**

This behaviour is consistent with Universal/BRC-20.

### 1.4 Indexer Behavior

When a mint is detected:

- A new NFT is inserted into the index state  
- NFT identity = (`tick_normalized`, `meta`, `sig`)  
- Stored fields typically include:
  - owner → **first standard output after OP_RETURN**
  - block height  
  - txid  
  - timestamp  
  - optional ISPF metadata (meta_full, sig_full, category, ipfs)

## 2. Transfer Operation

### 2.1 Purpose

Transfers ownership of an existing NFT from one address to another.

### 2.2 Payload Example

{
"p": "nft",
"op": "transfer",
"tick":"EXAMPLE",
"meta":"abc",
"sig": "123"
}

### 2.3 Transaction Structure (Conceptual)

A valid Universal-NFT transfer transaction generally contains:

- Inputs referencing UTXOs owned by the current holder  
- One OP_RETURN with the transfer payload  
- One or more standard outputs  

Indexers determine:

- **from** = the address referenced by the **first input** of the transaction  
  (same rule used by Universal/BRC-20)

- **to** = the **first standard output after the OP_RETURN**

This ensures full compatibility with Universal conventions.

### 2.4 Indexer Behavior

When a transfer is detected:

1. Locate the NFT using (`tick_normalized`, `meta`, `sig`)  
2. Update:
   - owner → new address  
   - last_tx → current transaction ID  
   - last_update → timestamp  
3. Append an entry to the global `nft_operations` table, containing:
   - op = "transfer"  
   - tick / meta / sig  
   - from  
   - to  
   - block  
   - txid  
   - timestamp  

This global table mirrors the behaviour of `brc20_operations`.

## 3. Market Extensions (Optional)

Universal-NFT does not define marketplace operations at the protocol level.  
However, implementations may provide off-chain logic such as:

- Listing and delisting NFTs  
- Creating and signing sale agreements  
- Executing sales that ultimately map to on-chain `transfer` operations  

These do not modify the Universal-NFT protocol and remain optional application-level features.
