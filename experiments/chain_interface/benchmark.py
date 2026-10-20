"""Performance-monitoring harness (architecture "Performance monitoring"): gas, TPS, latency per backend.

Replays a fixed workload of ANALYSIS_RECORD events against any `Ledger` inside a fixed measurement window and
summarizes the receipts. For LocalHashChainLedger gas is undefined (None); the blockchain backend fills it.

Run (local baseline only on this machine):
  experiments\\.venv\\Scripts\\python.exe -X utf8 experiments\\chain_interface\\benchmark.py [n_events] [outdir]
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger import ANALYSIS_RECORD, Event, Ledger, LocalHashChainLedger  # noqa: E402


def workload(n: int):
    for i in range(n):
        h = hashlib.sha256(f"evidence-{i}".encode()).hexdigest()
        yield Event(ANALYSIS_RECORD, {"record_id": f"bench/{i}", "conclusion": "benchmark record",
                                      "evidence_hash": h, "evidence_uri": f"repo://bench/{i}",
                                      "model_version": "bench", "confidence": "n/a"}, org="bench")


def run(ledger: Ledger, n: int = 1000, window_s: float = 60.0) -> dict:
    receipts, failures, t0 = [], 0, time.time()
    for ev in workload(n):
        if time.time() - t0 > window_s:
            break
        try:
            receipts.append(ledger.append(ev))
        except Exception:  # noqa: BLE001  (a rejected tx counts against the success rate)
            failures += 1
    elapsed = time.time() - t0
    lat = sorted(r.latency_s for r in receipts)
    gas = [r.gas_used for r in receipts if r.gas_used is not None]
    return {
        "backend": type(ledger).__name__, "submitted": len(receipts) + failures, "confirmed": len(receipts),
        "success_rate": len(receipts) / max(1, len(receipts) + failures),
        "tps": len(receipts) / elapsed if elapsed else None,
        "latency_p50_s": lat[len(lat) // 2] if lat else None,
        "latency_p95_s": lat[int(0.95 * (len(lat) - 1))] if lat else None,
        "gas_mean": statistics.mean(gas) if gas else None,
        "window_s": window_s, "elapsed_s": elapsed, "chain_valid": ledger.verify(),
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.mkdtemp(prefix="ledger_bench_"))
    res = run(LocalHashChainLedger(out / "bench_ledger.jsonl", authorized_orgs={"bench"}), n)
    (out / "benchmark.json").write_text(json.dumps(res, indent=1), "utf-8")
    print(json.dumps(res, indent=1))
