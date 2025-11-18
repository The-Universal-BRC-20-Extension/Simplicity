# Universal-NFT Operations

This document describes how `mint` and `transfer` operations work within the Universal-NFT extension, and how indexers and tools are expected to interpret them.

---

## 1. Mint Operation

### 1.1 Purpose

Creates a new NFT on the Bitcoin blockchain and assigns its initial owner.

### 1.2 Payload Example

{
  "p":   "nft",
  "op":  "mint",
  "tick":"example",
  "meta":"abc",
  "sig": "123",
  "amt": "1"
}

### 1.3 Transaction Structure (Conceptual)

A valid mint transaction typically includes:

- One or more standard outputs (P2WPKH, P2TR, etc.)
- One OP_RETURN output containing the JSON payload

Indexers reconstruct state by:

1. Scanning all transaction outputs  
2. Detecting an OP_RETURN containing a valid Universal-NFT mint payload  
3. Assigning ownership to the **first standard output** of the transaction  

### 1.4 Indexer Behavior

When a mint is detected:

- A new NFT is created in the index state  
- The NFT is identified by the tuple: (`tick`, `meta`, `sig`)  
- Stored fields typically include:
  - owner (first standard output)
  - block height  
  - transaction ID  
  - timestamps  
  - optional ISPF fields (meta_full, sig_full, category, ipfs)

---

## 2. Transfer Operation

### 2.1 Purpose

Transfers ownership of an existing NFT from one address to another.

### 2.2 Payload Example

{
  "p":   "nft",
  "op":  "transfer",
  "tick":"example",
  "meta":"abc",
  "sig": "123"
}

### 2.3 Transaction Structure (Conceptual)

A valid Universal-NFT transfer transaction generally contains:

- Inputs referencing UTXOs controlled by the current owner  
- One or more standard outputs  
- One OP_RETURN output embedding the transfer payload  

Indexers determine:

- **from**: derived from the previous outputs referenced by the transaction inputs  
- **to**: the address contained in the first standard output  

### 2.4 Indexer Behavior

When a transfer is detected:

1. Locate the NFT using (`tick`, `meta`, `sig`)  
2. Update:
   - owner → new address  
   - last_tx → current transaction ID  
   - last_update → timestamp  
3. Append an entry to transfer history:
   - op = transfer  
   - from → previous owner  
   - to → new owner  
   - block  
   - txid  
   - timestamp  

---

## 3. Market Extensions (Optional)

Universal-NFT does not define marketplace operations at the protocol level.  
However, applications may implement off-chain logic such as:

- Listing NFTs for sale  
- Buying listed NFTs  
- Recording signed sale agreements  
- Linking economic actions to on-chain `transfer` operations  

These market features **do not modify** the Universal-NFT protocol itself and are considered optional, application-level extensions.
