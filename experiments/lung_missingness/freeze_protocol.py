"""Freeze protocol_v2 before starting any new runs."""
import hashlib, json, platform
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd, sklearn, sksurv, torch
HERE=Path(__file__).resolve().parent
DATA=HERE/"prepared"
OUT=HERE/"protocol_v2.json"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if OUT.exists(): raise FileExistsError(f"Refusing to overwrite frozen protocol: {OUT}")
    cohort=pd.read_csv(DATA/"cohort.csv")
    seed=20261004
    strata=cohort.cohort.astype(str)+"_"+cohort.event.astype(str)
    # Materialize the frozen patient-level outer assignment before fitting any new models.
    from sklearn.model_selection import StratifiedKFold
    splitter=StratifiedKFold(n_splits=5,shuffle=True,random_state=seed)
    folds=[]
    import numpy as np
    idx=np.arange(len(cohort))
    for fold,(_,test) in enumerate(splitter.split(idx,strata)):
        folds.extend({"patient_id":cohort.patient_id.iloc[i],"outer_fold":fold} for i in test)
    pd.DataFrame(folds).to_csv(HERE/"audit_v2"/"patient_outer_folds.csv",index=False)
    doc={"protocol_version":"2.0","frozen_at_utc":datetime.now(timezone.utc).isoformat(),
      "data_status":"previously observed cohort; no independent validation claim",
      "cohort":{"n":len(cohort),"events":int(cohort.event.sum()),"by_source":cohort.groupby("cohort").size().to_dict()},
      "split":{"unit":"patient_id","outer_folds":5,"stratify":["cohort","event"],"random_state":seed,
       "neural_seeds":[41,42,43],"inner_validation_fraction":0.2,"inner_validation_seed_rule":"101 + outer_fold"},
      "primary_estimand":{"metric":"3-year IPCW C-index","time_days":1095,"support":"training censoring distribution; report tau, effective support, and evaluable N; outside support is not estimable"},
      "secondary_metrics":["Harrell C","time-dependent AUC at 1, 2, 3 years","Brier at 1, 2, 3 years","integrated Brier over supported interval","calibration curves at supported horizons"],
      "comparisons":{"primary":["early_fusion Cox vs baseline clinical Cox","random-dropout TokenCox vs same-architecture masked TokenCox"],"correction":"Holm","other_comparisons":"exploratory"},
      "models":{"classical":["clinical Cox","WSI Cox","RNA Cox","missing-mask Cox","clinical plus mask Cox","early-fusion Cox","validation-weighted late fusion"],
       "neural":["concatenation MLP-Cox","masked TokenCox","random-modality-dropout TokenCox"],
       "preprocessing_primary":"top256 variance selection then train-fold standardization/PCA16","sensitivity":["PCA32","WSI raw 768 projection"],
       "search":{"learning_rate":[0.0003,0.001],"weight_decay":[0.001,0.01],"token_dimensions":32,"token_layers":1,"dropout":[0.1,0.3,0.5],"max_epochs":300,"validation_every":5,"patience":30,"seeds":[41,42,43]}},
      "stress_conditions":["natural","no_wsi","no_rna","clinical_only","random_drop_0","random_drop_0.1","random_drop_0.3","random_drop_0.5","random_drop_0.7","random_drop_0.9","age_conditioned","age_conditioned_reverse","stage_conditioned","stage_conditioned_reverse","within_patient_content_permutation"],
      "stress_threshold_source":"training fold only; outcome never used to generate missingness","missingness_intervention_limit":"artificial deletion is not evidence of real MNAR robustness",
      "clinical_inputs":{"baseline_candidates":["diagnoses.age_bin","demographic.gender","demographic.race","demographic.ethnicity","exposures.pack_years_smoked","exposures.tobacco_smoking_status","exposures.tobacco_years_smoked","diagnoses.icd_10_code","diagnoses.morphology","diagnoses.prior_malignancy"],"stage_enhanced":["diagnoses.ajcc_pathologic_m","diagnoses.ajcc_pathologic_n","diagnoses.ajcc_pathologic_stage","diagnoses.ajcc_pathologic_t","diagnoses.ajcc_staging_system_edition"],"age_bin":"categorical ten-year bin; continuous age not available","stage":"exploratory only; likely postoperative and not for diagnosis-time primary analysis"},
      "calibration":"fit on training patients only; never fit on validation/test outcomes",
      "bootstrap":{"unit":"patient","paired":True,"seeds_share_resample":True,"resamples":2000},
      "external_migration":"TCGA-to-CPTAC and reverse are exploratory; CPTAC already used; never label as unseen final test",
      "stopping_threshold":{"primary_missingness_mean_cindex_gain_min":0.01,"natural_performance_drop_max":0.01,"requires_cross_fold_seed_stability":True,"requires_corrected_interval_support":True},
      "limits":["time-origin and acquisition order unresolved; retrospective technical analysis only","RNA upstream selection/normalization and WSI encoder population unverified","no independent external cohort available locally"],
      "hashes":{p.name:sha(p) for p in [DATA/"features.npz",DATA/"cohort.csv",DATA/"clinical.csv",HERE/"models.py",HERE/"prepare.py",HERE/"audit_v2.py"]},
      "environment":{"python":platform.python_version(),"numpy":np.__version__,"pandas":pd.__version__,"torch":torch.__version__,"torch_cuda":torch.version.cuda,"sklearn":sklearn.__version__,"sksurv":sksurv.__version__}}
    OUT.write_text(json.dumps(doc,indent=2,default=str),"utf-8")
    print("Frozen",OUT)
if __name__=="__main__": main()
