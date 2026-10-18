"""Compare four forecasters on Guan-calibrated synthetic requested counts.
Run data_synthesis.py first. Inventory outcomes are the separate fixed benchmark.
"""
from pathlib import Path
import argparse, hashlib, json, platform, time
import numpy as np
import pandas as pd
import statsmodels
from statsmodels.stats.diagnostic import acorr_ljungbox
from configuration import Config
from experiment import load_inputs, contract_split
from forecasting import predict, METHODS, error_table
from advanced_forecasting import ARIMA_GRID, SARIMA_GRID, FittedForecaster

ROOT = Path(__file__).resolve().parent


def rolling_records(evaluation, fit_history, spec, scenario, part):
    # This routine does not accept final test data when scoring validation.
    fitted = FittedForecaster(fit_history, spec)
    history = fit_history.astype(float).copy()
    rows = []
    for decision, actual in evaluation.items():
        raw, corrected = fitted.predict(history, decision)
        for h in (1,2):
            target = decision+pd.Timedelta(days=h-1)
            eligible = target in evaluation.index
            rows.append({'scenario':scenario, 'model':spec.family, 'decision_date':decision.date().isoformat(),
                         'target_date':target.date().isoformat(), 'forecast_horizon':h,
                         'history_end':history.index[-1].date().isoformat(), 'fit_end':fit_history.index[-1].date().isoformat(),
                         'raw_predicted_units':float(raw[h-1]), 'predicted_units':float(corrected[h-1]),
                         'negative_correction':bool(raw[h-1]<0), 'decision_split':part,
                         'actual_requested_units':float(evaluation.loc[target]) if eligible else None,
                         'included_in_accuracy':eligible})
        # Actual is revealed after both forecasts; never enters today's decision.
        history = pd.concat([history, pd.Series([float(actual)], index=pd.DatetimeIndex([decision]))])
    return pd.DataFrame(rows), fitted.fit_info


def accuracy(records, weekday=False):
    included = records[records.included_in_accuracy].rename(columns={
        'model':'method', 'decision_split':'split', 'decision_date':'origin_date',
        'target_date':'target_date', 'forecast_horizon':'horizon_days',
        'predicted_units':'forecast_units', 'actual_requested_units':'units_requested'})
    return error_table(included, weekday)


def select_on_development(development, cfg, scenario, out):
    if len(development) != cfg.train_days+cfg.validation_days:
        raise ValueError('Selection receives exactly development data, never test')
    train = development.iloc[:cfg.train_days]
    val = development.iloc[cfg.train_days:]
    selected, candidates, kept_records, fit_infos = {}, [], [], {}
    for family, grid in [('ARIMA', ARIMA_GRID), ('SARIMA', SARIMA_GRID)]:
        ranked=[]
        for i,spec in enumerate(grid):
            row = {'scenario':scenario, **spec.settings()}
            try:
                forecasts, info = rolling_records(val,train,spec,scenario,'validation')
                scores = accuracy(forecasts).set_index('horizon_days')
                row.update(status='accepted', validation_today_MAE=float(scores.loc[1,'MAE']),
                           validation_today_RMSE=float(scores.loc[1,'RMSE']), validation_tomorrow_MAE=float(scores.loc[2,'MAE']),
                           validation_tomorrow_RMSE=float(scores.loc[2,'RMSE']), fit_info=json.dumps(info))
                ranked.append((row['validation_today_MAE'], sum(spec.order[::2])+sum(spec.seasonal_order[::2][:2]),
                               spec.key, spec, forecasts, info))
            except Exception as exc:
                row.update(status='rejected', error=f'{type(exc).__name__}: {exc}')
            candidates.append(row)
            if (i+1)%6 == 0:
                print(f'{scenario} {family}: {i+1}/{len(grid)} candidates checked', flush=True)
        if not ranked:
            raise RuntimeError(f'No valid {family} model for {scenario}')
        best = min(ranked, key=lambda x:x[:3])
        selected[family]=best[3]
        kept_records.append(best[4]); fit_infos[family]=best[5]
        print(f'{scenario} selected {best[3].key}; validation today MAE={best[0]:.4f}',flush=True)
    pd.DataFrame(candidates).to_csv(out/f'validation_search_{scenario}.csv', index=False)
    (out/f'selection_frozen_{scenario}.json').write_text(json.dumps({f:s.settings() for f,s in selected.items()},indent=2))
    return selected, pd.concat(kept_records,ignore_index=True), fit_infos


def baseline_records(series,cfg,scenario):
    split=contract_split(cfg)
    rows=[]
    for decision in series.index[cfg.train_days:]:
        history=series.loc[series.index<decision]
        part=split.label(decision)
        for method in METHODS:
            values=predict(history,decision,2,method)
            for h,value in enumerate(values,1):
                target=decision+pd.Timedelta(days=h-1)
                eligible=target in series.index and split.label(target)==part
                rows.append({'scenario':scenario,'model':method,'decision_date':decision.date().isoformat(),
                             'target_date':target.date().isoformat(),'forecast_horizon':h,
                             'history_end':history.index[-1].date().isoformat(),'fit_end':None,
                             'raw_predicted_units':float(value),'predicted_units':float(value),'negative_correction':False,
                             'decision_split':part,'actual_requested_units':float(series.loc[target]) if target in series.index else None,
                             'included_in_accuracy':eligible})
    return pd.DataFrame(rows)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs')
    args=parser.parse_args();out=args.output_dir
    if out.exists() and any(out.iterdir()):
        parser.error('Choose an empty output directory')
    out.mkdir(parents=True,exist_ok=True)
    cfg=Config.load(ROOT/'config.json')
    frames,quality=load_inputs(cfg,ROOT/'inputs');quality.to_csv(out/'input_quality.csv',index=False)
    settings={'status':'PRELIMINARY_SINGLE_SEED_SYNTHETIC','seed':cfg.seed,'split':contract_split(cfg).as_dict(),
              'selection':'minimum validation today MAE; ties smaller AR/MA count, then lexical key',
              'validation_fit':'training only; fixed parameters, rolling filtered states',
              'test_fit':'selected orders refitted once on full development; fixed parameters, rolling filtered states',
              'features':'past requested counts only; no cycle/calendar regressors or generator means',
              'correction':'max(0, raw prediction), continuous forecasts for metrics',
              'implementation':'statsmodels SARIMAX used for both nonseasonal ARIMA and seasonal SARIMA',
              'ARIMA_grid':[s.settings() for s in ARIMA_GRID], 'SARIMA_grid':[s.settings() for s in SARIMA_GRID],
              'versions':{'python':platform.python_version(),'statsmodels':statsmodels.__version__,'numpy':np.__version__,'pandas':pd.__version__},
              'scenarios':{}}
    selected_all={}; records=[]
    # Complete and persist selection for EVERY scenario before evaluating any test path.
    for scenario,frame in frames.items():
        series=frame.assign(date=pd.to_datetime(frame.date)).set_index('date').units_requested.asfreq('D')
        dev=series.iloc[:cfg.train_days+cfg.validation_days]
        selected,val_records,val_fit=select_on_development(dev,cfg,scenario,out)
        selected_all[scenario]=selected;records.append(val_records)
        settings['scenarios'][scenario]={'selected_models':{f:s.settings() for f,s in selected.items()},'validation_fits':val_fit}
    (out/'settings_before_test.json').write_text(json.dumps(settings,indent=2))
    diagnostics=[]
    for scenario,frame in frames.items():
        series=frame.assign(date=pd.to_datetime(frame.date)).set_index('date').units_requested.asfreq('D')
        dev=series.iloc[:cfg.train_days+cfg.validation_days];test=series.iloc[len(dev):]
        for family,spec in selected_all[scenario].items():
            predictions,info=rolling_records(test,dev,spec,scenario,'test')
            records.append(predictions);settings['scenarios'][scenario].setdefault('final_fits',{})[family]=info
            fit=FittedForecaster(dev,spec)
            burn=max(14,fit.result.loglikelihood_burn)
            res=np.asarray(fit.result.resid)[burn:]
            df=sum(spec.order[::2])+sum(spec.seasonal_order[::2][:2])
            lb=acorr_ljungbox(res,lags=[7,14,21],model_df=df,return_df=True)
            for lag,row in lb.iterrows():
                diagnostics.append({'scenario':scenario,'model':family,'fit_period':'development',
                                    'lag':lag,'model_df':df,'ljung_box_stat':row.lb_stat,'p_value':row.lb_pvalue})
            print(f'{scenario} {family} final test complete',flush=True)
        records.append(baseline_records(series,cfg,scenario))
    forecasts=pd.concat(records,ignore_index=True)
    # Preserve cross-boundary actuals for audit but keep them excluded from accuracy.
    actuals={(s,str(d)):int(v) for s,f in frames.items() for d,v in zip(f.date,f.units_requested)}
    forecasts['actual_requested_units']=[actuals.get((s,d),np.nan) for s,d in zip(forecasts.scenario,forecasts.target_date)]
    forecasts.to_csv(out/'forecasts.csv',index=False)
    accuracy(forecasts).to_csv(out/'forecast_accuracy.csv',index=False)
    accuracy(forecasts,True).to_csv(out/'forecast_accuracy_by_weekday.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(out/'development_residual_diagnostics.csv',index=False)
    (out/'model_settings.json').write_text(json.dumps(settings,indent=2))
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [*sorted((ROOT/'inputs').glob('*.csv')),ROOT/'config.json',ROOT/'advanced_forecasting.py',ROOT/'forecast_models.py',ROOT/'forecasting.py',ROOT/'simulator.py']}
    (out/'source_hashes.json').write_text(json.dumps(manifest,indent=2))
    print(accuracy(forecasts).query("split=='test'").to_string(index=False),flush=True)


if __name__=='__main__':
    main()
