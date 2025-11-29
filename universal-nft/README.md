# Universal-NFT
### Extension of the Universal / OPT Protocol for Bitcoin-Native NFTs

Universal-NFT extends the Universal / OPT payload architecture to support non-fungible assets (NFTs) directly on the Bitcoin blockchain.  
It preserves the same minimal and sovereign design of Universal, changing only the protocol identifier:

{"p":"nft", ... }

This folder documents how the NFT extension fits within the Universal ecosystem and how non-fungible assets can be represented, validated, and transferred using standard Bitcoin transactions.

---

## Purpose

- Provide a clean, minimal, and fully on-chain specification for Bitcoin NFTs.  
- Reuse the Universal JSON OP_RETURN structure.  
- Maintain full compatibility with the Universal philosophy and format.  
- Demonstrate that the OPT model is not limited to fungible tokens (BRC-20), but can be extended to unique digital primitives.

---

## Core Concepts

- Every NFT exists as a JSON payload inside an OP_RETURN output.  
- The NFT identity is defined by:
  - tick — NFT family or collection identifier  
  - meta — 3-character tag derived from the image hash  
  - sig  — 3-character tag derived from deterministic server-side hashing  
- Ownership is determined by the first standard output of the transaction.  
- Transfers are performed through PSBT-signed transactions crafted and signed entirely by the user’s wallet.

---

## Documentation Structure

This folder contains the following documents:

- docs/protocol.md – NFT protocol specification  
- docs/operations.md – Mint / Transfer workflow and lifecycle  
- docs/isp_flow.md – Image Storage & Provenance Flow (ISPF)  
- docs/security.md – Security model (wallet custody, signing, trust boundaries)

---

## Compatibility

- Fully aligned with the Universal JSON payload standard.  
- Same OP_RETURN schema, same field style, compatible indexing logic.  
- Designed to coexist with BRC-20 and any other OPT-based protocol.

---

## Credits

All base design concepts belong to the Universal / OPT protocol.  
This extension is a community contribution exploring non-fungible use cases within the same architectural model.

---

## License

Same license as the parent Universal repository.
