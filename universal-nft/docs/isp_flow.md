# ISPF — Image Storage & Provenance Flow

Universal-NFT assumes that each NFT is linked to binary media (typically an image).  
To keep the on-chain payload compact while preserving trustless provenance, an **Image Storage & Provenance Flow (ISPF)** is used.

---

## 1. Purpose

- Bind each NFT to a specific image or media file  
- Ensure verifiable provenance using hashes  
- Avoid storing large data directly on Bitcoin  
- Allow indexers to enrich NFT metadata off-chain

---

## 2. Image Hashing

On the client side:

1. The original image file (e.g., PNG) is hashed using SHA-256.  
2. The **full hash** is kept off-chain as `meta_full`.  
3. The **last 3 hexadecimal characters** of the hash become the on-chain `meta` tag.

Example:

- SHA-256: `...fa9c`  
- meta = `a9c`

This ensures a deterministic link between the image and the NFT payload.

---

## 3. Deterministic Signature (sig / sig_full)

A second deterministic hash is used for provenance:

- A server or verifier computes a SHA-256 hash (`sig_full`)  
- The **last 3 hex characters** of this hash become the on-chain `sig`

This provides:

- A binding between the NFT and its off-chain metadata  
- A deterministic signature lineage  
- Compatibility with Universal hashing practices

---

## 4. Sidecar Metadata Files (Off-Chain)

Applications may store media and accompanying metadata as:

- `images/<tick>_<meta>_<sig>.png`  
- `images/<tick>_<meta>_<sig>.json`

A typical sidecar JSON may contain:

{
  "meta": "<short_meta>",
  "sig": "<short_sig>",
  "longmeta": "<full_sha256_image_hash>",
  "longsig": "<full_sha256_signature_hash>",
  "category": "<optional_category>"
}

Indexers may use this sidecar to populate:

- meta_full  
- sig_full  
- optional metadata (category, ipfs, tags, etc.)

---

## 5. Optional Content Addressed Storage

Universal-NFT does not require a specific storage system.  
However, implementations may upload media to decentralized storage such as:

- IPFS  
- Filecoin  
- Arweave  
- Other CAS layers  

The resulting content hash (e.g., IPFS CID) can be added as optional metadata in local indexing systems.

---

## 6. Summary

ISPF provides a clean and minimal approach to:

- Link images to NFTs  
- Preserve provenance  
- Avoid on-chain bloat  
- Allow future-proof, storage-agnostic metadata extensions
