"""H2 analysis exactly per PROTOCOL_H2.md §4–§7. Reads built/, writes results/.

One frozen model per configuration is fitted on the full development cohort and applied
unchanged to every external cohort. Nothing here reads external outcomes before the
models are fitted, and nothing fitted on external data feeds back into a model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sksurv.linear_model import CoxPHSurvivalAnalysis
from sksurv.metrics import concordance_index_censored, concordance_index_ipcw, cumulative_dynamic_auc
from sksurv.nonparametric import CensoringDistributionEstimator, kaplan_meier_estimator

HERE = Path(__file__).resolve().parent
BUILT, RES = HERE / "built", HERE / "results"
PRIMARY = ["GSE72094", "GSE68465", "GSE31210", "GSE50081", "GSE37745", "GSE30219", "GSE42127"]
TAU, N_BOOT, ALPHAS = 1095.0, 2000, [1.0, 10.0, 100.0]
SEED_VAL, SEED_BOOT = 20261006, 20261006


def y_of(df):
    y = np.empty(len(df), dtype=[("event", bool), ("time", float)])
    y["event"], y["time"] = df.event.astype(bool).values, df.time_days.astype(float).values
    return y


# ----------------------------------------------------------------------------- RNA normalisation (§4.5–4.6)

def rank01(e: pd.DataFrame) -> pd.DataFrame:
    """Within-sample average-rank scaled to [0, 1]; e is genes x samples."""
    r = e.rank(axis=0, method="average")
    return (r - 1) / (len(e) - 1)


def quantile_to_ref(e: pd.DataFrame, ref_sorted: np.ndarray) -> pd.DataFrame:
    r = e.rank(axis=0, method="average").values
    grid = np.linspace(0, 1, len(ref_sorted))
    return pd.DataFrame(np.interp((r - 1) / (len(e) - 1), grid, ref_sorted), index=e.index, columns=e.columns)


# ----------------------------------------------------------------------------- models (§5)

class Model:
    def __init__(self, with_rna: bool, clinical_vars: list[str], n_pc: int = 16):
        self.with_rna, self.vars, self.n_pc = with_rna, clinical_vars, n_pc

    def _x(self, clin: pd.DataFrame, rna: np.ndarray | None, fit: bool):
        if fit:
            self.enc = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                                           self.vars)]).fit(clin[self.vars])
        x = self.enc.transform(clin[self.vars])
        if self.with_rna:
            if fit:
                self.genes = np.argsort(rna.var(axis=0))[-256:]
                self.scale = StandardScaler().fit(rna[:, self.genes])
                self.pca = PCA(n_components=self.n_pc, svd_solver="full").fit(self.scale.transform(rna[:, self.genes]))
            x = np.hstack([x, self.pca.transform(self.scale.transform(rna[:, self.genes]))])
        return x.astype(float)

    def fit(self, clin, rna, y, alpha):
        self.alpha = alpha
        self.cox = CoxPHSurvivalAnalysis(alpha=alpha, ties="breslow", n_iter=150).fit(self._x(clin, rna, True), y)
        return self

    def risk(self, clin, rna):
        return self.cox.predict(self._x(clin, rna, False))

    def surv_at(self, clin, rna, t):
        return np.array([f(t) for f in self.cox.predict_survival_function(self._x(clin, rna, False))])


def select_alpha(with_rna, vars_, clin, rna, y, n_pc):
    strata = clin.source.astype(str) + "_" + clin.event.astype(str)
    tr, va = train_test_split(np.arange(len(clin)), test_size=0.2, random_state=SEED_VAL, stratify=strata)
    best = None
    for a in ALPHAS:
        m = Model(with_rna, vars_, n_pc).fit(clin.iloc[tr], rna[tr] if rna is not None else None, y[tr], a)
        r = m.risk(clin.iloc[va], rna[va] if rna is not None else None)
        c = concordance_index_censored(y[va]["event"], y[va]["time"], r)[0]
        if best is None or c > best[0]:
            best = (c, a)
    return best[1]


# ----------------------------------------------------------------------------- metrics (§6)

def tau_for(y) -> float:
    """min(1095, largest time at which the target cohort's censoring KM is still > 0)."""
    cens = CensoringDistributionEstimator().fit(y)
    t = np.sort(np.unique(y["time"]))
    g = cens.predict_proba(t)
    ok = t[g > 0]
    return float(min(TAU, ok.max() - 1e-6)) if len(ok) else TAU


def ipcw_c(y, risk, tau):
    return float(concordance_index_ipcw(y, y, risk, tau=tau)[0])


def boot_delta(y, r_base, r_new, rng):
    n, tau = len(y), tau_for(y)
    out = []
    for _ in range(N_BOOT):
        i = rng.integers(0, n, n)
        yb = y[i]
        if yb["event"].sum() < 2:
            continue
        try:
            tb = tau_for(yb)
            out.append(ipcw_c(yb, r_new[i], tb) - ipcw_c(yb, r_base[i], tb))
        except ValueError:
            continue
    out = np.array(out)
    return {"delta": ipcw_c(y, r_new, tau) - ipcw_c(y, r_base, tau), "ci": [float(np.percentile(out, 2.5)),
            float(np.percentile(out, 97.5))], "se": float(out.std(ddof=1)), "n_boot_ok": int(len(out)), "tau": tau}


def calib(y, risk, surv3):
    lp = (risk - risk.mean()) / risk.std()
    slope = CoxPHSurvivalAnalysis(alpha=1e-6).fit(lp[:, None], y).coef_[0] / risk.std()
    t, s = kaplan_meier_estimator(y["event"], y["time"])
    km3 = float(s[t <= TAU][-1]) if (t <= TAU).any() else 1.0
    return {"calibration_slope": float(slope), "pred_surv_3y_mean": float(np.mean(surv3)), "km_surv_3y": km3}


def td_auc(y, risk, tau):
    times = [t for t in (365.25, 730.5, 1095.0) if t < tau and t > y["time"].min()]
    if not times:
        return {}
    auc, _ = cumulative_dynamic_auc(y, y, risk, times)
    return {f"auc_{int(t)}d": float(a) for t, a in zip(times, auc)}


def dersimonian_laird(d, se):
    d, w = np.asarray(d), 1 / np.asarray(se) ** 2
    fixed = (w * d).sum() / w.sum()
    q = (w * (d - fixed) ** 2).sum()
    df = len(d) - 1
    tau2 = max(0.0, (q - df) / (w.sum() - (w ** 2).sum() / w.sum())) if df > 0 else 0.0
    ws = 1 / (np.asarray(se) ** 2 + tau2)
    est = (ws * d).sum() / ws.sum()
    sei = np.sqrt(1 / ws.sum())
    i2 = max(0.0, (q - df) / q) if q > 0 else 0.0
    return {"pooled_delta": float(est), "ci": [float(est - 1.96 * sei), float(est + 1.96 * sei)],
            "tau2": float(tau2), "I2": float(i2), "Q": float(q), "k": len(d)}


# ----------------------------------------------------------------------------- data assembly

def load():
    dev_clin = pd.read_parquet(BUILT / "dev_clin.parquet")
    dev_expr = pd.read_parquet(BUILT / "dev_expr.parquet")
    ext = {g: (pd.read_parquet(BUILT / f"{g}_clin.parquet"), pd.read_parquet(BUILT / f"{g}_expr.parquet"))
           for g in PRIMARY}
    common = set(dev_expr.index)
    for _, e in ext.values():
        common &= set(e.index)
    common = sorted(common)
    return dev_clin, dev_expr, ext, common


def run_config(name, cfg, dev_clin, dev_expr, ext, common, mmist=None):
    vars_ = ["age_bin", "sex", "histology"] + (["stage"] if cfg.get("stage", True) else [])
    keep_dev = dev_clin.stage.notna() if cfg.get("stage", True) or cfg.get("stage_I_III") else pd.Series(True, index=dev_clin.index)
    if cfg.get("stage_I_III"):
        keep_dev &= dev_clin.stage.isin(["I", "II", "III"])
    if cfg.get("adeno_only"):
        keep_dev &= dev_clin.histology.eq("adeno")
    dc = dev_clin[keep_dev].reset_index(drop=True)
    if cfg.get("rna_source") == "mmist":
        dc = dc[dc.patient_id.isin(mmist.index)].reset_index(drop=True)
        genes = [g for g in common if g in mmist.columns]
        de = mmist.loc[dc.patient_id, genes].T
    else:
        genes = common
        de = dev_expr.loc[genes, dc.patient_id]
    norm = cfg.get("norm", "rank")
    dev_r = rank01(de)
    ref = np.sort(dev_r.values.mean(axis=1)) if norm == "quantile" else None
    if norm == "quantile":
        dev_r = quantile_to_ref(de, ref)
    rna_dev = dev_r.T.values
    y = y_of(dc)
    n_pc = cfg.get("n_pc", 16)
    a_base = select_alpha(False, vars_, dc, None, y, n_pc)
    a_new = select_alpha(True, vars_, dc, rna_dev, y, n_pc)
    base = Model(False, vars_, n_pc).fit(dc, None, y, a_base)
    new = Model(True, vars_, n_pc).fit(dc, rna_dev, y, a_new)
    out = {"config": name, "clinical_vars": vars_, "n_dev": len(dc), "events_dev": int(y["event"].sum()),
           "n_genes": len(genes), "alpha_clinical": a_base, "alpha_rna": a_new, "cohorts": {}}
    rng = np.random.default_rng(SEED_BOOT)
    for g in PRIMARY:
        c, e = ext[g]
        keep = c.stage.notna() if cfg.get("stage", True) or cfg.get("stage_I_III") else pd.Series(True, index=c.index)
        if cfg.get("stage_I_III"):
            keep &= c.stage.isin(["I", "II", "III"])
        if cfg.get("adeno_only"):
            keep &= c.histology.eq("adeno")
        c = c[keep].reset_index(drop=True)
        if len(c) < 20 or c.event.sum() < 5:
            out["cohorts"][g] = {"n": len(c), "skipped": "too few samples/events"}
            continue
        ee = e.loc[genes, c["sample"]]
        er = (quantile_to_ref(ee, ref) if norm == "quantile" else rank01(ee)).T.values
        yt = y_of(c)
        rb, rn = base.risk(c, None), new.risk(c, er)
        tau = tau_for(yt)
        res = {"n": len(c), "events": int(yt["event"].sum()), "tau": tau,
               "harrell_clinical": float(concordance_index_censored(yt["event"], yt["time"], rb)[0]),
               "harrell_rna": float(concordance_index_censored(yt["event"], yt["time"], rn)[0]),
               "ipcw_clinical": ipcw_c(yt, rb, tau), "ipcw_rna": ipcw_c(yt, rn, tau)}
        res["delta"] = boot_delta(yt, rb, rn, rng)
        res["calib_clinical"] = calib(yt, rb, base.surv_at(c, None, TAU))
        res["calib_rna"] = calib(yt, rn, new.surv_at(c, er, TAU))
        res["tdauc_clinical"], res["tdauc_rna"] = td_auc(yt, rb, tau), td_auc(yt, rn, tau)
        out["cohorts"][g] = res
        print(f"  [{name}] {g}: n={res['n']} ev={res['events']} C_clin={res['ipcw_clinical']:.3f} "
              f"C_rna={res['ipcw_rna']:.3f} dC={res['delta']['delta']:+.3f} {np.round(res['delta']['ci'], 3)}", flush=True)
    ok = [(v["delta"]["delta"], v["delta"]["se"]) for v in out["cohorts"].values() if "delta" in v]
    out["pooled"] = dersimonian_laird(*zip(*ok)) if len(ok) >= 2 else None
    return out


CONFIGS = {  # §6 primary + §7 sensitivity analyses
    "primary": {},
    "s1_no_stage": {"stage": False},
    "s2_adeno_only": {"adeno_only": True},
    "s3_stage_I_III": {"stage_I_III": True},
    "s4_mmist_rna": {"rna_source": "mmist"},
    "s5_pca32": {"n_pc": 32},
    "s6_quantile_norm": {"norm": "quantile"},
}

if __name__ == "__main__":
    RES.mkdir(exist_ok=True)
    which = sys.argv[1:] or list(CONFIGS)
    dev_clin, dev_expr, ext, common = load()
    print(f"common genes across dev + {len(PRIMARY)} platforms: {len(common)}", flush=True)
    mmist = None
    if "s4_mmist_rna" in which:
        m = pd.read_csv(HERE.parent.parent / "repos/MMIST-LUNG/features/selected-transcriptomics.csv").set_index("cases.submitter_id")
        gm = pd.read_csv(BUILT / "dev_gene_map.csv")
        ens2sym = gm.drop_duplicates("ensembl").set_index("ensembl")["symbol"]  # PAR_Y duplicates -> first
        sym = pd.Series([ens2sym.get(c.split(".")[0]) for c in m.columns])
        keep = (sym.notna() & ~sym.duplicated()).values  # unmapped IDs dropped; first of duplicate symbols kept
        mmist = m.iloc[:, keep]
        mmist.columns = sym[keep].values
    for name in which:
        print(f"== {name}", flush=True)
        r = run_config(name, CONFIGS[name], dev_clin, dev_expr, ext, common, mmist)
        (RES / f"{name}.json").write_text(json.dumps(r, indent=1), "utf-8")
        if r["pooled"]:
            p = r["pooled"]
            print(f"  POOLED dC={p['pooled_delta']:+.4f} 95%CI [{p['ci'][0]:+.4f}, {p['ci'][1]:+.4f}] I2={p['I2']:.2f} k={p['k']}", flush=True)
