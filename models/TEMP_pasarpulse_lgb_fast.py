from __future__ import annotations

import argparse
import importlib.util
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.metrics import mean_absolute_error, mean_squared_error


def load_optimizer(path: Path):
    spec = importlib.util.spec_from_file_location("pasarpulse_core", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def metric_row(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    denom = np.abs(y) + np.abs(p)
    return {
        "mae_idr_per_kg": float(np.mean(np.abs(y-p))),
        "rmse_idr_per_kg": float(np.sqrt(np.mean((y-p)**2))),
        "smape_percent": float(np.mean(2*np.abs(y-p)/np.where(denom==0,1,denom))*100),
        "mean_error_idr_per_kg": float(np.mean(p-y)),
    }


def blend_weights(y, predictions):
    names = list(predictions)
    P = np.column_stack([predictions[n] for n in names])
    def obj(w):
        return np.mean(np.abs(y - P @ w))
    constraints = ({"type": "eq", "fun": lambda w: np.sum(w)-1.0},)
    bounds = [(0.0, 1.0)] * len(names)
    starts = [np.ones(len(names))/len(names)]
    starts += [np.eye(len(names))[i] for i in range(len(names))]
    best = None
    for x0 in starts:
        result = minimize(obj, x0, method="SLSQP", bounds=bounds, constraints=constraints,
                          options={"maxiter": 250, "ftol": 1e-7})
        if result.success and (best is None or result.fun < best.fun):
            best = result
    if best is None:
        weights = np.ones(len(names))/len(names)
        score = obj(weights)
    else:
        weights = np.clip(best.x,0,1); weights /= weights.sum(); score = best.fun
    return dict(zip(names, weights)), float(score)


def run(core, panel, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    variants = {
        "B2_price_only_LGBM": core.PRICE_BASE + core.CATEGORICAL[:-1],
        "B3_price_calendar_LGBM": core.PRICE_BASE + core.CALENDAR + core.CATEGORICAL,
        "B6_dynamic_graph_LGBM": core.PRICE_BASE + core.CALENDAR + core.GRAPH + core.CATEGORICAL,
    }
    fold_rows = []
    prediction_rows = []
    feature_rows = []
    for horizon in core.HORIZONS:
        supervised = core.create_supervised(panel, horizon)
        valid = ((supervised.observed == 1) & (supervised.target_observed == 1)
                 & supervised.target_price.notna() & supervised.price_filled.notna())
        supervised = supervised[valid].copy()
        for fold_id, origin in enumerate(core.ORIGINS, 1):
            print(f"h={horizon} fold={fold_id} origin={origin.date()}", flush=True)
            train = supervised[(supervised.date < origin)
                               & ((supervised.date + pd.Timedelta(days=horizon)) <= origin)].copy()
            test = supervised[supervised.date == origin].copy()
            counts = train.groupby("series_id", observed=True).size()
            eligible = counts[counts >= 240].index
            train = train[train.series_id.isin(eligible)].copy()
            test = test[test.series_id.isin(eligible)].copy()
            sw = core.recent_weights(train.date, origin)
            predictions = {}
            for name, requested in variants.items():
                feats = [f for f in requested if f in train]
                delta, model = core.fit_predict_lgb(
                    train, test, feats, "target_delta", sw,
                    {"n_estimators": 420, "learning_rate": 0.035, "num_leaves": 39,
                     "min_child_samples": 65, "max_bin": 127, "reg_lambda": 2.0},
                )
                pred = np.clip(test.price_filled.to_numpy() + delta, 1000, 500000)
                predictions[name] = pred
                fold_rows.append({"model": name, "horizon_days": horizon,
                                  "fold_id": fold_id, "forecast_origin": str(origin.date()),
                                  "rows_scored": len(test), **metric_row(test.target_price, pred)})

            final_feats = [f for f in (variants["B6_dynamic_graph_LGBM"] +
                           ["target_dow","target_month","target_doy_sin","target_doy_cos"])
                           if f in train]
            params = {"n_estimators": 700, "learning_rate": 0.025, "num_leaves": 47,
                      "min_child_samples": 50, "max_bin": 127, "reg_alpha": 0.05,
                      "reg_lambda": 2.5, "colsample_bytree": 0.9}
            d, model = core.fit_predict_lgb(train,test,final_feats,"target_delta",sw,params)
            l, _ = core.fit_predict_lgb(train,test,final_feats,"target_logratio",sw,params)
            a, _ = core.fit_predict_lgb(train,test,final_feats,"target_price",sw,params)
            current = test.price_filled.to_numpy()
            test_lag = test[f"price_lag_{horizon}"].to_numpy(dtype=float)
            test_lag = np.where(np.isfinite(test_lag), test_lag, current)
            experts = {
                "lgb_delta": np.clip(current+d,1000,500000),
                "lgb_logratio": np.clip(current*np.exp(np.clip(l,-1.2,1.2)),1000,500000),
                "lgb_level": np.clip(a,1000,500000),
                "last_price": current,
                "momentum": np.clip(current + 0.5*(current-test_lag),1000,500000),
            }
            val_start = origin-pd.Timedelta(days=84)
            inner = train[(train.date+pd.Timedelta(days=horizon)) < val_start].copy()
            val = train[(train.date >= val_start)
                        & ((train.date+pd.Timedelta(days=horizon)) <= origin)].copy()
            if len(inner) > 5000 and len(val) > 300:
                iw = core.recent_weights(inner.date,val_start)
                inner_params = dict(params); inner_params["n_estimators"] = 400
                vd,_=core.fit_predict_lgb(inner,val,final_feats,"target_delta",iw,inner_params)
                vl,_=core.fit_predict_lgb(inner,val,final_feats,"target_logratio",iw,inner_params)
                va,_=core.fit_predict_lgb(inner,val,final_feats,"target_price",iw,inner_params)
                vc=val.price_filled.to_numpy()
                val_lag = val[f"price_lag_{horizon}"].to_numpy(dtype=float)
                val_lag = np.where(np.isfinite(val_lag), val_lag, vc)
                val_experts={
                    "lgb_delta":np.clip(vc+vd,1000,500000),
                    "lgb_logratio":np.clip(vc*np.exp(np.clip(vl,-1.2,1.2)),1000,500000),
                    "lgb_level":np.clip(va,1000,500000),
                    "last_price":vc,
                    "momentum":np.clip(vc+0.5*(vc-val_lag),1000,500000),
                }
                weights, inner_mae = blend_weights(val.target_price.to_numpy(), val_experts)
            else:
                weights={"lgb_delta":0.45,"lgb_logratio":0.2,"lgb_level":0.2,"last_price":0.15,"momentum":0.0}
                inner_mae=np.nan
            blend=sum(weights[k]*experts[k] for k in weights)
            max_change=np.maximum(9000,0.40*current)
            blend=np.clip(blend,current-max_change,current+max_change)
            model_name="PROPOSED_tree_dynamic_graph_ensemble"
            fold_rows.append({"model":model_name,"horizon_days":horizon,"fold_id":fold_id,
                              "forecast_origin":str(origin.date()),"rows_scored":len(test),
                              "inner_val_mae":inner_mae,"blend_weights":json.dumps(weights),
                              **metric_row(test.target_price,blend)})
            for expert,pred in experts.items():
                fold_rows.append({"model":f"expert_{expert}","horizon_days":horizon,
                                  "fold_id":fold_id,"forecast_origin":str(origin.date()),
                                  "rows_scored":len(test),**metric_row(test.target_price,pred)})
            base=test[["series_id","province_code","province_name","commodity_code",
                       "commodity_name","market_level","date","target_price","price_filled"]].copy()
            base=base.rename(columns={"date":"forecast_origin","target_price":"actual_price",
                                      "price_filled":"current_price"})
            base["target_date"]=base.forecast_origin+pd.Timedelta(days=horizon)
            base["horizon_days"]=horizon; base["fold_id"]=fold_id
            output={**predictions,**{f"expert_{k}":v for k,v in experts.items()},model_name:blend}
            for name,pred in output.items():
                part=base.copy(); part["model"]=name; part["predicted_price"]=pred
                part["absolute_error"]=(part.actual_price-part.predicted_price).abs()
                prediction_rows.append(part)
            for feature, importance in zip(final_feats, model.feature_importances_):
                feature_rows.append({"horizon_days":horizon,"fold_id":fold_id,
                                     "feature":feature,"importance":float(importance)})
    preds=pd.concat(prediction_rows,ignore_index=True)
    folds=pd.DataFrame(fold_rows)
    pooled=[]
    for (name,h),g in preds.groupby(["model","horizon_days"]):
        pooled.append({"model":name,"horizon_days":h,"rows_scored":len(g),
                       "series_scored":g.series_id.nunique(),"folds_scored":g.fold_id.nunique(),
                       **metric_row(g.actual_price,g.predicted_price)})
    pooled=pd.DataFrame(pooled).sort_values(["horizon_days","mae_idr_per_kg"])
    preds.to_csv(outdir/"oof_predictions.csv",index=False)
    folds.to_csv(outdir/"fold_metrics.csv",index=False)
    pooled.to_csv(outdir/"pooled_metrics.csv",index=False)
    pd.DataFrame(feature_rows).to_csv(outdir/"feature_importance.csv",index=False)
    print(pooled.to_string(index=False),flush=True)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--core",type=Path,required=True)
    ap.add_argument("--workdir",type=Path,required=True); args=ap.parse_args()
    core=load_optimizer(args.core)
    work=args.workdir; work.mkdir(parents=True,exist_ok=True); out=work/"results"
    price_path=work/"price_daily.csv"
    if price_path.exists():
        raw=pd.read_csv(price_path,parse_dates=["date"],dtype={"province_code":str})
    else:
        raw=core.download_prices(work/"raw_pihps"); raw.to_csv(price_path,index=False)
    panel_path=work/"panel_features.parquet"
    if panel_path.exists(): panel=pd.read_parquet(panel_path)
    else:
        panel=core.build_panel(raw); panel.to_parquet(panel_path,index=False)
    started=time.time(); run(core,panel,out)
    (out/"runtime_seconds.txt").write_text(str(time.time()-started))

if __name__=="__main__": main()
