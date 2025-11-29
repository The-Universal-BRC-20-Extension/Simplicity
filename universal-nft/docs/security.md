# Universal-NFT Security Model

This document describes the security assumptions and trust boundaries of the Universal-NFT extension.

---

## 1. Wallet Custody

- Private keys remain **entirely** inside the user's wallet.  
- The application **never requests**, stores, or handles:
  - private keys  
  - seed phrases  
  - hardware wallet secrets  

- All critical operations (mint, transfer, optional market actions) are executed using:
  - PSBT (Partially Signed Bitcoin Transactions), or  
  - native wallet message signing.

The wallet signs **locally** and broadcasts the final transaction.

---

## 2. Server Responsibilities

A typical Universal-NFT implementation may:

- Scan Bitcoin blocks and decode OP_RETURN payloads  
- Maintain local state (NFT records, history, pending operations)  
- Store media files and sidecar metadata (ISPF pattern)  
- Provide deterministic hashing to produce `sig_full` → `sig`  

But the server:

- **Never controls UTXOs**  
- **Never signs Bitcoin transactions**  
- **Never has access to private keys**

It acts only as an indexer and metadata provider.

---

## 3. Trust Boundary

- Bitcoin consensus establishes the authoritative record of NFT operations  
- Wallets guarantee ownership via private keys  
- Indexers reconstruct state deterministically from on-chain data  

If metadata or servers disappear, the NFTs remain valid and discoverable purely from the blockchain.

---

## 4. Attack Surface Considerations

Even though Universal-NFT is minimal, implementations should consider:

- User interface integrity (no fake transaction prompts)  
- Safe handling of external URLs in metadata  
- Basic rate limiting to avoid API abuse  

None of these affect the **on-chain state**, but improve overall robustness.

---

## 5. Summary

- Universal-NFT keeps Bitcoin as the single source of truth  
- Wallets remain the only holders of cryptographic authority  
- Servers are optional helpers, not custodians  
- The protocol is intentionally simple:
  > If it is not on-chain and signed by the wallet, it is not authoritative
