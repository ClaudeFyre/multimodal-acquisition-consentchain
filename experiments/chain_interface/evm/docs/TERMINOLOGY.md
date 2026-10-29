# Terminology and evidence boundaries

| Term | Meaning in this artifact |
|---|---|
| B1 analysis record | Original aggregate conclusion from `b1_cost_acquisition/anchor_results.py`; two records |
| evidenceHash | SHA-256 of native Python JSON serialization of sorted six-file path/hash pairs |
| modelSpecHash | SHA-256 of `model_specification.json`; specification and source checksums, without trained weights |
| resultHash | SHA-256 of ABI-encoded source ID, conclusion, evidence hash, URI, model version and confidence |
| recordId | SHA-256 of UTF-8 native source ID |
| metadataHash | Keccak-256 of ABI-encoded display name and description |
| registration | Immutable analysis fields plus initial display metadata |
| metadata revision | Versioned change of display name/description; immutable fields stay fixed |
| receipt latency | Client elapsed submission-to-successful-receipt time; one confirmation |
| submission start | Original client wall-clock timestamp before the RPC send; UTC in the paper |
| block time | Timestamp of the canonical inclusion block from RPC; seconds resolution; UTC in the paper |
| effective gas price | Receipt effectiveGasPrice in wei per gas; 1 gwei = 10^9 wei |
| actual transaction fee | Receipt gasUsed multiplied by effectiveGasPrice; 1 SepoliaETH = 10^18 wei |
| public paper table | Four successful operations; fees shown in 10^-9 SepoliaETH; totals use the same four rows |
| observed throughput | Completed writes divided by repetition completion span under stated concurrency |
| consensus finality | Separate network property; one receipt is not used as evidence of finality |
| technical repetition | One batch of 16 load records; three per backend/payload class |
| synthetic load | Schema-conforming records for overhead measurement; no additional model inference |
| signed log | Additional EIP-191-signed, SHA-256-chained, fsynced JSONL comparison |
| LocalHashChainLedger | Original unsigned local reference log, preserved as supplied |
| integrity check | Equality of a recomputed commitment with the registered value; no truth validation |
| supported EVM scope | B1 ANALYSIS_RECORD only; A2 remains outside this backend |

Use the recorded network ID whenever reporting gas and latency. Keep local timing and public-network receipts separate. Full public transaction hashes belong in receipt artifacts; the paper links to the contract and states the limited workload.
