"""Freeze PROTOCOL_H2.md before any GEO expression data is downloaded or any outcome is analysed.

Writes protocol_h2.freeze.json: protocol SHA-256, UTC time, the data files touched so far
(GEO sample annotations used only for event counts / field formats), and the environment.
Refuses to overwrite an existing freeze.
"""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PROTOCOL = HERE / "PROTOCOL_H2.md"
OUT = HERE / "protocol_h2.freeze.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite frozen protocol: {OUT}")
    geo = ROOT / "discovery" / "geo"
    touched = sorted(geo.glob("GSE*_samples.csv")) + [geo / "geo_lung_os_screen.csv", geo / "gdc_dev_rna_files.csv"]
    expression = [p.name for p in geo.glob("*series_matrix*")] + [p.name for p in geo.glob("GPL*")]
    if expression:
        raise RuntimeError(f"Expression/platform files already present, freeze would be invalid: {expression}")
    import numpy, pandas, sklearn, sksurv
    rec = {
        "protocol": PROTOCOL.name,
        "protocol_sha256": sha(PROTOCOL),
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_state": "GEO: sample annotations only (event totals + field formats). No expression downloaded; "
                      "no outcome-covariate or outcome-expression analysis. Dev cohort previously used internally.",
        "files_touched_before_freeze": {str(p.relative_to(ROOT)): sha(p) for p in touched if p.exists()},
        "dev_cohort_file": {"experiments/lung_missingness/prepared/cohort.csv":
                            sha(ROOT / "experiments/lung_missingness/prepared/cohort.csv")},
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "numpy": numpy.__version__, "pandas": pandas.__version__,
                        "scikit-learn": sklearn.__version__, "scikit-survival": sksurv.__version__},
    }
    OUT.write_text(json.dumps(rec, indent=2, ensure_ascii=False), "utf-8")
    print(f"frozen {PROTOCOL.name} sha256={rec['protocol_sha256'][:16]}… at {rec['frozen_at_utc']}")


if __name__ == "__main__":
    main()
