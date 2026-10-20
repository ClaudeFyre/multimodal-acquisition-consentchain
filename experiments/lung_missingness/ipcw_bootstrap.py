"""Patient-paired fold-wise IPCW C-index bootstrap for the frozen v2 run."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sksurv.nonparametric import CensoringDistributionEstimator

HERE=Path(__file__).resolve().parent
RUN=HERE/"runs"/"internal5x3_final_categorical_age"
OUT=HERE/"results_v2_final"
TAU=1095.0
B=2000

def structured(df):
    y=np.empty(len(df),dtype=[("event",bool),("time",float)])
    y["event"]=df.event.to_numpy(bool); y["time"]=df.time_days.to_numpy(float)
    return y

def pair_components(test, risk):
    times=test.time_days.to_numpy(float)
    events=test.event.to_numpy(bool)
    comp=events[:,None]&(times[:,None]<times[None,:])
    ii,jj=np.where(comp)
    delta=risk[ii]-risk[jj]
    concord=(delta>1e-8).astype(float)+.5*(np.abs(delta)<=1e-8)
    return ii,jj,concord

def main():
    pred=pd.read_csv(RUN/"predictions.csv")
    split=pd.read_csv(RUN/"splits.csv")
    cohort=pd.read_csv(HERE/"prepared"/"cohort.csv")
    ymap=cohort.set_index("patient_id")
    metrics=pd.read_csv(RUN/"metrics.csv")
    internal=sorted(e for e in pred.experiment.unique() if e.startswith("internal_"))
    rng=np.random.default_rng(20261005)
    comp_defs=[("early_fusion_vs_clinical_natural","natural","early_fusion","clinical"),
               ("dropout_vs_masked_natural","natural","dropout_transformer","masked_transformer")]
    results=[]
    for cname,condition,left,right in comp_defs:
        fold_obs=[]; fold_boot=[]; model_fold_boot={left:[],right:[]}; n_rows=0
        for fold in range(5):
            experiments=[e for e in internal if e.startswith(f"internal_{fold}_seed")]
            if not experiments: continue
            per_seed=[]; boot_seed=[]
            ref=None
            for exp in experiments:
                roles=split[split.experiment==exp]
                train_ids=roles.loc[roles.role=="train","patient_id"].tolist()
                ytrain=ymap.loc[train_ids]
                train_struct=structured(ytrain)
                # Restrict training censoring support at 3 years using the same IPCW convention as scikit-survival.
                cde=CensoringDistributionEstimator().fit(train_struct)
                q=pred[(pred.experiment==exp)&(pred.condition==condition)&(pred.time_days<TAU)]
                a=q[q.model==left].sort_values("patient_id")
                b=q[q.model==right].sort_values("patient_id")
                if ref is None: ref=a
                if len(a)==0 or len(a)!=len(b) or not np.array_equal(a.patient_id.to_numpy(),b.patient_id.to_numpy()):
                    raise ValueError(f"paired predictions mismatch: {exp}/{condition}")
                ev=a.event.to_numpy(bool); raw_t=a.time_days.to_numpy(float)
                t=raw_t
                # IPCW concordance weights each comparable event by 1/G(T)^2.
                yt=np.empty(len(a),dtype=[("event",bool),("time",float)])
                yt["event"]=ev; yt["time"]=t
                ipcw=cde.predict_ipcw(yt)
                weights=ipcw**2
                ra=a.risk.to_numpy(float); rb=b.risk.to_numpy(float)
                ii,jj,ca=pair_components(a,ra); _,_,cb=pair_components(b,rb)
                pair_w=weights[ii]
                den=pair_w.sum()
                if not den: raise ValueError(f"no IPCW-comparable pairs in {exp}")
                per_seed.append((float(pair_w@ca/den),float(pair_w@cb/den),float(pair_w@(ca-cb)/den)))
                # Resample test patients; reuse each fold's multinomial sample across models and seeds.
                n=len(a); n_rows=n
                if len(boot_seed)<len(experiments):
                    counts=np.zeros((B,n),dtype=np.float64)
                    for j in range(B): counts[j]=np.bincount(rng.integers(0,n,n),minlength=n)
                    if ref is None: pass
                    # Persist for all seeds in this fold through the fold-local variable below.
                    if 'fold_counts' not in locals() or locals().get('fold_marker')!=fold:
                        fold_counts=counts; fold_marker=fold
                pair_mult=fold_counts[:,ii]*fold_counts[:,jj]*pair_w[None,:]
                den_b=pair_mult.sum(axis=1)
                boot_seed.append((pair_mult@ca/den_b,pair_mult@cb/den_b,pair_mult@(ca-cb)/den_b))
            arr=np.asarray(per_seed)
            fold_obs.append(arr.mean(axis=0))
            bs=np.mean(np.stack([x[2] for x in boot_seed]),axis=0)
            ba=np.mean(np.stack([x[0] for x in boot_seed]),axis=0)
            bb=np.mean(np.stack([x[1] for x in boot_seed]),axis=0)
            fold_boot.append((ba,bb,bs))
            model_fold_boot[left].append(ba); model_fold_boot[right].append(bb)
        obs=np.mean(fold_obs,axis=0)
        boots=np.mean(np.stack([x[2] for x in fold_boot]),axis=0)
        p=(2*min(np.mean(boots<=0),np.mean(boots>=0))*B+1)/(B+1)
        p=min(1.,float(p))
        results.append({"comparison":cname,"condition":condition,"left_model":left,"right_model":right,
            "left_ipcw_c_3y":float(obs[0]),"right_ipcw_c_3y":float(obs[1]),"delta_ipcw_c_3y":float(obs[2]),
            "delta_ci95_low":float(np.quantile(boots,.025)),"delta_ci95_high":float(np.quantile(boots,.975)),
            "bootstrap_p_two_sided":p,"bootstrap_n":B,"folds":len(fold_obs),"training_seeds_per_fold":3,
            "test_patient_bootstrap":"within outer fold; shared resamples across models and training seeds",
            "censoring_distribution":"fit on corresponding outer-fold training set; held fixed during test bootstrap",
            "estimand":"mean of fold-specific Uno IPCW C-index; not pooled risks"})
        del fold_counts
    # Holm correction across the two frozen primary comparisons.
    order=sorted(range(len(results)),key=lambda i:results[i]["bootstrap_p_two_sided"])
    adj=[0.]*len(results); running=0.
    for rank,i in enumerate(order):
        running=max(running,min(1.,(len(results)-rank)*results[i]["bootstrap_p_two_sided"]))
        adj[i]=running
    for i,r in enumerate(results):r["holm_adjusted_p"]=adj[i]
    pd.DataFrame(results).to_csv(OUT/"primary_ipcw_comparisons.csv",index=False)
    path=OUT/"analysis_manifest.json"
    d=json.loads(path.read_text("utf-8")); d["ipcw_bootstrap"]={"status":"completed","seed":20261005,"n":B,"results":results,"notes":"Patient bootstrap conditions on fitted models and fold-specific training censoring distribution; it does not include model refitting uncertainty."}
    path.write_text(json.dumps(d,indent=2),"utf-8")
    print(pd.DataFrame(results).to_string(index=False))
if __name__=="__main__":main()
