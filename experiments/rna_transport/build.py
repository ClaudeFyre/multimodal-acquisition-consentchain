"""Build H2 analysis inputs exactly as specified in PROTOCOL_H2.md (+ DEVIATIONS.md #1–5).

Outputs (built/):
  dev_expr.parquet      genes x patients, GDC tpm_unstranded, gene symbols
  dev_clin.parquet      patient_id, age_bin, sex, histology, stage, time_days, event, source
  <GSE>_expr.parquet    genes x samples, probe-collapsed (max-mean probe per gene, within cohort)
  <GSE>_clin.parquet    sample, age_bin, sex, histology, stage, time_days, event (+ exclusion log)
  build_report.json     counts at every inclusion/exclusion step
"""
from __future__ import annotations

import gzip
import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "built"
GEO = ROOT / "data" / "raw" / "geo"
GDC = ROOT / "data" / "raw" / "gdc"
PRIMARY = ["GSE72094", "GSE68465", "GSE31210", "GSE50081", "GSE37745", "GSE30219", "GSE42127"]
PLATFORM = {"GSE72094": "GPL15048", "GSE68465": "GPL96", "GSE31210": "GPL570", "GSE50081": "GPL570",
            "GSE37745": "GPL570", "GSE30219": "GPL570", "GSE42127": "GPL6884", "GSE41271": "GPL6884"}
REPORT: dict = {}

# ----------------------------------------------------------------------------- shared encoders (protocol §3)


def age_bin(age) -> str:
    a = pd.to_numeric(age, errors="coerce")
    return "missing" if pd.isna(a) else f"{int(a // 10) * 10}s"


def stage_group(s) -> str | None:
    """'Stage IIIA' / 'IIIA' / '3a' / '1B' / '4' -> 'I'..'IV'."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    t = str(s).strip().upper().replace("STAGE", "").strip()
    m = re.match(r"^(IV|III|II|I)(?![IV])", t)
    if m:
        return m.group(1)
    m = re.match(r"^([1-4])", t)
    if m:
        return ["I", "II", "III", "IV"][int(m.group(1)) - 1]
    return None


def tnm_group(t: str | None, n: str | None, m: str | None) -> str | None:
    """AJCC 7th edition grouping (protocol §3)."""
    def num(x, p):
        mm = re.search(p + r"\s*([0-4])", str(x or "").upper())
        return int(mm.group(1)) if mm else None
    T, N, M = num(t, "T"), num(n, "N"), num(m, "M")
    if M == 1:
        return "IV"
    if T is None or N is None:
        return None
    if T == 4 or N >= 2 or (T == 3 and N == 1):
        return "III"
    if (T == 3 and N == 0) or (N == 1 and T <= 2):
        return "II"
    if T <= 2 and N == 0:
        return "I"
    return None


def histology_icdo(code) -> str:
    m = re.match(r"(\d{4})", str(code or ""))
    if not m:
        return "other"
    c = int(m.group(1))
    if 8140 <= c <= 8255 or 8480 <= c <= 8490:
        return "adeno"
    if 8050 <= c <= 8084:
        return "squamous"
    return "other"


def histology_text(x) -> str:
    t = str(x or "").lower()
    if re.search(r"adeno|^adc$", t) and "squam" not in t:
        return "adeno"
    if re.search(r"squam|^sqc$|^bas$", t):
        return "squamous"
    return "other"


def sex_norm(x) -> str:
    t = str(x or "").strip().lower()
    return {"m": "male", "male": "male", "f": "female", "female": "female"}.get(t, "missing")


# ----------------------------------------------------------------------------- development cohort


def pick_diagnosis(case: dict) -> dict:
    dx = case.get("diagnoses") or []
    for d in dx:
        if d.get("diagnosis_is_primary_disease") is True:
            return d
    for d in dx:
        if d.get("ajcc_pathologic_stage"):
            return d
    return dx[0] if dx else {}


def build_dev() -> None:
    cohort = pd.read_csv(ROOT / "experiments/lung_missingness/prepared/cohort.csv")
    raw = {}
    for p in ["tcga-luad", "tcga-lusc", "cptac-luad", "cptac-lscc"]:
        for f in (GDC / p).glob("*.json"):
            for h in json.loads(f.read_text("utf-8")):
                raw[h["submitter_id"]] = h
    rows = []
    for r in cohort.itertuples():
        h = raw.get(r.patient_id, {})
        d = pick_diagnosis(h)
        demo = h.get("demographic") or {}
        age = d.get("age_at_diagnosis")
        age = age / 365.25 if age is not None else demo.get("age_at_index")
        st = d.get("ajcc_pathologic_stage")
        rows.append({"patient_id": r.patient_id, "source": r.cohort, "age_bin": age_bin(age),
                     "sex": sex_norm(demo.get("sex_at_birth") or demo.get("gender")),
                     "histology": histology_icdo(d.get("morphology")),
                     "stage": stage_group(st), "time_days": r.time_days, "event": bool(r.event)})
    clin = pd.DataFrame(rows)

    sel = pd.read_csv(GDC / "lung-dev-star-counts" / "selected_files.csv")
    series = {}
    for r in sel.itertuples():
        t = pd.read_csv(GDC / "lung-dev-star-counts" / f"{r.file_id}.tsv", sep="\t", comment="#",
                        usecols=["gene_id", "gene_name", "tpm_unstranded"])
        t = t[t.gene_id.str.startswith("ENSG")]
        series[r.patient_id] = t.set_index("gene_id")
    first = next(iter(series.values()))
    pd.DataFrame({"ensembl": first.index.str.split(".").str[0], "symbol": first.gene_name.values}) \
        .to_csv(OUT / "dev_gene_map.csv", index=False)  # GENCODE v36 map, used by the MMIST sensitivity run
    expr = pd.DataFrame({pid: s.tpm_unstranded for pid, s in series.items()})
    expr.insert(0, "gene_name", first.gene_name.reindex(expr.index))
    # DEVIATIONS #5: duplicate symbols -> keep the Ensembl ID with the highest mean TPM
    expr["_mean"] = expr.drop(columns="gene_name").mean(axis=1)
    expr = expr.sort_values("_mean", ascending=False).drop_duplicates("gene_name").drop(columns="_mean")
    expr = expr.set_index("gene_name")
    keep = clin.patient_id.isin(expr.columns)
    REPORT["dev"] = {"cohort": len(clin), "with_rna": int(keep.sum()),
                     "with_stage": int((keep & clin.stage.notna()).sum()),
                     "events_with_rna_stage": int((keep & clin.stage.notna() & clin.event).sum()),
                     "stage": clin[keep].stage.value_counts(dropna=False).to_dict(),
                     "histology": clin[keep].histology.value_counts().to_dict()}
    clin[keep].to_parquet(OUT / "dev_clin.parquet", index=False)
    expr.to_parquet(OUT / "dev_expr.parquet")


# ----------------------------------------------------------------------------- GEO


def read_series_matrix(g: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    with gzip.open(GEO / g / f"{g}_series_matrix.txt.gz", "rt", encoding="utf-8", errors="replace") as f:
        text = f.read()
    head, rest = text.split("!series_matrix_table_begin", 1)
    table = rest.split("!series_matrix_table_end", 1)[0]
    expr = pd.read_csv(io.StringIO(table), sep="\t", index_col=0, low_memory=False)
    expr.index = expr.index.astype(str)
    expr = expr.apply(pd.to_numeric, errors="coerce")
    ann = {}
    for line in head.splitlines():
        parts = [x.strip('"') for x in line.split("\t")]
        if parts[0] == "!Sample_geo_accession":
            ann["gsm"] = parts[1:]
        elif parts[0] == "!Sample_source_name_ch1":
            ann["source_name"] = parts[1:]
        elif parts[0] == "!Sample_characteristics_ch1":
            for i, cell in enumerate(parts[1:]):
                if ":" in cell:
                    k, v = cell.split(":", 1)
                    ann.setdefault(k.strip().lower(), [None] * len(parts[1:]))[i] = v.strip()
    n = len(ann["gsm"])
    return expr, pd.DataFrame({k: (v + [None] * n)[:n] for k, v in ann.items()})


def read_platform(p: str) -> pd.Series:
    """probe ID -> single gene symbol (multi-gene probes dropped; protocol §4.2)."""
    annot = GEO / "platforms" / f"{p}.annot.gz"
    full = GEO / "platforms" / f"{p}.full.txt.gz"
    path = annot if annot.exists() else full
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        lines = [ln for ln in f if not ln.startswith(("#", "!", "^"))]
    t = pd.read_csv(io.StringIO("".join(lines)), sep="\t", dtype=str, low_memory=False)
    cols = {c.lower().replace("_", " "): c for c in t.columns}
    sym = next(cols[c] for c in ["gene symbol", "symbol", "genesymbol", "gene name"] if c in cols)
    s = t.set_index(t.columns[0])[sym].dropna().astype(str).str.strip()
    s = s[(s != "") & ~s.str.contains(r"///|//|;|,")]
    s.index = s.index.astype(str)
    REPORT.setdefault("platform", {})[p] = {"file": path.name, "probes_single_gene": int(len(s)),
                                            "genes": int(s.nunique())}
    return s


OUTCOME = {  # protocol §2.2 table: (time field, unit factor to days, event field, event test)
    "GSE72094": ("survival_time_in_days", 1.0, "vital_status", lambda v: v.lower() == "dead"),
    "GSE68465": ("months_to_last_contact_or_death", 30.4375, "vital_status", lambda v: v.lower() == "dead"),
    "GSE31210": ("days before death/censor", 1.0, "death", lambda v: v.lower() == "dead"),
    "GSE50081": ("survival time", 365.25, "status", lambda v: v.lower() == "dead"),
    "GSE37745": ("days to determined death status", 1.0, "dead", lambda v: v.lower() == "yes"),
    "GSE30219": ("follow-up time (months)", 30.4375, "status", lambda v: v.upper() == "DEAD"),
    "GSE42127": ("overall survival months", 30.4375, "survival status", lambda v: v.upper() == "D"),
}


def geo_clinical(g: str, a: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    log = {"samples": len(a)}
    keep = pd.Series(True, index=a.index)

    def drop(mask, why):
        nonlocal keep
        n = int((keep & mask).sum())
        if n:
            log[f"excluded_{why}"] = n
        keep = keep & ~mask

    get = lambda c: a[c] if c in a else pd.Series([None] * len(a), index=a.index)  # noqa: E731
    if g == "GSE68465":
        drop(get("source_name").eq("HLM"), "HLM_moffitt_overlap")
        stage = [tnm_group(*(re.findall(r"pT\d", x or "") or [None]), *(re.findall(r"pN\d", x or "") or [None]), None)
                 for x in get("disease_stage")]
        hist = ["adeno"] * len(a)  # GSE68465 is a lung adenocarcinoma series (Director's Challenge)
        age, sex = get("age"), get("sex")
    elif g == "GSE31210":
        drop(get("tissue").ne("primary lung tumor"), "non_tumour")
        drop(get("exclude for prognosis analysis due to incomplete resection or adjuvant therapy").eq("exclude"),
             "author_exclude_flag")
        stage, hist = get("pathological stage").map(stage_group), ["adeno"] * len(a)
        age, sex = get("age (years)"), get("gender")
    elif g == "GSE30219":
        h = get("histology")
        drop(get("source_name").ne("Lung Tumour"), "non_tumour")
        drop(~h.isin(["ADC", "SQC", "BAS"]), "non_nsclc_or_other_histology")
        stage = [tnm_group(t, n, m) for t, n, m in zip(get("pt stage"), get("pn stage"), get("pm stage"))]
        hist, age, sex = h.map(histology_text), get("age at surgery"), get("gender")
    elif g == "GSE72094":
        stage, hist, age, sex = get("stage").map(stage_group), ["adeno"] * len(a), get("age_at_diagnosis"), get("gender")
    elif g == "GSE50081":
        stage, hist, age, sex = get("stage").map(stage_group), get("histology").map(histology_text), get("age"), get("sex")
    elif g == "GSE37745":
        stage, hist, age, sex = get("tumor stage").map(stage_group), get("histology").map(histology_text), get("age"), get("gender")
    elif g == "GSE42127":
        stage, hist = get("final.pat.stage").map(stage_group), get("histology").map(histology_text)
        age, sex = get("age at surgery"), get("gender")
    else:
        raise KeyError(g)
    tfield, factor, efield, isdead = OUTCOME[g]
    time = pd.to_numeric(get(tfield), errors="coerce") * factor
    ev_raw = get(efield)
    ok_outcome = time.gt(0) & ev_raw.notna() & ~ev_raw.astype(str).str.upper().isin(["NA", "N/A", "UNKNOWN", ""])
    drop(~ok_outcome, "missing_or_nonpositive_outcome")
    clin = pd.DataFrame({"sample": a["gsm"], "age_bin": [age_bin(x) for x in age],
                         "sex": [sex_norm(x) for x in sex], "histology": list(hist), "stage": list(stage),
                         "time_days": time, "event": [bool(isdead(str(v))) if v is not None else None for v in ev_raw]})
    clin = clin[keep.values].reset_index(drop=True)
    log["included_any_stage"] = len(clin)
    log["missing_stage"] = int(clin.stage.isna().sum())
    return clin, log


def build_geo(g: str) -> None:
    expr, ann = read_series_matrix(g)
    probe2gene = read_platform(PLATFORM[g])
    clin, log = geo_clinical(g, ann)
    e = expr.loc[expr.index.intersection(probe2gene.index), clin["sample"]]
    e.insert(0, "gene", probe2gene.reindex(e.index).values)
    e["_mean"] = e.drop(columns="gene").mean(axis=1)      # protocol §4.3: max-mean probe per gene
    e = e.sort_values("_mean", ascending=False).drop_duplicates("gene").drop(columns="_mean").set_index("gene")
    log.update({"probes_in_matrix": int(len(expr)), "genes_after_collapse": int(len(e)),
                "value_range": [float(np.nanmin(e.values)), float(np.nanmax(e.values))]})
    REPORT.setdefault("geo", {})[g] = log
    clin.to_parquet(OUT / f"{g}_clin.parquet", index=False)
    e.to_parquet(OUT / f"{g}_expr.parquet")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    build_dev()
    for g in PRIMARY:
        build_geo(g)
        print(g, REPORT["geo"][g], flush=True)
    (OUT / "build_report.json").write_text(json.dumps(REPORT, indent=1, default=str), "utf-8")
    print(json.dumps(REPORT["dev"], indent=1, default=str))
