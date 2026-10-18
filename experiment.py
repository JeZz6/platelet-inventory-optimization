"""Shared chronological evaluation and inventory-verification helpers."""
from dataclasses import asdict,replace
from datetime import date,timedelta
from pathlib import Path
import argparse, hashlib, json, platform, time
import numpy as np
import pandas as pd
from configuration import Config
from forecasting import METHODS, Split, validate_demand, forecast_records, error_table
from integration import BaselineProvider, PolicySpec, OrderingPolicy
from policies import make_baseline
from simulator import simulate, summarize

ROOT=Path(__file__).resolve().parent
BUFFER_GRID=tuple(range(21))  # provisional 0..20 units, fixed BEFORE test


def contract_split(cfg):
    start=pd.Timestamp(cfg.start_date)
    return Split(start, start+pd.Timedelta(days=cfg.train_days),
                 start+pd.Timedelta(days=cfg.train_days+cfg.validation_days),
                 start+pd.Timedelta(days=cfg.n_days),
                 "Member 2 contract v1.0 exact configured day-index boundaries")


def load_inputs(cfg, input_dir):
    frames, quality=[] ,[]
    for scenario in cfg.scenario_ids:
        path=input_dir/f"forecast_input_{scenario}.csv"
        frame=pd.read_csv(path)
        if "generator_mean_units" in frame.columns:
            raise ValueError("Generator means must not be present in forecasting inputs")
        clean=validate_demand(frame)
        expected=pd.date_range(cfg.start_date,periods=cfg.n_days)
        if len(clean)!=cfg.n_days or clean.scenario.unique().tolist()!=[scenario] or not clean.date.reset_index(drop=True).equals(pd.Series(expected)):
            raise ValueError("Input scenario/calendar differs from modelling contract")
        split=contract_split(cfg)
        expected_labels=[split.label(d) for d in clean.date]
        original=frame.copy()
        original["date"]=pd.to_datetime(original.date)
        original=original.sort_values("date")
        if "split" not in original or original.split.tolist()!=expected_labels:
            raise ValueError("Input split labels differ from contract")
        # Forecast and simulator inputs retain ONLY exogenous requested counts
        # and dates. Unused calendar/cycle columns stay in originals for audit.
        clean["date"]=clean.date.dt.strftime("%Y-%m-%d")
        clean["split"]=expected_labels
        frames.append(clean)
        quality.append({"scenario":scenario,"rows":len(clean),"zero_demand_days":int((clean.units_requested==0).sum()),
                        "missing_dates":0,"duplicate_dates":0,"invalid_counts":0,
                        "input_sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    return {f.scenario.iloc[0]:f for f in frames},pd.DataFrame(quality)


def baseline_accuracy(frame,cfg):
    series=frame.assign(date=pd.to_datetime(frame.date)).set_index("date").units_requested
    split=replace(contract_split(cfg),end_exclusive=series.index[-1]+pd.Timedelta(days=1))
    records=forecast_records(series,str(frame.scenario.iloc[0]),split)
    errors=error_table(records)
    weekdays=error_table(records,True)
    return records,errors,weekdays


def make_specs(training_mean):
    specs=[PolicySpec("fixed_daily","fixed_daily",training_mean),
           PolicySpec("historical_base_stock","historical_base_stock",training_mean)]
    for method in METHODS:
        for kind in ("forecast_aggregate","forecast_age_aware"):
            specs.append(PolicySpec(f"{kind}_{method}",kind,training_mean,method))
    return specs


def run_policy(frame,cfg,spec,fixed_quantity,activation_date,forecast_activation_date):
    policy=OrderingPolicy(spec,fixed_quantity,activation_date)
    provider=BaselineProvider(spec.method,forecast_activation_date) if spec.kind.startswith("forecast") else None
    result=simulate(frame,cfg,policy,spec.name,forecast_provider=provider)
    return result,policy,provider


def tune_on_development(development,cfg,buffer_grid=BUFFER_GRID):
    """The function never accepts or accesses actual TEST observations.

    simulate requires the complete configured calendar. Append a zero-demand
    tail as a technical replay scaffold; only [train_end,development_end) is
    scored. No scaffold outputs are presented as project results. All final
    runs use the untouched supplied demand. The engine/config remain unchanged.
    """
    dev_end=cfg.train_days+cfg.validation_days
    if len(development)!=dev_end:
        raise ValueError("Tuning accepts exactly the development prefix")
    scenario=development.scenario.iloc[0]
    expected=pd.date_range(cfg.start_date,periods=dev_end).strftime("%Y-%m-%d").tolist()
    if development.date.tolist()!=expected:
        raise ValueError("Development dates differ from contract")
    tail_dates=pd.date_range(cfg.start_date,periods=cfg.n_days)[dev_end:]
    scaffold=pd.DataFrame({"date":tail_dates.strftime("%Y-%m-%d"),"scenario":scenario,"units_requested":0,"split":"test_scaffold_not_observed"})
    replay=pd.concat([development,scaffold],ignore_index=True)
    mean=float(development.units_requested.iloc[:cfg.train_days].mean())
    fixed_quantity=make_baseline(cfg,scenario).quantity
    activate=(date.fromisoformat(cfg.start_date)+timedelta(days=cfg.train_days))
    selected,candidates=[],[]
    for spec in make_specs(mean):
        if spec.kind=="fixed_daily":
            selected.append(spec)
            continue
        ranked=[]
        for buffer in buffer_grid:
            candidate=PolicySpec(spec.name,spec.kind,mean,spec.method,float(buffer))
            result,_,_=run_policy(replay,cfg,candidate,fixed_quantity,activate,activate)
            metrics=summarize(result,cfg,cfg.train_days,dev_end,"validation")
            candidates.append({"model":candidate.method if candidate.kind.startswith("forecast") else "training_mean",
                               "buffer_units":buffer,**metrics})
            ranked.append((metrics["weighted_shortage_expiry"],buffer,candidate))
        selected.append(min(ranked,key=lambda x:(x[0],x[1]))[2])
    return selected,pd.DataFrame(candidates)


def join_actuals(provider_records,frame,cfg):
    df=pd.DataFrame(provider_records)
    actual=frame[["date","units_requested"]].rename(columns={"date":"target_date","units_requested":"actual_requested_units"})
    df=df.merge(actual,on="target_date",how="left",validate="many_to_one")
    split=contract_split(cfg)
    df["decision_split"]=[split.label(d) for d in df.decision_date]
    df["target_split"]=[split.label(d) if pd.Timestamp(d)<split.end_exclusive else "beyond_data" for d in df.target_date]
    df["included_in_accuracy"]=(df.decision_split==df.target_split)&df.actual_requested_units.notna()
    return df


def verify_run(result,frame,cfg):
    if result.daily.date.tolist()!=frame.date.tolist() or result.daily.units_requested.tolist()!=frame.units_requested.tolist():
        raise AssertionError("Simulator changed demand dates or path")
    if not (result.audits.stock_balance_residual==0).all() or not (result.audits.request_balance_residual==0).all():
        raise AssertionError("Conservation failed")
    if result.audits.opening_stock.tolist()[1:]!=result.daily.closing_stock.tolist()[:-1]:
        raise AssertionError("Inventory did not carry across calendar days")
    qty=result.daily.units_ordered
    if (qty<0).any() or (qty%1!=0).any():
        raise AssertionError("Invalid order counts")
    for start,end,label in ((0,cfg.train_days,"train"),(cfg.train_days,cfg.train_days+cfg.validation_days,"validation"),
                            (cfg.train_days+cfg.validation_days,cfg.n_days,"test")):
        summarize(result,cfg,start,end,label)


