"""Build auditable OS outcomes and pooled frozen features, without touching source data."""
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = HERE / "prepared"
FEATURES = ROOT / "repos/MMIST-LUNG/features"
PROJECTS = ["tcga-luad", "tcga-lusc", "cptac-luad", "cptac-lscc"]


def finite_number(x):
    try:
        value = float(x)
        return value if np.isfinite(value) and value > 0 else None
    except (ValueError, TypeError):
        return None


def outcome(h):
    """Use explicit GDC status; do not infer censoring from a missing death date."""
    demo = h.get("demographic") or {}
    status = demo.get("vital_status")
    death = finite_number(demo.get("days_to_death"))
    if status == "Dead" and death is not None:
        return True, death, "demographic.days_to_death", None
    if status == "Alive" and death is not None:
        return None, None, None, "alive_with_positive_death_time"
    if status != "Alive":
        return None, None, None, "unknown_status_or_dead_without_valid_death_time"
    candidates = []
    for field in ["days_to_last_follow_up", "days_to_last_known_alive"]:
        value = finite_number(demo.get(field))
        if value is not None:
            candidates.append((value, "demographic." + field))
    for i, d in enumerate(h.get("diagnoses") or []):
        value = finite_number(d.get("days_to_last_follow_up"))
        if value is not None:
            candidates.append((value, f"diagnoses[{i}].days_to_last_follow_up"))
    for i, f in enumerate(h.get("follow_ups") or []):
        value = finite_number(f.get("days_to_follow_up"))
        if value is not None:
            candidates.append((value, f"follow_ups[{i}].days_to_follow_up"))
    if not candidates:
        return None, None, None, "alive_without_positive_followup"
    time, source = max(candidates)
    return False, time, source, None


def patient_id(name):
    stem = Path(name).stem
    if "_" in stem:
        return stem.split("_")[0]
    return "-".join(stem.split("-")[:3 if stem.startswith("TCGA") else 2])


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    demo = pd.read_csv(FEATURES / "demographics.csv").set_index("cases.submitter_id")
    dx = pd.read_csv(FEATURES / "diagnosis.csv").set_index("cases.submitter_id")
    assert demo.index.is_unique and dx.index.is_unique
    raw, origins, hashes = {}, {}, {}
    for project in PROJECTS:
        for p in sorted((ROOT / "data/raw/gdc" / project).glob("*.json")):
            hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
            for h in json.loads(p.read_text("utf-8")):
                pid = h["submitter_id"]
                if pid in raw and raw[pid] != h:
                    raise ValueError(f"Conflicting raw case {pid}")
                raw[pid] = h
                origins[pid] = project
    rows = []
    for pid in sorted(demo.index):
        h = raw.get(pid)
        if h is None:
            event, time, source, error = None, None, None, "no_local_gdc_case"
        else:
            event, time, source, error = outcome(h)
        known_365 = time is not None and (event or time >= 365)
        death_365 = int(bool(event and time <= 365)) if known_365 else None
        author_alive = int(demo.loc[pid, "vital_status_12"])
        rows.append({"patient_id": pid, "cohort": "TCGA" if pid.startswith("TCGA") else "CPTAC",
                     "project": origins.get(pid), "event": event, "time_days": time,
                     "time_source": source, "exclusion": error, "death_by_365": death_365,
                     "author_alive_365": author_alive,
                     "author_label_disagrees": bool(author_alive != 1 - death_365) if known_365 else None})
    all_cases = pd.DataFrame(rows)
    all_cases.to_csv(DATA / "outcome_audit.csv", index=False)
    cohort = all_cases[all_cases.exclusion.isna()].copy().reset_index(drop=True)
    ids = cohort.patient_id.tolist()
    # Explicit allow-list: no survival labels, timestamps, follow-up or treatment variables.
    clinical_cols = ["diagnoses.age_bin", "demographic.gender", "demographic.race",
                     "demographic.ethnicity", "exposures.pack_years_smoked",
                     "exposures.tobacco_smoking_status", "exposures.tobacco_years_smoked"]
    clinical = demo.loc[ids, clinical_cols].join(dx.loc[ids]).replace(-1, np.nan)
    cohort.to_csv(DATA / "cohort.csv", index=False)
    clinical.to_csv(DATA / "clinical.csv", index_label="patient_id")
    arrays = {"patient_ids": np.asarray(ids, dtype=str), "clinical": clinical.to_numpy(dtype=np.float32)}
    feature_audit = {}
    for folder, key in [("WSI", "wsi"), ("CT-SCANS", "ct"), ("PET-SCANS", "pet")]:
        values = {}
        shape_counts = {}
        unmatched = 0
        for p in sorted((FEATURES / folder).glob("*.*")):
            if p.suffix not in {".pt", ".h5"}:
                continue
            pid = patient_id(p.name)
            if pid not in ids:
                unmatched += 1
                continue
            if p.suffix == ".h5":
                with h5py.File(p) as f:
                    value = np.asarray(f["features"], dtype=np.float32)
            else:
                value = torch.load(p, map_location="cpu", weights_only=True)
                if isinstance(value, dict):
                    value = value["features"]
                value = value.detach().cpu().numpy().astype(np.float32)
            shape = str(value.shape)
            shape_counts[shape] = shape_counts.get(shape, 0) + 1
            value = value.squeeze()
            if value.ndim == 2:
                value = value.mean(axis=0)
            if value.ndim != 1 or not np.isfinite(value).all():
                raise ValueError(f"Invalid feature {p}: {value.shape}")
            values.setdefault(pid, []).append(value)
        dimension = len(next(iter(values.values()))[0])
        arr = np.full((len(ids), dimension), np.nan, dtype=np.float32)
        counts = np.zeros(len(ids), dtype=int)
        for i, pid in enumerate(ids):
            if pid in values:
                arr[i] = np.stack(values[pid]).mean(axis=0)
                counts[i] = len(values[pid])
        arrays[key] = arr
        cohort[key + "_present"] = counts > 0
        cohort[key + "_files"] = counts
        feature_audit[key] = {"dimension": dimension, "patients": int((counts > 0).sum()),
                              "files": int(counts.sum()), "out_of_cohort_files": unmatched, "shapes": shape_counts}
        print(key, feature_audit[key], flush=True)
    rna = pd.read_csv(FEATURES / "selected-transcriptomics.csv").set_index("cases.submitter_id")
    assert rna.index.is_unique
    arrays["rna"] = rna.reindex(ids).to_numpy(dtype=np.float32)
    cohort["rna_present"] = np.isfinite(arrays["rna"]).all(axis=1)
    cohort.to_csv(DATA / "cohort.csv", index=False)
    np.savez_compressed(DATA / "features.npz", **arrays)
    summary = {"source_hashes": hashes, "clinical_columns": clinical.columns.tolist(),
               "patients_input": len(all_cases), "eligible": len(cohort), "events": int(cohort.event.sum()),
               "by_cohort": cohort.groupby("cohort").agg(patients=("patient_id", "size"), events=("event", "sum"),
                                  wsi=("wsi_present", "sum"), rna=("rna_present", "sum"), ct=("ct_present", "sum")).to_dict("index"),
               "exclusions": all_cases.exclusion.fillna("eligible").value_counts().to_dict(),
               "known_365": int(cohort.death_by_365.notna().sum()),
               "author_label_disagreements": int(cohort.author_label_disagrees.fillna(False).sum()),
               "feature_audit": feature_audit,
               "limits": ["Retrospective GDC index-time OS, not a validated prospective time origin",
                          "Author frozen imaging features lack verified acquisition-time filters",
                          "RNA file is author preselected/preprocessed; cannot undo whole-cohort preprocessing",
                          "Pathologic staging assumes diagnosis/staging is available at prediction time",
                          "Research use only; this is not an exact reproduction of author folds"]}
    (DATA / "summary.json").write_text(json.dumps(summary, indent=2, default=int), "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"source_hashes", "feature_audit", "clinical_columns"}}, indent=2), flush=True)


if __name__ == "__main__":
    main()
