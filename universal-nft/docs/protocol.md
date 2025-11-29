# Universal-NFT Protocol Specification

## 1. Overview

Universal-NFT is an extension of the Universal / OPT protocol that defines how non-fungible assets (NFTs) are encoded, identified, and tracked on the Bitcoin blockchain.

The core idea is simple:

- NFTs are represented as UTF-8 JSON payloads inside an OP_RETURN output.
- The structure mirrors Universal/BRC-20, changing only the protocol identifier and the semantics of the fields.
- State reconstruction is fully deterministic and indexer-driven.

---

## 2. Payload Format

Every Universal-NFT action is encoded as a JSON object placed in an OP_RETURN output.

Minimal structure:

{
"p": "nft",
"op": "mint" | "transfer",
"tick": "<ticker>",
"meta": "<3-hex>",
"sig": "<3-hex>"
}

yaml
Copia codice

---

## 2.1 Field Definitions

### **p**
Protocol identifier.  
Always:

"p": "nft"

markdown
Copia codice

### **op**
Operation type:

- `"mint"` — creates a new NFT  
- `"transfer"` — transfers ownership of an existing NFT  

### **tick**
Identifier of the NFT collection.

- Allowed characters: any alphanumeric (A–Z, a–z, 0–9)  
- Recommended length: **1–7 characters**
- Indexers SHOULD normalize tickers to **uppercase**, consistent with Universal conventions  
  (e.g., `satoshi` → `SATOSHI`).

Regex:

^[A-Za-z0-9]{1,7}$

markdown
Copia codice

### **meta**
A short on-chain tag derived from the SHA-256 of the NFT image.

- Defined as: **last 3 hex characters** of the image hash
- Not intended to be globally unique (4096 possible values)

### **sig**
A second deterministic short tag.

- Defined as: last 3 hex characters of a deterministic hash (`sig_full`)
- Not a cryptographic signature and does **not** rely on any private key
- Used together with `tick` and `meta` to identify the NFT tuple

### **amt** (optional)
Defaults to `"1"` for all NFTs.

---

## 3. JSON Encoding Rules

- UTF-8 encoding only  
- Must be valid JSON  
- No trailing commas  
- Field order is not enforced  
- Extra fields MUST be ignored for forward compatibility  

---

## 4. Validation Rules

A Universal-NFT payload is considered valid if:

1. `p` is exactly `"nft"`
2. `op` is `"mint"` or `"transfer"`
3. `tick` matches `^[A-Za-z0-9]{1,7}$`
4. `meta` matches `^[a-f0-9]{3}$`
5. `sig` matches `^[a-f0-9]{3}$`
6. JSON is valid UTF-8
7. Payload sits inside an OP_RETURN output

NFT state must be reconstructed deterministically from on-chain events.

---

## 5. Identity Model

An NFT is uniquely identified by the tuple:

( tick_normalized , meta , sig )

yaml
Copia codice

Notes:

- `meta` is a compact “bucket”, not a unique identifier  
- `sig` adds additional entropy  
- The full SHA-256 hash in the sidecar metadata is the canonical identity source  
- Indexers use both on-chain and sidecar data to resolve potential collisions

---

## 6. Ownership Model

Universal-NFT adopts the same ownership rules as Universal/BRC-20:

- For **mint** operations:  
  owner = **first standard output after OP_RETURN**

- For **transfer** operations:  
  - `from` = address referenced by the **first input**  
  - `to`   = first standard output after OP_RETURN  

State is built exclusively from blockchain events with no external assertions.

---

## 7. Design Principles

- minimal on-chain footprint  
- deterministic analysis  
- state reconstruction driven by indexers  
- forward compatibility  
