"""Sharded, isolated training (SISA-style) + Merkle roots + the unlearning orchestration.

ML side of A2. It calls the ledger only through `ledger.Ledger`, so swapping LocalHashChainLedger for the
blockchain backend changes nothing here.

Exact unlearning by construction: each shard model is trained only on its own samples, so removing a sample
and retraining its shard yields a model in which the sample never influenced any weight.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, Sequence

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "chain_interface"))  # shared ledger interface

from ledger import ANCHOR_MODEL, SET_CONSENT, UNLEARNING_RECEIPT, Event, Ledger, Receipt


def shard_of(commitment: str, n_shards: int) -> int:
    return int(commitment[:16], 16) % n_shards


# ---------- Merkle tree over sorted commitments (shard membership proofs) ----------
def _h(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(a + b).digest()


def merkle_root(leaves: Sequence[str]) -> str:
    level = [bytes.fromhex(x) for x in sorted(leaves)]
    if not level:
        return hashlib.sha256(b"").hexdigest()
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [_h(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_proof(leaves: Sequence[str], leaf: str) -> list[tuple[str, str]]:
    """[(side, sibling_hex)] path from leaf to root; side = 'L' if the sibling is on the left."""
    level = [bytes.fromhex(x) for x in sorted(leaves)]
    i = level.index(bytes.fromhex(leaf))
    path = []
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sib = i ^ 1
        path.append(("L" if sib < i else "R", level[sib].hex()))
        level = [_h(level[k], level[k + 1]) for k in range(0, len(level), 2)]
        i //= 2
    return path


def merkle_verify(leaf: str, proof: list[tuple[str, str]], root: str) -> bool:
    cur = bytes.fromhex(leaf)
    for side, sib in proof:
        cur = _h(bytes.fromhex(sib), cur) if side == "L" else _h(cur, bytes.fromhex(sib))
    return cur.hex() == root


# ---------- trainer interface (the medical model plugs in here) ----------
class ShardTrainer(Protocol):
    """【医学模型接口位置】Implement with the real model (e.g. B1's Cox / multimodal survival model, or a LoRA
    adapter of a small VLM). `train_shard` must use ONLY the given commitments' data."""

    def train_shard(self, shard_id: int, commitments: Sequence[str]) -> bytes:
        """Train one shard; return serialized weights (their sha256 is anchored)."""

    def evaluate(self, shard_weights: dict[int, bytes]) -> dict:
        """Evaluate the aggregated ensemble on the held-out set; return metrics (e.g. 3-year Uno C-index)."""


@dataclass
class ShardedModel:
    shards: dict[int, list[str]]       # shard_id -> commitments
    weights: dict[int, bytes]          # shard_id -> serialized weights
    model_hash: str = ""

    def roots(self) -> dict[str, str]:
        return {str(s): merkle_root(c) for s, c in sorted(self.shards.items())}

    def compute_hash(self) -> str:
        h = hashlib.sha256()
        for s in sorted(self.weights):
            h.update(str(s).encode() + hashlib.sha256(self.weights[s]).digest())
        return h.hexdigest()


def train_all(trainer: ShardTrainer, commitments: Sequence[str], n_shards: int, ledger: Ledger,
              model_id: str, parent: str = "") -> tuple[ShardedModel, Receipt]:
    shards: dict[int, list[str]] = {s: [] for s in range(n_shards)}
    for c in commitments:
        shards[shard_of(c, n_shards)].append(c)
    m = ShardedModel(shards, {s: trainer.train_shard(s, cs) for s, cs in shards.items()})
    m.model_hash = m.compute_hash()
    rc = ledger.append(Event(ANCHOR_MODEL, {"model_id": model_id, "model_hash": m.model_hash,
                                            "shard_roots": m.roots(), "parent_model_hash": parent}))
    return m, rc


def unlearn(trainer: ShardTrainer, model: ShardedModel, commitment: str, ledger: Ledger,
            model_id: str) -> tuple[ShardedModel, Receipt]:
    """Revocation -> retrain only the affected shard -> anchor new model -> publish receipt."""
    consent_rc = ledger.append(Event(SET_CONSENT, {"commitment": commitment, "state": "revoked"}))
    s = next(k for k, v in model.shards.items() if commitment in v)
    old_root, old_hash = merkle_root(model.shards[s]), model.model_hash
    shards = {k: list(v) for k, v in model.shards.items()}
    shards[s].remove(commitment)
    weights = dict(model.weights)
    weights[s] = trainer.train_shard(s, shards[s])
    new = ShardedModel(shards, weights)
    new.model_hash = new.compute_hash()
    ledger.append(Event(ANCHOR_MODEL, {"model_id": model_id, "model_hash": new.model_hash,
                                       "shard_roots": new.roots(), "parent_model_hash": old_hash}))
    rc = ledger.append(Event(UNLEARNING_RECEIPT, {
        "commitment": commitment, "shard_id": s, "old_shard_root": old_root,
        "new_shard_root": merkle_root(shards[s]), "old_model_hash": old_hash,
        "new_model_hash": new.model_hash, "consent_tx": consent_rc.tx_id}))
    return new, rc
