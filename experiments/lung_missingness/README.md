# MMIST-LUNG survival and missingness pilot

## Protocol v2 execution (2026-10-04)

Protocol v2 artifacts are isolated from the original pilot outputs. Read `REPORT_PROTOCOL_V2_2026-10-04.md`, `FOLLOWUP_ANALYSIS_2026-10-04.md`, and `EXECUTION_LOG_PROTOCOL_V2.md` for completed steps, intermediate runs, deviations, and limits. The final internal run is `runs/internal5x3_final_categorical_age/`; tuned neural grid, two-way transfer, and conditional deletion runs are under `runs/neural_grid_v2_retry1/`, `runs/cohort_transfer_v2/`, and `runs/conditional_stress_v2/`. Summaries and curves are under `results_v2_final/`. The provenance audit is under `audit_v2/`.

Claims remain limited to retrospective technical evaluation because patient-level index/acquisition order is unknown. CPTAC was already explored. Follow-up work added IPCW-scale patient-paired bootstrap, MLP-Cox and the planned optimization grid, 1/2/3-year AUC/Brier and supported-interval integrated Brier, train-only calibrated out-of-fold calibration curves, bidirectional cohort transfer, and age/stage-conditioned artificial deletion. PCA/raw-feature sensitivity, stage-time-defined prediction, and real missingness validation remain unresolved. Local TCIA NSCLC-Radiomics and NSCLC-Radiogenomics data are candidate cohorts only; neither is established as confirmatory same-modality validation. See `RESEARCH_DECISION_AND_NEXT_STEPS.md` for the current method decision, `ROADMAP_6_9_MONTHS.md` for the staged research plan, and `audit_v2/` for the data card, provenance, exclusions, unresolved issues, and cohort shortlist.

For a new, separate run (never point output-dir at existing results), use:

```powershell
experiments\.venv\Scripts\python.exe -X utf8 experiments\lung_missingness\run_gpu.py --device cuda --internal-only --protocol experiments\lung_missingness\protocol_v2.json --output-dir experiments\lung_missingness\runs\new_run_name
```

`--device cuda` fails if CUDA is unavailable; it never silently falls back. `--resume` reuses only the named run directory. See `--help` for fold/seed selection.

Exploratory experiments completed locally on 2026-10-04. All source datasets are read-only. Outputs stay in this directory; no new imaging download is needed.

## Reproduce

From `E:\MedicalResearch`, use the project-scoped environment `experiments\.venv` (system packages are visible, scikit-survival and its updated sklearn are installed only inside this environment):

```powershell
experiments\.venv\Scripts\python.exe -X utf8 experiments\lung_missingness\prepare.py
experiments\.venv\Scripts\python.exe -X utf8 experiments\lung_missingness\test_integrity.py
experiments\.venv\Scripts\python.exe -X utf8 experiments\lung_missingness\run.py
experiments\.venv\Scripts\python.exe -X utf8 experiments\lung_missingness\analyze.py
experiments\.venv\Scripts\python.exe -X utf8 experiments\lung_missingness\robustness.py
```

`prepare.py` reconstructs retrospective index-time overall survival from cached GDC cases, explicit Alive/Dead status and positive follow-up/death time. Missing death times are never automatically censored. It pools author-frozen slide/series features per patient. It exports exclusions, time sources, source hashes and an allow-list of baseline clinical inputs. RNA input remains the author's preselected/preprocessed feature file; fold-local variance selection, scaling and PCA cannot undo preprocessing already performed by the authors.

`run.py` uses 3 patient-disjoint internal folds (each has an inner validation set) and three TCGA train/validation seeds with the same 308-patient CPTAC held-out cohort. Preprocessing and regularization selection use training/validation only. No author folds or outcome CSV labels are treated as ground truth. Cox baselines, late fusion, masked Transformer and random-modality-dropout Transformer are evaluated on natural, absent-modality, random missingness and content permutation conditions. The latter is a diagnostic intervention, not a clinical missingness model.

Survival probabilities at 365 days are calibrated using a train-only scalar Cox model. Metrics are Harrell C, IPCW C truncated at 3 years, IPCW cumulative AUC at 1 year, and IPCW Brier at 1 year. No integrated Brier score or clinical-benefit claim is made in this pilot. The fitted survival function may still be miscalibrated under source shift.

`analyze.py` saves patient-paired percentile bootstrap intervals for predefined comparisons. External seeds share bootstrap patient samples; they do not create 924 independent patients. Intervals condition on fitted models (no training resampling) and are exploratory without multiplicity correction. Internal comparison intervals average fold-wise concordance, avoiding uncalibrated risk pooling across models fitted on different folds.

`robustness.py` is a second, explicitly exploratory ablation on the already observed external cohort. Four variants share initial seeds, architecture, preprocessing, validation-only stopping and train/test patients: masked only, random dropout, random dropout plus centered risk consistency, and conditional dropout plus the same consistency. Age/stage thresholds are derived only on the training split; the direction of conditional dropout varies across training epochs. Additional age-conditioned RNA removal tests do not use outcome labels. This is not a final test set for selecting a publishable method; independent verification will be required.

## Limitations to resolve before publication

- GDC index dates and imaging/specimen collection times are not fully reconciled; this is not validated prospective prognosis.
- Diagnosis/pathologic stage is assumed available; distinguish diagnosis-time and postoperative prediction.
- Almost all eligible patients have WSI/RNA features. Artificial deletion tests do not establish real MNAR modality robustness.
- Public feature preprocessing and encoder training populations are not fully audited for leakage.
- Clinical coded categories follow author encoding, and genotype source preprocessing differs from the paper description.
- Author-defined 12-month/DSS labels are audited but not used as OS targets; disagreements may reflect version or endpoint differences.
- The original pilot used CPU-bounded training. Protocol v2 adds a CUDA entry point; see the separate v2 run manifests for device evidence. No weights are exported for clinical use.

## Outputs

- `prepared/`: audited cohort, feature arrays and metadata.
- `results/`: initial nine-model metrics, patient predictions, folds, fitted hyperparameters, paired intervals and environment/hash manifest.
- `robustness_results/`: controlled four-variant exploratory ablation.
- `REPORT_2026-10-04.md`: interpreted results and next-step decision.

Metric references: [scikit-survival evaluation guide](https://scikit-survival.readthedocs.io/en/stable/user_guide/evaluating-survival-models.html), [penalized Cox guide](https://scikit-survival.readthedocs.io/en/stable/user_guide/coxnet.html).
