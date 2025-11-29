# ISPF — Image Storage & Provenance Flow

Universal-NFT assumes that each NFT references a binary media asset (typically an image).  
To keep the on-chain payload compact while preserving strong provenance guarantees, an  
**Image Storage & Provenance Flow (ISPF)** is used.

---

## 1. Purpose

- Link each NFT to a specific image or media file  
- Ensure verifiable provenance through deterministic hashing  
- Avoid storing large binary data directly on Bitcoin  
- Provide indexers with off-chain metadata for exact validation and identity resolution  

---

## 2. Image Hashing

On the client side:

1. The original image file (e.g., PNG) is hashed using SHA-256.  
2. The **full SHA-256 hash** is stored off-chain as `meta_full`.  
3. The **last 3 hexadecimal characters** of the hash become the compact on-chain field `meta`.

Example:

- SHA-256: `...fa9c`  
- meta = `a9c`

### Collision Note
With only 3 hex characters (`16 × 16 × 16 = 4,096` possibilities),  
**collisions are expected** and fully acceptable.

`meta` is not intended to be unique — it is only a compact bucket.  
The *canonical* identity is provided by the full SHA-256 hash in the sidecar.

Indexers use the tuple `(tick_normalized, meta, sig)` together with the sidecar  
to resolve any meta collisions deterministically.

---

## 3. Deterministic Signature (sig / sig_full)

A second deterministic hash is used to create an additional tag.

- `sig_full` is a SHA-256 hash computed deterministically from NFT metadata  
  (e.g., image hash + tick + collection rules)
- `sig` is the **last 3 hex characters** of `sig_full`

Important:

- `sig` is **not** a cryptographic signature  
- No private key is involved  
- It is simply a second compact on-chain discriminator  
- It does not replace the full hash, which remains authoritative

This approach keeps the on-chain footprint minimal while still allowing  
trustless identity reconstruction.

---

## 4. Sidecar Metadata Files (Off-Chain)

Implementations may store image files and metadata using a structured naming scheme such as:

- `images/<tick>_<meta>_<sig>.png`  
- `images/<tick>_<meta>_<sig>.json`

A typical sidecar JSON file may contain:

{
"meta": "<short_meta>",
"sig": "<short_sig>",
"longmeta": "<full_sha256_image_hash>",
"longsig": "<full_sha256_signature_hash>",
"category": "<optional_category>"
}

Indexers may use these fields to enrich state:

- `meta_full`  
- `sig_full`  
- optional metadata (category, ipfs CID, tags, attributes, etc.)

Because the sidecar contains canonical hashes, indexers can  
deterministically resolve any `meta` or `sig` collisions that appear on-chain.

---

## 5. Optional Content Addressed Storage (CAS)

Universal-NFT does not require a specific storage system.  
Implementations MAY store media on decentralized or content-addressed networks:

- IPFS  
- Filecoin  
- Arweave  
- Other CAS layers  

The resulting content hash (e.g., CID) MAY be included in the sidecar for richer metadata,  
but it does not influence the protocol-level state.

---

## 6. Summary

ISPF provides a minimal and verifiable structure for:

- Linking NFTs to their media  
- Ensuring provenance through deterministic hashing  
- Allowing indexers to rebuild identity deterministically  
- Avoiding on-chain bloat  
- Supporting future-proof and storage-agnostic metadata standards
