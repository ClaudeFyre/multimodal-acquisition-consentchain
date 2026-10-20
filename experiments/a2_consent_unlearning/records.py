"""Off-chain sample registry: provenance + license per training sample, and salted commitments.

A "sample" is one patient-level training record of the lung cohort (experiments/lung_missingness/prepared).
The full record and its salt stay off-chain (registry.jsonl / salts.json, both local and deletable);
only `commitment = sha256(salt || canonical(record))` goes to the ledger.
Revocation = record SET_CONSENT revoked on the ledger, then destroy the salt so the commitment can no
longer be linked to the patient.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "experiments" / "lung_missingness" / "prepared"
REGISTRY_YAML = ROOT / "registry" / "datasets.yaml"

# Policy ids used by LICENSE_AUDIT. Extend when non-open datasets enter the pool.
OPEN_LICENSES = {"CC-BY-3.0", "CC-BY-4.0"}


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def dataset_licenses() -> dict[str, str]:
    """dataset_id -> normalized license id, read from registry/datasets.yaml (source of truth)."""
    out, cur = {}, None
    for line in REGISTRY_YAML.read_text("utf-8").splitlines():
        m = re.match(r"\s*-\s*dataset_id:\s*(\S+)", line)
        if m:
            cur = m.group(1)
        m = re.match(r"\s*license:\s*(.+)", line)
        if m and cur:
            txt = m.group(1)
            ids = sorted({f"CC-BY-{v}" for v in re.findall(r"CC BY (\d\.\d)", txt)})
            out[cur] = "+".join(ids) if ids else txt.strip()
    return out


def build_records() -> list[dict]:
    """One provenance record per cohort patient. Contains identifiers -> never leaves this machine."""
    cohort = pd.read_csv(V2 / "cohort.csv")
    summary = json.loads((V2 / "summary.json").read_text("utf-8"))
    src_hash = {Path(k).parts[-2]: v for k, v in summary["source_hashes"].items()}  # project -> GDC json sha256
    lic = dataset_licenses()
    recs = []
    for r in cohort.itertuples():
        ns = "TCGA" if r.cohort == "TCGA" else "CPTAC"
        recs.append({
            "patient_key": f"{ns}:{r.patient_id}",
            "dataset_id": r.project,
            "license_id": lic.get(r.project, "UNKNOWN"),
            "modalities": [m for m, ok in [("clinical", True), ("wsi", r.wsi_present), ("rna", r.rna_present)] if ok],
            "source_sha256": src_hash.get(r.project),
            "source": "GDC",
        })
    return recs


class SampleRegistry:
    """Local registry: record + salt per sample, keyed by commitment."""

    def __init__(self, dirpath: Path):
        self.dir = Path(dirpath)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.salts_path = self.dir / "salts.json"
        self.records_path = self.dir / "registry.jsonl"
        self.salts = json.loads(self.salts_path.read_text("utf-8")) if self.salts_path.exists() else {}

    @staticmethod
    def commit(record: dict, salt: str) -> str:
        return hashlib.sha256(bytes.fromhex(salt) + _canonical(record)).hexdigest()

    def add(self, record: dict) -> str:
        salt = secrets.token_hex(32)
        c = self.commit(record, salt)
        self.salts[c] = salt
        with self.records_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"commitment": c, "record": record}, ensure_ascii=False) + "\n")
        return c

    def save(self) -> None:
        self.salts_path.write_text(json.dumps(self.salts), "utf-8")

    def records(self) -> dict[str, dict]:
        out = {}
        if self.records_path.exists():
            for line in self.records_path.read_text("utf-8").splitlines():
                row = json.loads(line)
                out[row["commitment"]] = row["record"]
        return out

    def opens(self, commitment: str) -> bool:
        """True if the commitment can still be opened (salt present and matches the stored record)."""
        rec, salt = self.records().get(commitment), self.salts.get(commitment)
        return rec is not None and salt is not None and self.commit(rec, salt) == commitment

    def forget(self, commitment: str) -> None:
        """After revocation: drop the salt and the off-chain record (the on-chain commitment becomes unlinkable)."""
        self.salts.pop(commitment, None)
        rows = [l for l in self.records_path.read_text("utf-8").splitlines()
                if json.loads(l)["commitment"] != commitment]
        self.records_path.write_text("\n".join(rows) + ("\n" if rows else ""), "utf-8")
        self.save()


def dataset_commitment(dataset_id: str) -> str:
    """Public, unsalted: datasets are public collections, not personal data."""
    return hashlib.sha256(dataset_id.encode()).hexdigest()
