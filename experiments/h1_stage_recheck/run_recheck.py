"""Post-hoc H1 recheck (ADDENDUM.md): early-fusion vs clinical Cox, with and without pathologic stage.

Reuses experiments/lung_missingness/{prepared, models.Preprocessor, models.fit_cox} and the v2 splits.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold, train_test_split
from sksurv.metrics import concordance_index_ipcw
from sksurv.nonparametric import CensoringDistributionEstimator

HERE = Path(__file__).resolve().parent
V2 = HERE.parent / "lung_missingness"
sys.path.insert(0, str(V2))
sys.path.insert(0, str(HERE.parent / "rna_transport"))
from models import Preprocessor, censor_y, fit_cox  # noqa: E402
import build as h2build  # noqa: E402  (stage rules identical to H2)

TAU, B, SEED = 1095.0, 2000, 20261007
STAGE_CODE = {"I": 1.0, "II": 2.0, "III": 3.0, "IV": 4.0}


def readable_stage(ids) -> np.ndarray:
    raw = {}
    for p in ["tcga-luad", "tcga-lusc", "cptac-luad", "cptac-lscc"]:
        for f in (h2build.GDC / p).glob("*.json"):
            for h in json.loads(f.read_text("utf-8")):
                raw[h["submitter_id"]] = h
    out = []
    for pid in ids:
        st = h2build.stage_group(h2build.pick_diagnosis(raw.get(pid, {})).get("ajcc_pathologic_stage"))
        out.append(STAGE_CODE.get(st, np.nan))
    return np.asarray(out, dtype=np.float32)


def uno(y_train, y_test, risk):
    return float(concordance_index_ipcw(y_train, y_test, risk, tau=TAU)[0])


def v2_style(y_train, y_test, risk):
    """Replicates ipcw_bootstrap.py: drop test patients with time >= tau, then weight by 1/G^2."""
    m = y_test["time"] < TAU
    yt, r = y_test[m], risk[m]
    w = CensoringDistributionEstimator().fit(y_train).predict_ipcw(yt) ** 2
    ii, jj = np.where(yt["event"][:, None] & (yt["time"][:, None] < yt["time"][None, :]))
    d = r[ii] - r[jj]
    c = (d > 1e-8) + 0.5 * (np.abs(d) <= 1e-8)
    return float((w[ii] * c).sum() / w[ii].sum())


def main():
    cohort = pd.read_csv(V2 / "prepared" / "cohort.csv")
    z = np.load(V2 / "prepared" / "features.npz", allow_pickle=False)
    arrays0 = {k: z[k] for k in ["clinical", "wsi", "rna", "ct", "pet"]}
    cols = json.loads((V2 / "prepared" / "summary.json").read_text("utf-8"))["clinical_columns"]
    base_keep = [i for i, c in enumerate(cols)
                 if not c.startswith("diagnoses.ajcc_pathologic") and c != "diagnoses.ajcc_staging_system_edition"]
    stage = readable_stage(cohort.patient_id)
    variants = {
        "A_no_stage": (arrays0["clinical"][:, base_keep], [cols[i] for i in base_keep]),
        "B_stage_group": (np.c_[arrays0["clinical"][:, base_keep], stage], [cols[i] for i in base_keep] + ["stage_group"]),
        "C_stage_enhanced": (arrays0["clinical"], list(cols)),
    }
    y = censor_y(cohort.event.to_numpy(bool), cohort.time_days.to_numpy(float))
    idx = np.arange(len(y))
    strata = cohort.cohort + "_" + cohort.event.astype(str)
    folds = list(StratifiedKFold(5, shuffle=True, random_state=20261004).split(idx, strata))
    rng = np.random.default_rng(SEED)
    counts = []  # shared test resamples per fold, reused across variants/models
    for _, test in folds:
        counts.append(np.stack([np.bincount(rng.integers(0, len(test), len(test)), minlength=len(test)) for _ in range(B)]))

    results, per_fold = {}, []
    for vname, (clin, ccols) in variants.items():
        arrays = dict(arrays0, clinical=clin)
        fold_rows = []
        boot_delta = {"uno": np.zeros(B), "v2": np.zeros(B)}
        for f, (_, test) in enumerate(folds):
            dev = np.setdiff1d(idx, test)
            train, val = train_test_split(dev, test_size=0.2, stratify=strata.iloc[dev], random_state=101 + f)
            prep = Preprocessor().fit(arrays, ccols, train)
            blocks, present = prep.transform(arrays)
            full_x = np.concatenate([*blocks, present[:, 1:].astype(float)], axis=1)
            risks = {}
            for mname, x in [("clinical", blocks[0]), ("early_fusion", full_x)]:
                model, meta = fit_cox(x, y, train, val)
                risks[mname] = model.predict(x[test])
            yt, ytr = y[test], y[train]
            row = {"variant": vname, "fold": f, "n_test": len(test)}
            for mname, r in risks.items():
                row[f"uno_{mname}"] = uno(ytr, yt, r)
                row[f"v2_{mname}"] = v2_style(ytr, yt, r)
            fold_rows.append(row)
            # paired bootstrap on test patients (shared resample across both models)
            for j in range(B):
                ib = np.repeat(np.arange(len(test)), counts[f][j])
                yb = yt[ib]
                try:
                    boot_delta["uno"][j] += (uno(ytr, yb, risks["early_fusion"][ib]) - uno(ytr, yb, risks["clinical"][ib])) / 5
                    boot_delta["v2"][j] += (v2_style(ytr, yb, risks["early_fusion"][ib]) - v2_style(ytr, yb, risks["clinical"][ib])) / 5
                except (ValueError, ZeroDivisionError):
                    boot_delta["uno"][j] = boot_delta["v2"][j] = np.nan
            print(f"{vname} fold {f}: uno clin={row['uno_clinical']:.4f} fus={row['uno_early_fusion']:.4f} | "
                  f"v2 clin={row['v2_clinical']:.4f} fus={row['v2_early_fusion']:.4f}", flush=True)
        df = pd.DataFrame(fold_rows)
        per_fold.append(df)
        res = {}
        for est in ["uno", "v2"]:
            obs = float((df[f"{est}_early_fusion"] - df[f"{est}_clinical"]).mean())
            bd = boot_delta[est][np.isfinite(boot_delta[est])]
            res[est] = {"clinical": float(df[f"{est}_clinical"].mean()), "early_fusion": float(df[f"{est}_early_fusion"].mean()),
                        "delta": obs, "ci": [float(np.quantile(bd, .025)), float(np.quantile(bd, .975))],
                        "p_two_sided": float(min(1, 2 * min((bd <= 0).mean(), (bd >= 0).mean()))), "n_boot": int(len(bd))}
        results[vname] = res
        print(vname, json.dumps(res), flush=True)
    a, b = results["A_no_stage"]["uno"]["delta"], results["B_stage_group"]["uno"]["delta"]
    out = {"run_at_utc": datetime.now(timezone.utc).isoformat(),
           "addendum_sha256": hashlib.sha256((HERE / "ADDENDUM.md").read_bytes()).hexdigest(),
           "stage_group_counts": pd.Series(stage).map({1: "I", 2: "II", 3: "III", 4: "IV"}).value_counts(dropna=False).to_dict(),
           "results": results, "shrinkage_A_to_B_uno": (a - b) / a if a else None}
    (HERE / "results.json").write_text(json.dumps(out, indent=1, default=str), "utf-8")
    pd.concat(per_fold).to_csv(HERE / "per_fold.csv", index=False)


if __name__ == "__main__":
    main()
