"""Paired patient bootstrap; repeated external seeds are not independent patients."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sksurv.metrics import concordance_index_censored

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"


def paired_bootstrap(predictions, candidate, reference, condition, external=True, n=1000):
    p = predictions[predictions.condition == condition]
    p = p[p.experiment.str.startswith("tcga_to") if external else p.experiment.str.startswith("internal")]
    data = []
    for experiment, group in p.groupby("experiment"):
        a = group[group.model == candidate].set_index("patient_id").sort_index()
        b = group[group.model == reference].set_index("patient_id").reindex(a.index)
        assert len(a) and b.risk.notna().all()
        data.append((a.event.to_numpy(bool), a.time_days.to_numpy(float), a.risk.to_numpy(float), b.risk.to_numpy(float), a.index.tolist()))
    if external:
        assert all(d[4] == data[0][4] for d in data)
    rng = np.random.default_rng(20261004)
    differences = []
    point = np.mean([concordance_index_censored(e, t, a)[0] - concordance_index_censored(e, t, b)[0] for e, t, a, b, _ in data])
    for i in range(n):
        values = []
        shared = rng.integers(0, len(data[0][0]), len(data[0][0])) if external else None
        for e, t, a, b, _ in data:
            ix = shared if external else rng.integers(0, len(e), len(e))
            values.append(concordance_index_censored(e[ix], t[ix], a[ix])[0] - concordance_index_censored(e[ix], t[ix], b[ix])[0])
        differences.append(np.mean(values))
    lo, hi = np.quantile(differences, [0.025, 0.975])
    return {"evaluation": "external" if external else "internal", "condition": condition,
            "candidate": candidate, "reference": reference, "delta_c": float(point),
            "ci95_low": float(lo), "ci95_high": float(hi), "bootstrap_replicates": n,
            "unique_patients": len(data[0][0]) if external else sum(len(d[0]) for d in data),
            "interpretation": "exploratory paired percentile CI; no multiplicity adjustment, not a retraining bootstrap"}


def main():
    m = pd.read_csv(OUT / "metrics.csv")
    m["evaluation"] = np.where(m.experiment.str.startswith("internal"), "internal", "external")
    mean = m.groupby(["evaluation", "condition", "model"])[["harrell_c", "ipcw_c_3y", "auc_1y", "brier_1y"]].agg(["mean", "std"])
    mean.to_csv(OUT / "aggregate_metrics.csv")
    p = pd.read_csv(OUT / "predictions.csv")
    comparisons = []
    for candidate, reference, condition, external in [
        ("late_fusion", "clinical", "natural", False),
        ("early_fusion", "clinical", "natural", True),
        ("dropout_transformer", "clinical", "natural", True),
        ("dropout_transformer", "rna", "natural", True),
        ("dropout_transformer", "late_fusion", "natural", True),
        ("dropout_transformer", "masked_transformer", "no_rna", True),
        ("dropout_transformer", "masked_transformer", "no_wsi", True),
        ("dropout_transformer", "masked_transformer", "random50", True)]:
        result = paired_bootstrap(p, candidate, reference, condition, external)
        comparisons.append(result)
        print(candidate, reference, condition, round(result["delta_c"], 4), round(result["ci95_low"], 4), round(result["ci95_high"], 4), flush=True)
    pd.DataFrame(comparisons).to_csv(OUT / "paired_bootstrap.csv", index=False)
    (OUT / "paired_bootstrap.json").write_text(json.dumps(comparisons, indent=2), "utf-8")
    # Correlation diagnosis only: availability and outcome mix vary across cohorts.
    c = pd.read_csv(HERE / "prepared/cohort.csv")
    availability = c.groupby("cohort")[["wsi_present", "rna_present", "ct_present", "event"]].mean()
    availability.to_csv(OUT / "cohort_availability.csv")
    split = pd.read_csv(OUT / "splits.csv")
    for name, g in split.groupby("experiment"):
        assert not g.patient_id.duplicated().any(), f"Split leakage in {name}"
    internal = split[(split.role == "test") & split.experiment.str.startswith("internal")]
    assert internal.patient_id.is_unique and len(internal) == len(c)
    print("patient-disjoint splits and one OOF prediction per model/condition/patient verified", flush=True)


if __name__ == "__main__":
    main()
