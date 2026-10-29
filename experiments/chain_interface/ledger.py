"""Shared ledger interface: the single seam between the analysis code (B1, A2) and any blockchain.

Architecture (papers/b1_jbhi Fig. 1): off-chain evidence repository -> multimodal analysis -> structured
conclusion -> submission payload -> [smart-contract anchoring] -> on-chain records -> [performance monitoring]
-> sustainability decision support. The bracketed steps are blockchain components; all of them sit behind
`Ledger`, so the analysis code never changes when the backend does.

Backends:
- `LocalHashChainLedger`: append-only JSONL with SHA-256 hash chaining. Implements the same checks a smart
  contract would (authorized submitter + record schema). It is the *centralized audit log* baseline and lets
  the pipeline run end-to-end on one machine.
- `BlockchainLedger`: B1 ANALYSIS_RECORD backend for an EVM registry, including Ethereum Sepolia.
  A2 consent/unlearning event types remain outside this backend's implemented scope.

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
    """B1 EVM backend with recoverable on-chain aggregate fields and immutable evidence hashes.

    event.org is a logical pipeline label checked locally; Receipt.submitter is the actual signer.
    verify() checks RPC receipt/block linkage and contract digests. Consensus validation is delegated
    to the selected node, and this method does not establish permissioned-chain endorsement or finality.
    Repeated append of identical immutable content returns its existing receipt without another write.
    """

    def __init__(self, rpc_url=None, contract_address=None, chain_id=11155111,
                 deployment_block=None, sender=None, authorized_orgs=None, node_executable="node"):
        super().__init__(authorized_orgs)
        self.evm = Path(__file__).resolve().parent / "evm"
        config = json.loads((self.evm / "config/sepolia.json").read_text())
        state_path = self.evm / "results/sepolia_deployment.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        address = contract_address or state.get("contractAddress")
        if not address:
            raise ValueError("Deploy the registry first or pass contract_address")
        if deployment_block is None:
            deployment_block = next((t["blockNumber"] for t in state.get("transactions", [])
                                     if t.get("label") == "deployment" and t.get("status") == 1), 0)
        self.node_executable = node_executable
        self.options = {"rpc_url": rpc_url or config["rpcUrl"], "chain_id": chain_id,
                        "contract_address": address, "deployment_block": deployment_block,
                        "sender": sender, "logical_org": "b1-analysis"}
        self.reused_receipts = 0

    def _call(self, action, **kwargs):
        import subprocess
        request = {**self.options, "action": action, **kwargs}
        run = subprocess.run([self.node_executable, str(self.evm / "scripts/ledger_bridge.mjs")],
                             input=json.dumps(request), text=True, capture_output=True, timeout=240)
        if run.returncode:
            raise RuntimeError(run.stderr.strip() or "EVM bridge failed")
        return json.loads(run.stdout)

    def append(self, event):
        self.check_submitter(event)
        event.validate()
        if event.kind != ANALYSIS_RECORD:
            raise NotImplementedError("The implemented EVM backend covers B1 ANALYSIS_RECORD only")
        extra = set(event.payload) - EVENT_FIELDS[ANALYSIS_RECORD]
        if extra:
            raise ValueError(f"unexpected ANALYSIS_RECORD fields {sorted(extra)}")
        result = self._call("append", event=asdict(event))
        self.reused_receipts += int(result.get("reused", False))
        return Receipt(**result["receipt"])

    def events(self, kind=None):
        if kind not in (None, ANALYSIS_RECORD):
            return
        for row in self._call("events"):
            yield Receipt(**row["receipt"]), Event(**row["event"])

    def verify(self):
        return bool(self._call("verify")["valid"])
