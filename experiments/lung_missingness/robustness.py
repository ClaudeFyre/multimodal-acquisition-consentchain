"""Predefined exploratory conditional-missingness / consistency ablations.

Reuses the external cohort: these results are hypothesis generation, not confirmation.
"""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sksurv.linear_model import CoxPHSurvivalAnalysis
from threadpoolctl import threadpool_limits

from models import NeuralModel, Preprocessor, TokenCox, censor_y, concordance, cox_loss
from run import metrics, stress_views

HERE = Path(__file__).parent
OUT = HERE / "robustness_results"


def fit(blocks, present, y, train, val, clinical, seed, mode):
    torch.manual_seed(seed)
    model = TokenCox([b.shape[1] for b in blocks])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.01)
    xb = [torch.as_tensor(b[train], dtype=torch.float32) for b in blocks]
    mask = torch.as_tensor(present[train], dtype=torch.bool)
    event = torch.as_tensor(y["event"][train], dtype=torch.bool)
    time = torch.as_tensor(y["time"][train], dtype=torch.float32)
    age = clinical["diagnoses.age_bin"].to_numpy()
    stage = clinical["diagnoses.ajcc_pathologic_stage"].to_numpy()
    thresholds = [float(np.nanmedian(age[train])), float(np.nanmedian(stage[train]))]
    groups = torch.as_tensor(np.c_[np.nan_to_num(stage[train], nan=thresholds[1]) > thresholds[1],
                                  np.nan_to_num(age[train], nan=thresholds[0]) > thresholds[0]])
    best, selected, stale, selected_epoch = -np.inf, None, 0, 0
    wrapper = NeuralModel(model, {})
    for epoch in range(1, 121):
        model.train()
        active = mask.clone()
        if mode == "structured_consistency":
            policy = int(torch.randint(0, 3, ()).item())
            probability = torch.full(groups.shape, 0.3)
            if policy:
                chosen = groups if policy == 1 else ~groups
                probability = torch.where(chosen, 0.6, 0.1)
            active[:, 1:] &= torch.rand(groups.shape) >= probability
        elif mode != "masked":
            active[:, 1:] &= torch.rand(active[:, 1:].shape) > 0.3
        risk = model(xb, active)
        loss = cox_loss(risk, event, time)
        if mode.endswith("consistency"):
            full = model(xb, mask)
            loss = 0.5 * (loss + cox_loss(full, event, time))
            # Cox risks are identifiable only up to an additive constant.
            masked_centered = risk - risk.mean()
            full_centered = (full - full.mean()).detach()
            loss += 0.1 * (masked_centered - full_centered).square().mean()
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 2)
        optimizer.step()
        if epoch % 5 == 0:
            score = concordance(y[val], wrapper.predict([b[val] for b in blocks], present[val]))
            if score > best + 0.0001:
                best, selected, stale, selected_epoch = score, copy.deepcopy(model.state_dict()), 0, epoch
            else:
                stale += 5
            if stale >= 25:
                break
    model.load_state_dict(selected)
    wrapper.meta = {"mode": mode, "epoch": selected_epoch, "val_cindex": best,
                    "age_threshold": thresholds[0], "stage_threshold": thresholds[1], "consistency_weight": 0.1 if mode.endswith("consistency") else 0}
    return wrapper


def main():
    OUT.mkdir(exist_ok=True)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)
    threadpool_limits(limits=4)
    cohort = pd.read_csv(HERE / "prepared/cohort.csv")
    clinical = pd.read_csv(HERE / "prepared/clinical.csv", index_col=0)
    z = np.load(HERE / "prepared/features.npz", allow_pickle=False)
    arrays = {k: z[k] for k in ["clinical", "wsi", "rna"]}
    y = censor_y(cohort.event.to_numpy(bool), cohort.time_days.to_numpy(float))
    splits = pd.read_csv(HERE / "results/splits.csv")
    summary = json.loads((HERE / "prepared/summary.json").read_text())
    positions = {pid: i for i, pid in enumerate(cohort.patient_id)}
    rows, preds, metadata = [], [], []
    for seed in [41, 42, 43]:
        exp = f"tcga_to_cptac_{seed}"
        s = splits[splits.experiment == exp]
        train, val, test = [np.array([positions[p] for p in s.loc[s.role == role, "patient_id"]]) for role in ["train", "validation", "test"]]
        prep = Preprocessor().fit(arrays, summary["clinical_columns"], train)
        blocks, present = prep.transform(arrays)
        for mode in ["masked", "random_dropout", "random_consistency", "structured_consistency"]:
            model = fit(blocks, present, y, train, val, clinical, seed=1000 + seed, mode=mode)
            risk_train = model.predict([b[train] for b in blocks], present[train])
            center, scale = risk_train.mean(), max(risk_train.std(), 1e-6)
            cal = CoxPHSurvivalAnalysis(alpha=10).fit(((risk_train - center) / scale)[:, None], y[train])
            views = list(stress_views([b[test] for b in blocks], present[test], seed=seed + 500))
            age = clinical["diagnoses.age_bin"].to_numpy()[test]
            age = np.nan_to_num(age, nan=model.meta["age_threshold"])
            rng = np.random.default_rng(600 + seed)
            for reverse in [False, True]:
                group = age > model.meta["age_threshold"]
                if reverse:
                    group = ~group
                drop = rng.random(len(test)) < np.where(group, 0.8, 0.1)
                bb, mm = [b[test].copy() for b in blocks], present[test].copy()
                bb[2][drop], mm[drop, 2] = 0, False
                views.append(("rna_missing_age_low" if reverse else "rna_missing_age_high", bb, mm))
            for condition, bb, mm in views:
                risk = model.predict(bb, mm)
                sf = cal.predict_survival_function(((risk - center) / scale)[:, None])
                surv = np.asarray([f(365.) for f in sf])
                rows.append({"experiment": exp, "model": mode, "condition": condition, **metrics(y[train], y[test], risk, surv)})
                preds.extend({"experiment": exp, "model": mode, "condition": condition, "patient_id": cohort.patient_id.iloc[i],
                              "event": bool(y["event"][i]), "time_days": float(y["time"][i]), "risk": float(risk[j])} for j, i in enumerate(test))
            metadata.append({"experiment": exp, **model.meta})
            print(exp, mode, "done", flush=True)
        pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False)
        pd.DataFrame(preds).to_csv(OUT / "predictions.csv", index=False)
        (OUT / "fit_metadata.json").write_text(json.dumps(metadata, indent=2), "utf-8")
    m = pd.DataFrame(rows)
    m.pivot_table(index="model", columns="condition", values="harrell_c").to_csv(OUT / "mean_cindex.csv")
    print(m.pivot_table(index="model", columns="condition", values="harrell_c").round(4).to_string(), flush=True)


if __name__ == "__main__":
    main()
