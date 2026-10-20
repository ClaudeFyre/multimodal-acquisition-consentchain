"""B1: cost-aware sequential modality acquisition (PROTOCOL_B1.md, frozen 2026-10-08). CPU only.

Ladder: clinicopathologic -> + WSI -> + RNA. Per-patient VoI policy vs random/static, Uno C-index at tau = 3 y.
Reuses experiments/lung_missingness/{prepared, models.Preprocessor, models.fit_cox} and the H1 splits / stage rules.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import KFold, StratifiedKFold, train_test_split
from sklearn.tree import DecisionTreeClassifier, export_text
from sksurv.metrics import brier_score, concordance_index_ipcw, cumulative_dynamic_auc
from sksurv.nonparametric import CensoringDistributionEstimator

HERE = Path(__file__).resolve().parent
V2 = HERE.parent / "lung_missingness"
OUT = HERE / "results"
sys.path.insert(0, str(V2))
sys.path.insert(0, str(HERE.parent / "rna_transport"))
sys.path.insert(0, str(HERE.parent / "h1_stage_recheck"))
from models import Preprocessor, censor_y, fit_cox  # noqa: E402
from run_recheck import readable_stage  # noqa: E402  (H1/H2 stage rules)

TAU, B, B_GRID, SEED, DELTA = 1095.0, 2000, 500, 20261008, 0.01
N_RANDOM = 100
GRID = np.round(np.arange(0, 1.01, 0.1), 1)
Q2_BUDGETS = [0.1, 0.2, 0.3, 0.5]
KAPPAS = [2, 5, 10, 20, 50]


# ---------- Uno C-index as pairwise matrices (validated against sksurv in check_uno) ----------
def uno_parts(y_train, y_test, risk, tol=1e-8):
    """A, D with C = (c A c) / (c D c) for patient multiplicities c (c = 1 -> plain Uno)."""
    t, e = y_test["time"], y_test["event"]
    m = t < TAU
    w = np.zeros(len(t))
    w[m] = CensoringDistributionEstimator().fit(y_train).predict_ipcw(y_test[m]) ** 2
    comp = e[:, None] & ((t[None, :] > t[:, None]) | ((t[None, :] == t[:, None]) & ~e[None, :]))
    np.fill_diagonal(comp, False)
    d = risk[:, None] - risk[None, :]
    score = (d > tol) + 0.5 * (np.abs(d) <= tol)
    D = w[:, None] * comp
    return D * score, D


def c_from(A, D, counts):
    """counts: (n,) or (B, n) multiplicities."""
    c = np.atleast_2d(counts).astype(float)
    return ((c @ A) * c).sum(1) / ((c @ D) * c).sum(1)


def check_uno(y_train, y_test, risk, rng):
    A, D = uno_parts(y_train, y_test, risk)
    ref = concordance_index_ipcw(y_train, y_test, risk, tau=TAU)[0]
    assert abs(c_from(A, D, np.ones(len(risk)))[0] - ref) < 1e-10, "Uno mismatch"
    cnt = np.bincount(rng.integers(0, len(risk), len(risk)), minlength=len(risk))
    ib = np.repeat(np.arange(len(risk)), cnt)
    ref = concordance_index_ipcw(y_train, y_test[ib], risk[ib], tau=TAU)[0]
    assert abs(c_from(A, D, cnt)[0] - ref) < 1e-10, "Uno bootstrap mismatch"


# ---------- models ----------
def risk3y(model, x):
    s = model.predict_survival_function(x.astype(float), return_array=True)
    k = np.searchsorted(model.unique_times_, TAU, side="right") - 1
    return 1.0 - (s[:, k] if k >= 0 else np.ones(len(x)))


def design(blocks, present):
    c, w, r = blocks
    return {"C": c, "CW": np.c_[c, w, present[:, 1]], "CWR": np.c_[c, w, r, present[:, 1:]]}


def fit_three(arrays, cols, y, train, val):
    prep = Preprocessor().fit(arrays, cols, train)
    blocks, present = prep.transform(arrays)
    X = design(blocks, present)
    models = {k: fit_cox(x, y, train, val)[0] for k, x in X.items()}
    return prep, blocks, present, X, models


def crossfit_targets(arrays, cols, y, train, strata, fold):
    """Out-of-fold d_W = |r_CW - r_C|, d_R = |r_CWR - r_CW| on the outer training set (inner 5-fold)."""
    dW, dR = np.full(len(train), np.nan), np.full(len(train), np.nan)
    for k, (itr, iho) in enumerate(KFold(5, shuffle=True, random_state=1000 + fold).split(train)):
        tr_all, ho = train[itr], train[iho]
        tr, va = train_test_split(tr_all, test_size=0.2, stratify=strata.iloc[tr_all], random_state=2000 + 10 * fold + k)
        _, _, _, X, models = fit_three(arrays, cols, y, tr, va)
        r = {m: risk3y(models[m], X[m][ho]) for m in models}
        dW[iho], dR[iho] = np.abs(r["CW"] - r["C"]), np.abs(r["CWR"] - r["CW"])
    return dW, dR


def top_mask(score, frac):
    n = len(score)
    k = int(round(frac * n))
    m = np.zeros(n, bool)
    if k:
        m[np.argsort(-score, kind="stable")[:k]] = True
    return m


def policy_risk(r, sW, sR, bW, bR):
    """Acquire WSI for top-bW by sW; RNA for top-bR (fraction of all) by sR among WSI-acquired."""
    got_w = top_mask(sW, bW)
    sR2 = np.where(got_w, sR, -np.inf)
    got_r = top_mask(sR2, bR) & got_w
    return np.where(got_r, r["CWR"], np.where(got_w, r["CW"], r["C"]))


# ---------- one clinical version ----------
def run_version(vname, arrays, cols, y, folds, strata, cohort, stage, counts):
    idx = np.arange(len(y))
    rng_rand = np.random.default_rng(SEED + 1)
    fold_info, grid_rows, q1_boot, q2_boot, rules, sub_store, sec_rows = [], [], {}, {}, [], [], []
    grid_boot = {}
    for f, (_, test) in enumerate(folds):
        dev = np.setdiff1d(idx, test)
        train, val = train_test_split(dev, test_size=0.2, stratify=strata.iloc[dev], random_state=101 + f)
        prep, blocks, present, X, models = fit_three(arrays, cols, y, train, val)
        r = {m: risk3y(models[m], X[m][test]) for m in models}
        yt, ytr = y[test], y[train]
        if f == 0:
            check_uno(ytr, yt, r["CWR"], np.random.default_rng(0))
        # VoI regressors (targets cross-fitted on the outer training set)
        dW_tr, dR_tr = crossfit_targets(arrays, cols, y, train, strata, f)
        inW, inR = X["C"], np.c_[X["C"], blocks[1], present[:, 1]]
        regW = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200, random_state=0).fit(inW[train], dW_tr)
        regR = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200, random_state=0).fit(inR[train], dR_tr)
        sW, sR = regW.predict(inW[test]), regR.predict(inR[test])
        oW, oR = np.abs(r["CW"] - r["C"]), np.abs(r["CWR"] - r["CW"])
        rand = [(rng_rand.random(len(test)), rng_rand.random(len(test))) for _ in range(N_RANDOM)]
        cnt = counts[f]
        info = {"fold": f, "n_test": int(len(test)), "alpha": {m: models[m].alpha for m in models},
                "spearman_pred_vs_true": {"W": float(pd.Series(sW).corr(pd.Series(oW), method="spearman")),
                                          "R": float(pd.Series(sR).corr(pd.Series(oR), method="spearman"))},
                "train_target_mean": {"W": float(dW_tr.mean()), "R": float(dR_tr.mean())}}
        fold_info.append(info)

        def boot_c(risk, nb=B):
            A, D = uno_parts(ytr, yt, risk)
            return c_from(A, D, np.ones(len(test)))[0], c_from(A, D, cnt[:nb])

        # 2D grid (Q3): VoI, random mean, oracle; Q1/Q2 are the bW = 1 row
        for bW in GRID:
            for bR in GRID[GRID <= bW + 1e-9]:
                key = (float(bW), float(bR))
                nb = B if bW == 1.0 else B_GRID
                c_voi, bt_voi = boot_c(policy_risk(r, sW, sR, bW, bR), nb)
                c_or, _ = boot_c(policy_risk(r, oW, oR, bW, bR), 1)
                rc = [boot_c(policy_risk(r, a, b, bW, bR), nb if (bW == 1.0 and bR in Q2_BUDGETS) else 1) for a, b in rand]
                c_rand = float(np.mean([x[0] for x in rc]))
                grid_rows.append({"version": vname, "fold": f, "bW": key[0], "bR": key[1],
                                  "C_voi": c_voi, "C_random": c_rand, "C_oracle": c_or})
                grid_boot.setdefault(key, np.zeros(nb))
                grid_boot[key][:nb] += bt_voi / len(folds)
                if bW == 1.0 and bR in Q2_BUDGETS:
                    q2_boot.setdefault(bR, np.zeros(B))
                    q2_boot[bR] += (bt_voi - np.mean([x[1] for x in rc], axis=0)) / len(folds)
        # secondary metrics for the bW = 1 row (point estimates)
        for bR in GRID:
            rk = policy_risk(r, sW, sR, 1.0, bR)
            row = {"version": vname, "fold": f, "bR": float(bR)}
            try:
                row["auc_3y"] = float(cumulative_dynamic_auc(ytr, yt, rk, [TAU])[0][0])
                row["brier_3y"] = float(brier_score(ytr, yt, (1 - rk)[:, None], [TAU])[1][0])
            except ValueError as ex:
                row["error"] = str(ex)
            sec_rows.append(row)
        # store what the rule / subgroup steps need
        sub_store.append({"test": test, "train": train, "r": r, "sR_train": regR.predict(inR[train]),
                          "pc1": blocks[1][:, 0], "ytr": ytr, "yt": yt, "cnt": cnt})

    grid = pd.DataFrame(grid_rows)
    gm = grid.groupby(["bW", "bR"])[["C_voi", "C_random", "C_oracle"]].mean().reset_index()
    full_key = (1.0, 1.0)
    # Q1: non-inferiority vs full acquisition
    q1 = []
    for bR in GRID:
        d = grid_boot[(1.0, float(bR))] - grid_boot[full_key]
        obs = float(gm.query("bW == 1.0 and bR == @bR").C_voi.iloc[0] - gm.query("bW == 1.0 and bR == 1.0").C_voi.iloc[0])
        q1.append({"bR": float(bR), "C_voi": float(gm.query("bW == 1.0 and bR == @bR").C_voi.iloc[0]),
                   "delta_vs_full": obs, "ci": [float(np.quantile(d, .025)), float(np.quantile(d, .975))],
                   "noninferior": bool(np.quantile(d, .025) > -DELTA)})
    b_star = next((x["bR"] for x in q1 if x["noninferior"]), None)
    # Q2: VoI vs random, Holm over 4 budgets
    q2 = []
    for bR in Q2_BUDGETS:
        d = q2_boot[bR]
        g = gm.query("bW == 1.0 and bR == @bR")
        q2.append({"bR": bR, "delta_voi_minus_random": float(g.C_voi.iloc[0] - g.C_random.iloc[0]),
                   "ci": [float(np.quantile(d, .025)), float(np.quantile(d, .975))],
                   "p_raw": float(min(1, 2 * min((d <= 0).mean(), (d >= 0).mean())))})
    order = np.argsort([x["p_raw"] for x in q2])
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(q2) - rank) * q2[i]["p_raw"]))
        q2[i]["p_holm"] = running
    # Q3: Pareto fronts per kappa (fractions are cost-agnostic; cost = bW + kappa * bR)
    gm["C_lo"] = [float(np.quantile(grid_boot[(a, b)][:B_GRID], .025)) for a, b in zip(gm.bW, gm.bR)]
    gm["C_hi"] = [float(np.quantile(grid_boot[(a, b)][:B_GRID], .975)) for a, b in zip(gm.bW, gm.bR)]
    fronts = {}
    for k in KAPPAS:
        g = gm.assign(cost=gm.bW + k * gm.bR).sort_values(["cost", "C_voi"], ascending=[True, False])
        best, pts = -np.inf, []
        for _, row in g.iterrows():
            if row.C_voi > best + 1e-12:
                best = row.C_voi
                pts.append({"bW": row.bW, "bR": row.bR, "cost": float(row.cost), "C": float(row.C_voi),
                            "ci": [row.C_lo, row.C_hi]})
        fronts[str(k)] = pts
    # Section 7: decision rule if b* > 0, else prespecified subgroups
    extra = {}
    if b_star is not None and b_star > 0:
        for f, s in enumerate(sub_store):
            tr = s["train"]
            feats = np.c_[stage[tr], (cohort.project.iloc[tr].str.contains("lusc|lscc")).astype(float),
                          arrays["clinical"][tr][:, cols.index("diagnoses.age_bin")] if "diagnoses.age_bin" in cols else np.nan,
                          np.nan_to_num(arrays["clinical"][tr][:, cols.index("exposures.tobacco_smoking_status")], nan=-1),
                          s["pc1"][tr]]
            feats = np.nan_to_num(feats, nan=-1)
            lab = top_mask(s["sR_train"], b_star)
            tree = DecisionTreeClassifier(max_depth=2, min_samples_leaf=30, random_state=0).fit(feats, lab)
            rules.append({"fold": f, "rule": export_text(tree, feature_names=["stage_group", "is_squamous", "age_bin", "smoking_status", "wsi_pc1"])})
        extra["decision_rules"] = rules
    else:
        subs = {"stage_I": lambda t: stage[t] == 1, "stage_II_IV": lambda t: stage[t] >= 2,
                "LUAD": lambda t: cohort.project.iloc[t].str.contains("luad").to_numpy(),
                "LUSC": lambda t: cohort.project.iloc[t].str.contains("lusc|lscc").to_numpy()}
        out = {}
        for name, fn in subs.items():
            obs, bt, n = [], np.zeros(B), 0
            for s in sub_store:
                m = fn(s["test"])
                n += int(m.sum())
                A1, D1 = uno_parts(s["ytr"], s["yt"][m], s["r"]["CWR"][m])
                A0, D0 = uno_parts(s["ytr"], s["yt"][m], s["r"]["CW"][m])
                obs.append(c_from(A1, D1, np.ones(m.sum()))[0] - c_from(A0, D0, np.ones(m.sum()))[0])
                c = s["cnt"][:, m]
                with np.errstate(invalid="ignore", divide="ignore"):
                    bt += (c_from(A1, D1, c) - c_from(A0, D0, c)) / len(sub_store)
            bt = bt[np.isfinite(bt)]
            out[name] = {"n": n, "delta_CWR_minus_CW": float(np.mean(obs)),
                         "ci": [float(np.quantile(bt, .025)), float(np.quantile(bt, .975))], "n_boot": int(len(bt))}
        extra["subgroups_rna_gain"] = out
    sec = pd.DataFrame(sec_rows)
    return {"q1": q1, "b_star": b_star, "q2": q2, "pareto": fronts, "fold_info": fold_info,
            "secondary": sec.groupby("bR")[["auc_3y", "brier_3y"]].mean().reset_index().to_dict("records"),
            **extra}, grid, gm


def main():
    OUT.mkdir(exist_ok=True)
    freeze = json.loads((HERE / "PROTOCOL_B1.freeze.json").read_text("utf-8"))
    sha = hashlib.sha256((HERE / "PROTOCOL_B1.md").read_bytes()).hexdigest()
    assert sha == freeze["protocol_sha256"], "protocol changed after freeze"
    cohort = pd.read_csv(V2 / "prepared" / "cohort.csv")
    z = np.load(V2 / "prepared" / "features.npz", allow_pickle=False)
    arrays0 = {k: z[k] for k in ["clinical", "wsi", "rna", "ct", "pet"]}
    cols = json.loads((V2 / "prepared" / "summary.json").read_text("utf-8"))["clinical_columns"]
    base_keep = [i for i, c in enumerate(cols)
                 if not c.startswith("diagnoses.ajcc_pathologic") and c != "diagnoses.ajcc_staging_system_edition"]
    stage = readable_stage(cohort.patient_id)
    base_cols = [cols[i] for i in base_keep]
    versions = {"B_stage_group": (np.c_[arrays0["clinical"][:, base_keep], stage], base_cols + ["stage_group"]),
                "A_no_stage": (arrays0["clinical"][:, base_keep], base_cols)}
    y = censor_y(cohort.event.to_numpy(bool), cohort.time_days.to_numpy(float))
    strata = cohort.cohort + "_" + cohort.event.astype(str)
    folds = list(StratifiedKFold(5, shuffle=True, random_state=20261004).split(np.arange(len(y)), strata))
    rng = np.random.default_rng(SEED)
    counts = [np.stack([np.bincount(rng.integers(0, len(t), len(t)), minlength=len(t)) for _ in range(B)]) for _, t in folds]
    results = {}
    for vname, (clin, ccols) in versions.items():
        t0 = datetime.now(timezone.utc)
        res, grid, gm = run_version(vname, dict(arrays0, clinical=clin), ccols, y, folds, strata, cohort, stage, counts)
        grid.to_csv(OUT / f"grid_per_fold_{vname}.csv", index=False)
        gm.to_csv(OUT / f"grid_mean_{vname}.csv", index=False)
        results[vname] = res
        print(f"{vname} done in {(datetime.now(timezone.utc) - t0).total_seconds():.0f}s; b* = {res['b_star']}", flush=True)
        print(json.dumps({"q1": res["q1"], "q2": res["q2"]}, indent=1), flush=True)
    out = {"run_at_utc": datetime.now(timezone.utc).isoformat(), "protocol_sha256": sha,
           "B": B, "B_grid": B_GRID, "delta": DELTA, "results": results}
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=str), "utf-8")


if __name__ == "__main__":
    main()
