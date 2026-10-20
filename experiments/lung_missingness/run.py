"""Patient-disjoint internal and cohort-held-out exploratory survival experiments."""
import argparse
import hashlib
import json
import platform
import pickle
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import sksurv
import torch
from sklearn.model_selection import StratifiedKFold, train_test_split
from sksurv.linear_model import CoxPHSurvivalAnalysis
from sksurv.metrics import brier_score, concordance_index_ipcw, cumulative_dynamic_auc
from threadpoolctl import threadpool_limits

from models import Preprocessor, censor_y, concordance, fit_cox, fit_neural

HERE = Path(__file__).resolve().parent
DATA = HERE / "prepared"
OUT = HERE / "results"


def metric_y(y, max_time):
    yy = y.copy()
    yy["event"] = y["event"] & (y["time"] <= max_time)
    yy["time"] = np.minimum(y["time"], max_time)
    return yy


def metrics(y_train, y_test, risk, survival365):
    out = {"n": len(y_test), "events": int(y_test["event"].sum()), "harrell_c": concordance(y_test, risk)}
    for key, fn in [
        ("ipcw_c_3y", lambda: concordance_index_ipcw(y_train, metric_y(y_test, 1096), risk, tau=1095)[0]),
        ("auc_1y", lambda: cumulative_dynamic_auc(y_train, metric_y(y_test, 366), risk, np.array([365.0]))[0][0]),
        ("brier_1y", lambda: brier_score(y_train, metric_y(y_test, 366), survival365[:, None], np.array([365.0]))[1][0])]:
        try:
            out[key] = float(fn())
        except ValueError as e:
            out[key] = None
            out[key + "_error"] = str(e)
    return out


def stress_views(blocks, present, seed):
    rng = np.random.default_rng(seed)
    yield "natural", blocks, present
    for name, key in [("no_rna", 2), ("no_wsi", 1)]:
        bb = [b.copy() for b in blocks]
        mm = present.copy()
        bb[key][:] = 0
        mm[:, key] = False
        yield name, bb, mm
    bb = [b.copy() for b in blocks]; mm = present.copy(); mm[:, 1:] = False
    bb[1][:] = 0; bb[2][:] = 0
    yield "clinical_only", bb, mm
    for rate in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9]:
        bb = [b.copy() for b in blocks]; mm = present.copy()
        for key in [1, 2]:
            drop = (rng.random(len(mm)) < rate) & mm[:, key]
            bb[key][drop] = 0; mm[drop, key] = False
        yield f"random_drop_{rate:.1f}", bb, mm
    bb = [b.copy() for b in blocks]
    # Permute only among observed patients: availability remains unchanged.
    for key in [1, 2]:
        obs = np.where(present[:, key])[0]
        bb[key][obs] = bb[key][rng.permutation(obs)]
    yield "content_permuted", bb, present


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--device", choices=["cuda", "cpu", "auto"], default="cuda")
    parser.add_argument("--seed", type=int, default=20261004)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--fold", type=int)
    parser.add_argument("--fold-seed-index", type=int)
    parser.add_argument("--internal-only", action="store_true")
    parser.add_argument("--training-seed", type=int)
    args = parser.parse_args()
    global OUT
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else "cpu" if args.device == "auto" else args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable; refusing CPU fallback")
    if device.type == "cuda" and torch.cuda.get_device_capability(0) < (6, 0):
        raise RuntimeError("CUDA device lacks required float32 kernel capability")
    out = args.output_dir or (HERE / "runs" / f"run_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S_%f')}_{args.seed}")
    out.mkdir(parents=True, exist_ok=args.resume)
    status_file = out / "status.json"
    status_file.write_text(json.dumps({"status": "running", "started": pd.Timestamp.now().isoformat(),
                                      "device": str(device)}, indent=2), "utf-8")
    OUT = out
    try:
        _execute(args, device, out, status_file)
    except Exception as exc:
        (out / "failure.log").write_text(traceback.format_exc(), "utf-8")
        status_file.write_text(json.dumps({"status": "failed", "error": repr(exc), "failed": pd.Timestamp.now().isoformat()}, indent=2), "utf-8")
        raise


def _execute(args, device, out, status_file):
    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)
    threadpool_limits(limits=4)
    cohort = pd.read_csv(DATA / "cohort.csv")
    z = np.load(DATA / "features.npz", allow_pickle=False)
    arrays = {k: z[k] for k in ["clinical", "wsi", "rna", "ct", "pet"]}
    assert np.array_equal(z["patient_ids"], cohort.patient_id.to_numpy())
    summary = json.loads((DATA / "summary.json").read_text("utf-8"))
    # Diagnosis-time candidate set excludes pathologic stage, which may be postoperative.
    clinical_columns = summary["clinical_columns"]
    baseline_keep = [i for i, col in enumerate(clinical_columns) if not col.startswith("diagnoses.ajcc_pathologic") and col != "diagnoses.ajcc_staging_system_edition"]
    arrays["clinical"] = arrays["clinical"][:, baseline_keep]
    baseline_columns = [clinical_columns[i] for i in baseline_keep]
    y = censor_y(cohort.event.to_numpy(dtype=bool), cohort.time_days.to_numpy(dtype=float))
    idx = np.arange(len(y))
    strata = cohort.cohort + "_" + cohort.event.astype(str)
    splitter = StratifiedKFold(args.folds, shuffle=True, random_state=20261004)
    experiments = []
    for fold, (_, test) in enumerate(splitter.split(idx, strata)):
        dev = np.setdiff1d(idx, test)
        train, val = train_test_split(dev, test_size=0.2, stratify=strata.iloc[dev], random_state=101 + fold)
        for model_seed in [41, 42, 43]:
            experiments.append((f"internal_{fold}_seed{model_seed}", fold, model_seed, train, val, test))
    tcga = idx[cohort.cohort == "TCGA"]
    cptac = idx[cohort.cohort == "CPTAC"]
    for seed in [41, 42, 43]:
        train, val = train_test_split(tcga, test_size=0.2, stratify=y["event"][tcga], random_state=seed)
        experiments.append((f"tcga_to_cptac_{seed}", -1, seed, train, val, cptac))
    if args.internal_only:
        experiments = [e for e in experiments if e[1] >= 0]
    records = pd.read_csv(out / "metrics.csv").to_dict("records") if args.resume and (out / "metrics.csv").exists() else []
    predictions = pd.read_csv(out / "predictions.csv").to_dict("records") if args.resume and (out / "predictions.csv").exists() else []
    splits = pd.read_csv(out / "splits.csv").to_dict("records") if args.resume and (out / "splits.csv").exists() else []
    fit_records = json.loads((out / "fit_metadata.json").read_text("utf-8")) if args.resume and (out / "fit_metadata.json").exists() else []
    protocol = json.loads(args.protocol.read_text("utf-8")) if args.protocol else {}
    selected_experiments = list(enumerate(experiments))
    if args.fold is not None:
        selected_experiments = [(i, e) for i, e in selected_experiments if e[1][1] == args.fold]
    if args.fold_seed_index is not None:
        selected_experiments = [(i, e) for i, e in selected_experiments if e[1][1] == args.fold_seed_index]
    if args.fold is None and args.training_seed is not None:
        selected_experiments = [(i, e) for i, e in selected_experiments if e[0] == f"tcga_to_cptac_{args.training_seed}"]
    if not selected_experiments:
        raise ValueError("Selection matched no experiments; check --fold / --training-seed")
    for number, (name, fold_id, model_seed, train, val, test) in selected_experiments:
        if args.resume and any(row.get("experiment") == name for row in records):
            print(name, "already complete; skipping", flush=True)
            continue
        assert not (set(train) & set(val) or set(train) & set(test) or set(val) & set(test))
        splits.extend({"experiment": name, "role": role, "patient_id": cohort.patient_id.iloc[i]} for role, inds in [("train", train), ("validation", val), ("test", test)] for i in inds)
        prep = Preprocessor().fit(arrays, baseline_columns, train)
        with open(out / f"{name}_preprocessor.pkl", "wb") as f:
            pickle.dump(prep, f, protocol=pickle.HIGHEST_PROTOCOL)
        blocks, present = prep.transform(arrays)
        full_x = np.concatenate([*blocks, present[:, 1:].astype(float)], axis=1)
        missing = np.concatenate([np.isnan(arrays["clinical"]).astype(float),
                                  (~np.isfinite(arrays["wsi"]).all(axis=1))[:, None],
                                  (~np.isfinite(arrays["rna"]).all(axis=1))[:, None],
                                  (~np.isfinite(arrays["ct"]).all(axis=1))[:, None]], axis=1)
        base = {}
        for model_name, x in [("clinical", blocks[0]), ("wsi", blocks[1]), ("rna", blocks[2]),
                              ("mask_only", missing), ("clinical_mask", np.c_[blocks[0], missing]), ("early_fusion", full_x)]:
            fit_train = train
            fit_val = val
            if model_name in {"wsi", "rna"}:
                key = 1 if model_name == "wsi" else 2
                fit_train = train[present[train, key]]
                fit_val = val[present[val, key]]
            model, meta = fit_cox(x, y, fit_train, fit_val)
            base[model_name] = (model, meta)
        late_risks = [base[key][0].predict(blocks[k]) for k, key in enumerate(["clinical", "wsi", "rna"])]
        centers = [float(r[train].mean()) for r in late_risks]
        scales = [max(float(r[train].std()), 1e-6) for r in late_risks]
        standardized = np.stack([(r - m) / s for r, m, s in zip(late_risks, centers, scales)], axis=1)
        weights = []
        for c in [0.25, 0.5, 0.75]:
            for fraction in [0.25, 0.5, 0.75]:
                w = np.array([c, (1 - c) * fraction, (1 - c) * (1 - fraction)])
                effective = present * w
                pred = (standardized * effective).sum(1) / effective.sum(1)
                weights.append((concordance(y[val], pred[val]), w))
        late_score, late_weights = max(weights, key=lambda x: x[0])
        neurons = {}
        for key, drop in [("masked_transformer", False), ("dropout_transformer", True)]:
            checkpoint = out / f"{name}_{key}.pt"
            neurons[key] = fit_neural(blocks, present, y, train, val,
                seed=model_seed,
                dropout=drop, device=device, max_epochs=args.epochs, patience=30,
                checkpoint_path=str(checkpoint), resume=args.resume)

        def predict(model_name, bb, mm, selected):
            if model_name in neurons:
                return neurons[model_name].predict(bb, mm, device=device)
            if model_name == "late_fusion":
                r = np.stack([(base[key][0].predict(bb[k]) - centers[k]) / scales[k] for k, key in enumerate(["clinical", "wsi", "rna"])], axis=1)
                w = mm * late_weights
                return (r * w).sum(1) / w.sum(1)
            if model_name == "early_fusion":
                x = np.concatenate([*bb, mm[:, 1:].astype(float)], axis=1)
            elif model_name == "mask_only":
                x = missing[selected].copy()
                x[:, -3] = ~mm[:, 1]
                x[:, -2] = ~mm[:, 2]
            elif model_name == "clinical_mask":
                m = missing[selected].copy()
                m[:, -3], m[:, -2] = ~mm[:, 1], ~mm[:, 2]
                x = np.c_[bb[0], m]
            else:
                x = bb[["clinical", "wsi", "rna"].index(model_name)]
            return base[model_name][0].predict(x)

        all_names = [*base, "late_fusion", *neurons]
        for model_name in all_names:
            training_risk = predict(model_name, [b[train] for b in blocks], present[train], train)
            # Train-only univariate Cox calibration gives comparable survival probabilities.
            center = float(training_risk.mean())
            scale = max(float(training_risk.std()), 1e-6)
            calibration = CoxPHSurvivalAnalysis(alpha=10.0).fit(((training_risk - center) / scale)[:, None], y[train])
            meta = neurons[model_name].meta if model_name in neurons else {"val_cindex": late_score, "weights": late_weights.tolist()} if model_name == "late_fusion" else base[model_name][1]
            fit_records.append({"experiment": name, "model": model_name, **meta})
            if model_name in neurons:
                torch.save({"state_dict": neurons[model_name].model.state_dict(), "metadata": meta,
                            "experiment": name, "model": model_name, "device": str(device)},
                           out / f"{name}_{model_name}_best.pt")
            for condition, bb, mm in stress_views([b[test] for b in blocks], present[test], seed=901 + number):
                risk = (neurons[model_name].predict(bb, mm, device=device) if model_name in neurons else predict(model_name, bb, mm, test))
                sf = calibration.predict_survival_function(((risk - center) / scale)[:, None])
                survival = np.asarray([f(365.0) for f in sf])
                rec = {"experiment": name, "model": model_name, "condition": condition, **metrics(y[train], y[test], risk, survival)}
                records.append(rec)
                for j, i in enumerate(test):
                    predictions.append({"experiment": name, "model": model_name, "condition": condition,
                                        "patient_id": cohort.patient_id.iloc[i], "cohort": cohort.cohort.iloc[i],
                                        "event": bool(y["event"][i]), "time_days": float(y["time"][i]),
                                        "risk": float(risk[j]), "survival365": float(survival[j])})
        pd.DataFrame(records).to_csv(OUT / "metrics.csv", index=False)
        pd.DataFrame(predictions).to_csv(OUT / "predictions.csv", index=False)
        pd.DataFrame(splits).to_csv(OUT / "splits.csv", index=False)
        (OUT / "fit_metadata.json").write_text(json.dumps(fit_records, indent=2), "utf-8")
        print(name, "complete", len(train), len(val), len(test), flush=True)
        print(pd.DataFrame(records).query("experiment == @name and condition == 'natural'")[["model", "harrell_c", "ipcw_c_3y", "auc_1y", "brier_1y"]].to_string(index=False), flush=True)
    hashes = {str(p.relative_to(HERE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [DATA / "features.npz", DATA / "cohort.csv", DATA / "clinical.csv", Path(__file__), HERE / "models.py", HERE / "prepare.py"]}
    (OUT / "run_manifest.json").write_text(json.dumps({"seed": args.seed, "device": str(device),
        "cuda": {"available": torch.cuda.is_available(), "name": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
                 "capability": torch.cuda.get_device_capability(0) if device.type == "cuda" else None,
                 "torch_cuda": torch.version.cuda}, "versions": {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__, "sklearn": sklearn.__version__, "sksurv": sksurv.__version__}, "hashes": hashes, "status": "completed", "limits": summary["limits"]}, indent=2), "utf-8")
    status_file.write_text(json.dumps({"status": "completed", "completed": pd.Timestamp.now().isoformat()}, indent=2), "utf-8")


if __name__ == "__main__":
    main()
