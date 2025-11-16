# Universal-NFT Protocol Specification

## 1. Overview

Universal-NFT is an extension of the Universal / OPT protocol that defines how non-fungible assets (NFTs) are encoded, identified, and tracked on the Bitcoin blockchain.

The core idea is simple:

- NFTs are represented as a UTF-8 JSON payload inside an OP_RETURN output.
- The structure mirrors the style of Universal (BRC-20), changing only the protocol identifier and the semantics of the fields.

---

## 2. Payload Format

Every Universal-NFT action is encoded as a JSON object stored in OP_RETURN.

Minimal structure:

{
  "p":   "nft",
  "op":  "mint" or "transfer",
  "tick":"<ticker>",
  "meta":"<3-hex-tag>",
  "sig": "<3-hex-tag>"
}

---

### 2.1 Field Definitions

- **p**  
  Protocol identifier. Always `"nft"` for this extension.

- **op**  
  Operation type:  
  - `"mint"` – creates a new NFT  
  - `"transfer"` – transfers ownership of an existing NFT  

- **tick**  
  NFT collection or identifier.  
  Lowercase alphanumeric plus underscore (`[a-z0-9_]`).  
  Recommended length: up to 7 characters.

- **meta**  
  3-character hex tag derived from the SHA-256 hash of the NFT image.  
  Defined as: last 3 hex characters of the image hash.

- **sig**  
  3-character deterministic signature derived from a server-side hash (sig_full).  
  Defined as: last 3 hex characters of the server hash.

- **amt** (optional)  
  String quantity. Defaults to `"1"`.  
  For NFTs this value is typically constant and equal to `"1"`.

---

## 3. JSON Encoding Rules

- UTF-8 encoding only.  
- Must be valid JSON.  
- No trailing commas.  
- Field order is not enforced.  
- Extra fields should be ignored by indexers for forward compatibility.

---

## 4. Validation Rules

A Universal-NFT payload is considered valid if:

1. "p" must be exactly "nft".
2. "op" must be either "mint" or "transfer".
3. "tick" must match ^[A-z 0-9]{1,7}$.
4. "meta" and "sig" must match ^[a-f 0-9]{3}$.
5. Payload must be valid UTF-8 JSON embedded in an OP_RETURN output.

Indexers may enrich NFTs with additional off-chain data (for example via ISPF), but the rules above define protocol-level validity.

---

## 5. Relationship to Universal (BRC-20)

- Universal-BRC-20 uses `p = "brc-20"` and fungible token semantics.  
- Universal-NFT uses `p = "nft"` and non-fungible semantics.  
- Both share:
  - JSON-in-OP_RETURN encoding  
  - minimal on-chain footprint  
  - deterministic parsing  
  - indexer-driven state reconstruction  

This design keeps Bitcoin consensus untouched while allowing digital primitives to be defined by payloads.
