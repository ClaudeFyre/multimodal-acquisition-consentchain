"""Interface smoke test for A2 (no real model, no blockchain): registry -> ledger -> shards -> revoke -> receipt.

Uses a dummy trainer whose "weights" are a hash of shard membership, so it checks the plumbing only.
Run:  experiments\\.venv\\Scripts\\python.exe -X utf8 experiments\\a2_consent_unlearning\\smoke_test.py [outdir]
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chain_interface"))  # shared ledger interface
from ledger import LICENSE_AUDIT, REGISTER_SAMPLE, Event, LocalHashChainLedger  # noqa: E402
from records import OPEN_LICENSES, SampleRegistry, build_records, dataset_commitment  # noqa: E402
from sisa import merkle_proof, merkle_root, merkle_verify, shard_of, train_all, unlearn  # noqa: E402

N_SHARDS = 8


class DummyTrainer:
    def train_shard(self, shard_id, commitments):
        return hashlib.sha256(("|".join(sorted(commitments)) + f"#{shard_id}").encode()).digest()

    def evaluate(self, shard_weights):
        return {}


def main(out: Path):
    reg, led = SampleRegistry(out / "registry"), LocalHashChainLedger(out / "ledger.jsonl")
    recs = build_records()
    commits = []
    for r in recs:
        c = reg.add(r)
        commits.append(c)
        led.append(Event(REGISTER_SAMPLE, {"commitment": c, "license_id": r["license_id"],
                                           "dataset_commitment": dataset_commitment(r["dataset_id"]),
                                           "shard_id": shard_of(c, N_SHARDS)}))
    reg.save()
    bad = [r for r in recs if not set(r["license_id"].split("+")) <= OPEN_LICENSES]
    led.append(Event(LICENSE_AUDIT, {"model_id": "smoke", "policy": "open-CC-BY", "n_samples": len(recs),
                                     "violations": len(bad)}))
    trainer = DummyTrainer()
    model, _ = train_all(trainer, commits, N_SHARDS, led, "smoke")
    target = commits[0]
    s = shard_of(target, N_SHARDS)
    old_root = merkle_root(model.shards[s])
    proof = merkle_proof(model.shards[s], target)
    new, _ = unlearn(trainer, model, target, led, "smoke")
    reg.forget(target)

    checks = {
        "n_samples": len(recs) == 1313,
        "license_violations_zero": not bad,
        "ledger_chain_valid": led.verify(),
        "consent_revoked": led.consent_state(target) == "revoked",
        "member_of_old_root": merkle_verify(target, proof, old_root),
        "not_in_new_shard": target not in new.shards[s],
        "proof_fails_on_new_root": not merkle_verify(target, proof, merkle_root(new.shards[s])),
        "only_one_shard_retrained": sum(new.weights[k] != model.weights[k] for k in new.weights) == 1,
        "salt_destroyed": not reg.opens(target),
        "others_still_open": reg.opens(commits[1]),
    }
    try:
        led.append(Event(REGISTER_SAMPLE, {"commitment": "x", "license_id": "x", "dataset_commitment": "x",
                                           "shard_id": 0, "patient_key": "TCGA:leak"}))
        checks["rejects_personal_fields"] = False
    except ValueError:
        checks["rejects_personal_fields"] = True
    lines = (out / "ledger.jsonl").read_text("utf-8").splitlines()
    lines[5] = lines[5].replace('"granted"', '"revoked"').replace('"shard_id": ', '"shard_id": 9')
    (out / "ledger_tampered.jsonl").write_text("\n".join(lines) + "\n", "utf-8")
    checks["tamper_detected"] = not LocalHashChainLedger(out / "ledger_tampered.jsonl").verify()
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"events: {sum(1 for _ in led.events())}, out: {out}")
    return all(checks.values())


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="a2_smoke_"))
    sys.exit(0 if main(out) else 1)
