"""B1 -> ledger: turn the frozen B1 results into compact, verifiable analysis records.

Architecture path (papers/b1_jbhi Fig. 1): evidence repository (frozen protocol, results, report; SHA-256)
-> structured conclusion (finding, evidence references, confidence, model version) -> submission payload
-> Ledger.append(ANALYSIS_RECORD). Default backend is the local hash-chained log; swap in
chain_interface.ledger.BlockchainLedger when the chain experiments are run (【区块链接口位置】).

Reads results only; never modifies the frozen B1 outputs.
Run:  experiments\\.venv\\Scripts\\python.exe -X utf8 experiments\\b1_cost_acquisition\\anchor_results.py [ledger.jsonl]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "chain_interface"))
from ledger import ANALYSIS_RECORD, Event, Ledger, LocalHashChainLedger, BlockchainLedger  # noqa: E402

EVIDENCE = ["PROTOCOL_B1.md", "PROTOCOL_B1.freeze.json", "results/results.json",
            "results/grid_mean_B_stage_group.csv", "results/grid_mean_A_no_stage.csv", "REPORT_B1.md"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def evidence_bundle() -> tuple[str, dict]:
    """Hash = H(sorted (relative path, file sha256)); the manifest itself stays off-chain."""
    manifest = {f"experiments/b1_cost_acquisition/{f}": sha256(HERE / f) for f in EVIDENCE}
    h = hashlib.sha256(json.dumps(sorted(manifest.items())).encode()).hexdigest()
    return h, manifest


def conclusions() -> list[dict]:
    res = json.loads((HERE / "results" / "results.json").read_text("utf-8"))
    out = []
    for v, r in res["results"].items():
        q2_sig = sum(x["p_holm"] < 0.05 for x in r["q2"])
        front = r["pareto"]["10"]
        zero = next(p for p in front if p["bW"] == 0 and p["bR"] == 0)  # cheapest point: always on the front
        best = max(front, key=lambda p: p["C"])
        out.append({"record_id": f"B1/{v}/policy",
                    "conclusion": (f"{v}: best frontier gain over zero-cost policy dC={best['C'] - zero['C']:+.3f} "
                                   f"at bW={best['bW']}, bR={best['bR']} (zero-cost 95% CI {zero['ci'][0]:.3f}-{zero['ci'][1]:.3f}); "
                                   f"VoI>random significant budgets (Holm)={q2_sig}/4; "
                                   f"prespecified b_R*={r['b_star']} (interval-width driven)"),
                    "confidence": "paired bootstrap, 2,000 replicates per fold, 5-fold CV"})
    return out


def anchor(ledger: Ledger) -> list[dict]:
    ev_hash, _ = evidence_bundle()
    freeze = json.loads((HERE / "PROTOCOL_B1.freeze.json").read_text("utf-8"))
    run_at = json.loads((HERE / "results" / "results.json").read_text("utf-8"))["run_at_utc"]
    receipts = []
    for c in conclusions():
        rc = ledger.append(Event(ANALYSIS_RECORD, {
            **c, "evidence_hash": ev_hash,
            "evidence_uri": "repo://experiments/b1_cost_acquisition/results/results.json",
            "model_version": f"protocol:{freeze['protocol_sha256'][:12]}|run:{run_at}"}, org="b1-analysis"))
        receipts.append({"record_id": c["record_id"], "tx_id": rc.tx_id, "index": rc.index,
                         "status": rc.status, "latency_s": rc.latency_s})
    return receipts


def verify_against_evidence(ledger: Ledger) -> bool:
    """Auditor step: recompute the evidence hash from the files and compare with every anchored record."""
    h, _ = evidence_bundle()
    return all(ev.payload["evidence_hash"] == h for _, ev in ledger.events(ANALYSIS_RECORD))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=HERE / "anchored" / "b1_ledger.jsonl")
    parser.add_argument("--backend", choices=["local", "evm"], default="local")
    parser.add_argument("--rpc-url")
    parser.add_argument("--contract")
    parser.add_argument("--chain-id", type=int, default=11155111)
    parser.add_argument("--deployment-block", type=int)
    parser.add_argument("--sender")
    args = parser.parse_args()
    led = (LocalHashChainLedger(args.path, authorized_orgs={"b1-analysis"}) if args.backend == "local"
           else BlockchainLedger(rpc_url=args.rpc_url, contract_address=args.contract,
                                 chain_id=args.chain_id, deployment_block=args.deployment_block,
                                 sender=args.sender, authorized_orgs={"b1-analysis"}))
    print(json.dumps(anchor(led), indent=1))
    print("chain valid:", led.verify(), "| evidence matches:", verify_against_evidence(led))
    if args.backend == "evm":
        print("identical records reused without new transactions:", led.reused_receipts)
