"""Fold-local preprocessing and small Cox / masked-token survival baselines."""
import copy
import pickle

import numpy as np
import torch
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sksurv.linear_model import CoxPHSurvivalAnalysis
from sksurv.metrics import concordance_index_censored
from torch import nn


class Preprocessor:
    def fit(self, arrays, clinical_columns, train):
        # age_bin is an encoded ten-year category, not a continuous age value.
        numeric = [i for i, c in enumerate(clinical_columns) if c in {
            "exposures.pack_years_smoked", "exposures.tobacco_years_smoked"}]
        cats = [i for i in range(len(clinical_columns)) if i not in numeric]
        self.clinical = ColumnTransformer([
            ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True), StandardScaler()), numeric),
            ("cat", make_pipeline(SimpleImputer(strategy="constant", fill_value=-1),
                                  OneHotEncoder(handle_unknown="ignore", sparse_output=False)), cats)])
        self.clinical.fit(arrays["clinical"][train])
        self.image = {}
        for key in ["wsi", "rna"]:
            a = arrays[key][train]
            observed = np.isfinite(a).all(axis=1)
            a = a[observed]
            variance = a.var(axis=0)
            selected = np.argsort(variance)[-min(256, a.shape[1]):]
            scale = StandardScaler().fit(a[:, selected])
            pca = PCA(n_components=min(16, len(a) - 1, len(selected)), svd_solver="full").fit(scale.transform(a[:, selected]))
            self.image[key] = (selected, scale, pca)
        return self

    def transform(self, arrays):
        blocks = [self.clinical.transform(arrays["clinical"]).astype(np.float32)]
        mask = [np.ones(len(blocks[0]), dtype=bool)]
        for key in ["wsi", "rna"]:
            present = np.isfinite(arrays[key]).all(axis=1)
            selected, scale, pca = self.image[key]
            x = np.zeros((len(present), pca.n_components_), dtype=np.float32)
            x[present] = pca.transform(scale.transform(arrays[key][present][:, selected]))
            blocks.append(x)
            mask.append(present)
        return blocks, np.stack(mask, axis=1)

    def save(self, path):
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)


def censor_y(event, time):
    y = np.empty(len(time), dtype=[("event", bool), ("time", float)])
    y["event"] = event
    y["time"] = time
    return y


def concordance(y, risk):
    return float(concordance_index_censored(y["event"], y["time"], risk)[0])


def fit_cox(x, y, train, val):
    results = []
    for alpha in [1.0, 10.0, 100.0]:
        model = CoxPHSurvivalAnalysis(alpha=alpha, ties="breslow", n_iter=150)
        model.fit(x[train].astype(float), y[train])
        score = concordance(y[val], model.predict(x[val]))
        results.append((score, alpha, model))
    score, alpha, model = max(results, key=lambda r: r[0])
    return model, {"alpha": alpha, "val_cindex": score}


def cox_loss(risk, event, time):
    # All equal-time patients are in each tied event's risk set (Breslow ties).
    risk_set = time[None, :] >= time[:, None]
    denominator = torch.logsumexp(risk[None, :].expand(len(time), -1).masked_fill(~risk_set, -torch.inf), dim=1)
    return (denominator[event] - risk[event]).mean()


class TokenCox(nn.Module):
    def __init__(self, dims):
        super().__init__()
        self.projections = nn.ModuleList([nn.Linear(d, 32) for d in dims])
        self.modality = nn.Parameter(torch.zeros(3, 32))
        layer = nn.TransformerEncoderLayer(32, 4, dim_feedforward=64, dropout=0.1, batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, 1, enable_nested_tensor=False)
        self.head = nn.Sequential(nn.LayerNorm(32), nn.Linear(32, 1))

    def forward(self, blocks, present):
        tokens = torch.stack([p(x) for p, x in zip(self.projections, blocks)], dim=1) + self.modality
        tokens = self.encoder(tokens, src_key_padding_mask=~present)
        pooled = (tokens * present[..., None]).sum(1) / present.sum(1, keepdim=True)
        return self.head(pooled).squeeze(1)


class ConcatMLPCox(nn.Module):
    """Simple early-concatenation MLP Cox model used as a neural baseline."""
    def __init__(self, dims):
        super().__init__()
        total=sum(dims)+2  # two image-modality availability indicators
        self.network=nn.Sequential(nn.Linear(total,64),nn.ReLU(),nn.Dropout(0.1),
                                   nn.Linear(64,32),nn.ReLU(),nn.Dropout(0.1),
                                   nn.Linear(32,1))

    def forward(self, blocks, present=None):
        # Inputs are already fold-standardized. Missing imaging embeddings are zeros;
        # append the availability indicators so missing and observed-zero are distinct.
        x=torch.cat([*blocks, present[:,1:].to(blocks[0].dtype)],dim=1)
        return self.network(x).squeeze(1)


class NeuralModel:
    def __init__(self, model, meta):
        self.model = model
        self.meta = meta

    def predict(self, blocks, present, device=None):
        self.model.eval()
        device = torch.device(device) if device is not None else next(self.model.parameters()).device
        with torch.no_grad():
            return self.model([torch.as_tensor(b, dtype=torch.float32, device=device) for b in blocks],
                              torch.as_tensor(present, dtype=torch.bool, device=device)).detach().cpu().numpy().astype(float)


def fit_neural(blocks, present, y, train, val, seed, dropout=False, device="cpu",
               max_epochs=300, patience=30, learning_rate=0.001, weight_decay=0.01,
               dropout_rate=0.3, checkpoint_path=None, resume=False, architecture="token"):
    device = torch.device(device)
    torch.manual_seed(seed)
    model = TokenCox([b.shape[1] for b in blocks]) if architecture=="token" else ConcatMLPCox([b.shape[1] for b in blocks])
    model=model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    xb = [torch.as_tensor(b[train], dtype=torch.float32, device=device) for b in blocks]
    mask = torch.as_tensor(present[train], dtype=torch.bool, device=device)
    event = torch.as_tensor(y["event"][train], dtype=torch.bool, device=device)
    time = torch.as_tensor(y["time"][train], dtype=torch.float32, device=device)
    best, state, stale, selected_epoch, start_epoch = -np.inf, None, 0, 0, 0
    if resume and checkpoint_path and __import__("pathlib").Path(checkpoint_path).exists():
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        best, state = checkpoint["best_val"], checkpoint["best_model"]
        stale, selected_epoch, start_epoch = checkpoint["stale"], checkpoint["selected_epoch"], checkpoint["epoch"]
    wrapper = NeuralModel(model, {})
    for epoch in range(start_epoch + 1, max_epochs + 1):
        model.train()
        active = mask.clone()
        if dropout:
            active[:, 1:] &= torch.rand(active[:, 1:].shape, device=device) > dropout_rate
        risk = model(xb, active)
        loss = cox_loss(risk, event, time)
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite neural Cox loss")
        optimizer.zero_grad()
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
        if not torch.isfinite(grad_norm):
            raise ValueError("Nonfinite neural Cox gradient norm")
        optimizer.step()
        if epoch % 5 == 0 or epoch == max_epochs:
            pred = wrapper.predict([b[val] for b in blocks], present[val], device=device)
            score = concordance(y[val], pred)
            if score > best + 0.0001:
                best, state, stale, selected_epoch = score, copy.deepcopy(model.state_dict()), 0, epoch
            else:
                stale += 5
            if stale >= patience:
                break
        if checkpoint_path:
            torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                        "best_model": state, "best_val": best, "stale": stale,
                        "selected_epoch": selected_epoch, "epoch": epoch, "seed": seed,
                        "device": str(device)}, checkpoint_path)
    model.load_state_dict(state)
    return NeuralModel(model, {"val_cindex": best, "epoch": selected_epoch,
                              "parameters": sum(p.numel() for p in model.parameters()), "modality_dropout": dropout,
                              "device": str(device), "learning_rate": learning_rate,
                              "weight_decay": weight_decay, "dropout_rate": dropout_rate,
                              "architecture":architecture})
