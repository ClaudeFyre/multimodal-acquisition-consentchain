"""Shared ledger interface: the single seam between the analysis code (B1, A2) and any blockchain.

Architecture (papers/b1_jbhi Fig. 1): off-chain evidence repository -> multimodal analysis -> structured
conclusion -> submission payload -> [smart-contract anchoring] -> on-chain records -> [performance monitoring]
-> sustainability decision support. The bracketed steps are blockchain components; all of them sit behind
`Ledger`, so the analysis code never changes when the backend does.

Backends:
- `LocalHashChainLedger`: append-only JSONL with SHA-256 hash chaining. Implements the same checks a smart
  contract would (authorized submitter + record schema). It is the *centralized audit log* baseline and lets
  the pipeline run end-to-end on one machine.
- `BlockchainLedger`: 【区块链接口位置】 permissioned chain (Hyperledger Fabric chaincode / EVM contract).
  Not implemented on this machine (decision 2026-10-08).

Rule: payloads carry only hashes, commitments, Merkle roots, model versions, public license ids and short
aggregate conclusions. Patient identifiers, salts, feature values never reach `append`.
"""
from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

# ---------------------------------------------------------------- event schema (= smart-contract ABI)
ANALYSIS_RECORD = "ANALYSIS_RECORD"        # B1: structured conclusion + evidence hash + URI (architecture "submission payload")
REGISTER_SAMPLE = "REGISTER_SAMPLE"        # A2: a training sample enters the governed pool
SET_CONSENT = "SET_CONSENT"                # A2: consent granted / revoked for a sample commitment
ANCHOR_MODEL = "ANCHOR_MODEL"              # A2: model version + shard Merkle roots
UNLEARNING_RECEIPT = "UNLEARNING_RECEIPT"  # A2: proof-of-procedure that a revoked sample was removed
LICENSE_AUDIT = "LICENSE_AUDIT"            # A2: license-policy check of a training set

EVENT_FIELDS = {
    ANALYSIS_RECORD: {"record_id", "conclusion", "evidence_hash", "evidence_uri", "model_version", "confidence"},
    REGISTER_SAMPLE: {"commitment", "license_id", "dataset_commitment", "shard_id"},
    SET_CONSENT: {"commitment", "state"},
    ANCHOR_MODEL: {"model_id", "model_hash", "shard_roots", "parent_model_hash"},
    UNLEARNING_RECEIPT: {"commitment", "shard_id", "old_shard_root", "new_shard_root",
                         "old_model_hash", "new_model_hash", "consent_tx"},
    LICENSE_AUDIT: {"model_id", "policy", "n_samples", "violations"},
}
FORBIDDEN_KEYS = {"patient_key", "patient_id", "salt", "features", "source_patient_id"}
MAX_CONCLUSION_CHARS = 512   # keep on-chain records compact; details live in the off-chain evidence


@dataclass(frozen=True)
class Event:
    kind: str
    payload: dict
    org: str = "local"           # submitter (Fabric MSP id / EVM address on a real chain)
    ts: float = field(default_factory=time.time)

    def validate(self) -> None:
        """Record-schema check (the contract's `require(...)` statements)."""
        if self.kind not in EVENT_FIELDS:
            raise ValueError(f"unknown event kind {self.kind}")
        missing = EVENT_FIELDS[self.kind] - self.payload.keys()
        if missing:
            raise ValueError(f"{self.kind} missing fields {sorted(missing)}")
        leaked = FORBIDDEN_KEYS & self.payload.keys()
        if leaked:
            raise ValueError(f"personal/secret fields must never reach the ledger: {sorted(leaked)}")
        if self.kind == ANALYSIS_RECORD and len(str(self.payload["conclusion"])) > MAX_CONCLUSION_CHARS:
            raise ValueError("conclusion too long for an on-chain record; put details in the evidence")


@dataclass(frozen=True)
class Receipt:
    """Transaction metadata (architecture "On-chain records / Transaction metadata")."""
    tx_id: str                       # tx hash; local log: entry hash
    index: int                       # block number / log position
    prev_hash: str
    status: str = "confirmed"        # confirmed | rejected
    submitter: str = "local"
    contract: str = "local-log"      # contract / chaincode address
    submitted_at: float = 0.0
    confirmed_at: float = 0.0
    gas_used: int | None = None      # chain only

    @property
    def latency_s(self) -> float:
        return self.confirmed_at - self.submitted_at


class Ledger(ABC):
    """Backend interface. The papers' claims depend only on these calls."""

    def __init__(self, authorized_orgs: Iterable[str] | None = None):
        self.authorized = set(authorized_orgs) if authorized_orgs else None

    def check_submitter(self, event: Event) -> None:
        """Contract check: only authorized signers may write."""
        if self.authorized is not None and event.org not in self.authorized:
            raise PermissionError(f"submitter {event.org!r} is not authorized")

    @abstractmethod
    def append(self, event: Event) -> Receipt: ...

    @abstractmethod
    def events(self, kind: str | None = None) -> Iterator[tuple[Receipt, Event]]: ...

    @abstractmethod
    def verify(self) -> bool:
        """Integrity of the whole history (hash chain locally; blocks + endorsements on a chain)."""

    def consent_state(self, commitment: str) -> str:
        state = "granted"
        for _, ev in self.events(SET_CONSENT):
            if ev.payload["commitment"] == commitment:
                state = ev.payload["state"]
        return state


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class LocalHashChainLedger(Ledger):
    """Append-only JSONL; entry_hash = sha256(prev_hash || canonical(event)). Centralized-log baseline."""

    GENESIS = "0" * 64

    def __init__(self, path: Path, authorized_orgs: Iterable[str] | None = None):
        super().__init__(authorized_orgs)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._idx, self._head = -1, self.GENESIS
        for row in self._rows():
            self._idx, self._head = row["index"], row["hash"]

    def _rows(self):
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    def append(self, event: Event) -> Receipt:
        t0 = time.time()
        self.check_submitter(event)
        event.validate()
        body = asdict(event)
        h = hashlib.sha256(self._head.encode() + canonical(body)).hexdigest()
        row = {"index": self._idx + 1, "prev_hash": self._head, "hash": h, "event": body}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        rc = Receipt(h, self._idx + 1, self._head, submitter=event.org, submitted_at=t0, confirmed_at=time.time())
        self._idx, self._head = rc.index, h
        return rc

    def events(self, kind=None):
        for row in self._rows():
            ev = Event(**row["event"])
            if kind is None or ev.kind == kind:
                yield Receipt(row["hash"], row["index"], row["prev_hash"], submitter=ev.org), ev

    def verify(self) -> bool:
        prev = self.GENESIS
        for i, row in enumerate(self._rows()):
            if row["index"] != i or row["prev_hash"] != prev:
                return False
            if hashlib.sha256(prev.encode() + canonical(row["event"])).hexdigest() != row["hash"]:
                return False
            prev = row["hash"]
        return True


class BlockchainLedger(Ledger):
    """【区块链接口位置】 Permissioned-chain backend. Not implemented on this machine.

    Mapping to implement (see experiments/chain_interface/README.md):
      append(event) -> check_submitter + event.validate() locally, then submit a transaction to contract
                       function `<event.kind>(payload)` signed by `event.org`; wait for confirmation and
                       return Receipt(tx hash, block number, previous block hash, status, submitter, contract
                       address, submitted_at, confirmed_at, gas_used).
      events(kind)  -> read contract events / world state filtered by kind, ordered by (block, tx index).
      verify()      -> validate the block hash chain and endorsement policy over the full history.
    `benchmark.py` then reports gas per transaction, TPS and confirmation latency for this backend versus
    LocalHashChainLedger over the same fixed measurement window.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Blockchain backend is reserved for the chain experiments (not run on this machine).")

    def append(self, event):  # pragma: no cover
        raise NotImplementedError

    def events(self, kind=None):  # pragma: no cover
        raise NotImplementedError

    def verify(self):  # pragma: no cover
        raise NotImplementedError
