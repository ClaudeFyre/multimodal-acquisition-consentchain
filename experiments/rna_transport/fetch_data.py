"""Download H2 inputs over the DIRECT route only (no proxy; see medlake/network.py).

1. GEO series matrices (expression + sample annotations) for the 7 primary cohorts + GSE41271
2. GEO platform annotation tables (probe -> gene symbol) for GPL570, GPL96, GPL6884, GPL15048
3. GDC STAR-Counts files (primary tumour, one per patient by smallest file_id) for the dev cohort

Run only after freeze_protocol.py. Every GDC file is checked against GDC's md5sum.
"""
import gzip
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from medlake.network import configure  # noqa: E402

configure("direct")
import requests  # noqa: E402

if not (HERE / "protocol_h2.freeze.json").exists():
    raise SystemExit("Protocol not frozen — run freeze_protocol.py first")

RAW = ROOT / "data" / "raw" / "geo"
GDC_DIR = ROOT / "data" / "raw" / "gdc" / "lung-dev-star-counts"
GEO_FTP = "https://ftp.ncbi.nlm.nih.gov/geo"
COHORTS = ["GSE72094", "GSE68465", "GSE31210", "GSE50081", "GSE37745", "GSE30219", "GSE42127", "GSE41271"]
PLATFORMS = ["GPL570", "GPL96", "GPL6884", "GPL15048"]
S = requests.Session()
S.headers["User-Agent"] = "medlake-h2/1.0 (research; direct)"
LOG = []


def stem(acc: str) -> str:
    return acc[:-3] + "nnn" if len(acc) > 6 else acc[:3] + "nnn"


def get(url: str, out: Path) -> Path:
    if out.exists() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    with S.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for ch in r.iter_content(1 << 20):
                f.write(ch)
    tmp.replace(out)
    LOG.append({"url": url, "file": str(out.relative_to(ROOT)), "bytes": out.stat().st_size})
    return out


def geo() -> None:
    for g in COHORTS:
        get(f"{GEO_FTP}/series/{stem(g)}/{g}/matrix/{g}_series_matrix.txt.gz",
            RAW / g / f"{g}_series_matrix.txt.gz")
        print("GEO", g, "ok", flush=True)
    for p in PLATFORMS:
        out = RAW / "platforms" / f"{p}.annot.gz"
        try:
            get(f"{GEO_FTP}/platforms/{stem(p)}/{p}/annot/{p}.annot.gz", out)
        except requests.HTTPError:
            # some platforms have no curated .annot; fall back to the submitter's full table
            txt = RAW / "platforms" / f"{p}.full.txt.gz"
            if not txt.exists():
                r = S.get("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi",
                          params={"acc": p, "targ": "self", "form": "text", "view": "data"}, timeout=300)
                r.raise_for_status()
                txt.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(txt, "wb") as f:
                    f.write(r.content)
                LOG.append({"url": r.url, "file": str(txt.relative_to(ROOT)), "bytes": txt.stat().st_size})
        print("GPL", p, "ok", flush=True)


def gdc() -> None:
    import pandas as pd
    files = pd.read_csv(ROOT / "discovery" / "geo" / "gdc_dev_rna_files.csv")
    tum = files[files.sample_type.str.contains("Primary Tumor", na=False)]
    pick = tum.sort_values("file_id").groupby("patient_id", as_index=False).first()  # protocol §2.1
    meta = S.post("https://api.gdc.cancer.gov/files", json={
        "filters": {"op": "in", "content": {"field": "file_id", "value": pick.file_id.tolist()}},
        "fields": "file_id,file_name,md5sum,file_size", "size": 5000, "format": "json"}, timeout=180).json()
    md5 = {h["file_id"]: h for h in meta["data"]["hits"]}
    pick = pick.assign(md5=pick.file_id.map(lambda x: md5[x]["md5sum"]))
    GDC_DIR.mkdir(parents=True, exist_ok=True)
    pick.to_csv(GDC_DIR / "selected_files.csv", index=False)

    def one(row):
        out = GDC_DIR / f"{row.file_id}.tsv"
        if not (out.exists() and hashlib.md5(out.read_bytes()).hexdigest() == row.md5):
            get(f"https://api.gdc.cancer.gov/data/{row.file_id}", out)
            if hashlib.md5(out.read_bytes()).hexdigest() != row.md5:
                out.unlink()
                raise RuntimeError(f"md5 mismatch {row.file_id}")
        return row.file_id

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, r) for r in pick.itertuples()]
        for i, f in enumerate(as_completed(futs), 1):
            f.result()
            if i % 100 == 0:
                print(f"GDC {i}/{len(futs)}", flush=True)
    print(f"GDC done: {len(pick)} patients, md5 verified", flush=True)


if __name__ == "__main__":
    geo()
    gdc()
    prov = HERE / "fetch_provenance.json"
    old = json.loads(prov.read_text("utf-8")) if prov.exists() else []
    old.append({"time": datetime.now(timezone.utc).isoformat(), "route": "direct", "downloads": LOG})
    prov.write_text(json.dumps(old, indent=1), "utf-8")
