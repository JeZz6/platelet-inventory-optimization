"""Independent saved-result audit and actual simulator callback smoke tests."""
from pathlib import Path
import argparse,json
from datetime import date
from unittest.mock import patch
import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX
from configuration import Config
from experiment import load_inputs,contract_split,verify_run
from advanced_forecasting import ModelSpec,AdvancedProvider
from simulator import simulate
from policies import make_baseline

ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=ROOT/'outputs')
    out=p.parse_args().output_dir;cfg=Config.load(ROOT/'config.json')
    frames,_=load_inputs(cfg,ROOT/'inputs');split=contract_split(cfg)
    records=pd.read_csv(out/'forecasts.csv');scores=pd.read_csv(out/'forecast_accuracy.csv')
    settings=json.loads((out/'model_settings.json').read_text())
    frozen=json.loads((out/'settings_before_test.json').read_text())
    assert len(records)==len(frames)*4*(cfg.n_days-cfg.train_days)*2
    assert not records.duplicated(['scenario','model','decision_date','forecast_horizon']).any()
    assert np.isfinite(records.predicted_units).all() and (records.predicted_units>=0).all()
    assert (pd.to_datetime(records.history_end)==pd.to_datetime(records.decision_date)-pd.Timedelta(days=1)).all()
    assert (pd.to_datetime(records.target_date)==pd.to_datetime(records.decision_date)+pd.to_timedelta(records.forecast_horizon-1,unit='D')).all()
    assert np.allclose(records.predicted_units,np.maximum(0,records.raw_predicted_units))
    indexed={s:f.set_index('date').units_requested for s,f in frames.items()}
    for r in records.itertuples():
        expected_actual=indexed[r.scenario].get(r.target_date,np.nan)
        assert (pd.isna(r.actual_requested_units) and pd.isna(expected_actual)) or r.actual_requested_units==expected_actual
        expected_include=not pd.isna(expected_actual) and split.label(r.target_date)==r.decision_split
        assert r.included_in_accuracy==expected_include
    counts={('validation',1):91,('validation',2):90,('test',1):183,('test',2):182}
    for (s,part,h),group in records[records.included_in_accuracy].groupby(['scenario','decision_split','forecast_horizon']):
        reference=None
        for model,g in group.groupby('model'):
            assert len(g)==counts[(part,h)]
            dates=g.target_date.tolist()
            if reference is None:reference=dates
            else:assert dates==reference
            row=scores[(scores.scenario==s)&(scores.split==part)&(scores.method==model)&(scores.horizon_days==h)].iloc[0]
            errors=g.predicted_units.to_numpy()-g.actual_requested_units.to_numpy()
            assert abs(row.MAE-np.abs(errors).mean())<1e-10
            assert abs(row.RMSE-np.sqrt(np.mean(errors**2)))<1e-10
    filtered_checks=0;live_checks=0
    for scenario,frame in frames.items():
        candidates=pd.read_csv(out/f'validation_search_{scenario}.csv')
        before=frozen['scenarios'][scenario]['selected_models'];after=settings['scenarios'][scenario]['selected_models']
        assert before==after
        series=frame.assign(date=pd.to_datetime(frame.date)).set_index('date').units_requested.asfreq('D')
        dev=series.iloc[:547]
        for family in ('ARIMA','SARIMA'):
            info=after[family];spec=ModelSpec(family,tuple(info['order']),tuple(info['seasonal_order']))
            accepted=candidates[(candidates.family==family)&(candidates.status=='accepted')]
            assert abs(float(accepted[accepted.key==spec.key].validation_today_MAE.iloc[0])-float(accepted.validation_today_MAE.min()))<1e-12
            final_fit=settings['scenarios'][scenario]['final_fits'][family]
            assert final_fit['converged'] and final_fit['training_n']==547 and final_fit['training_end']=='2025-06-30'
            expected=records[(records.scenario==scenario)&(records.model==family)&(records.decision_split=='test')]
            assert (expected.fit_end=='2025-06-30').all()
            # Independently filter each full prefix using saved parameters, avoiding extend().
            for i in (547,570,729):
                prefix=series.iloc[:i].astype(float)
                model=SARIMAX(prefix,order=spec.order,seasonal_order=spec.seasonal_order,trend=spec.trend,
                              enforce_stationarity=True,enforce_invertibility=True,simple_differencing=False)
                params=[final_fit['params'][name] for name in model.param_names]
                estimates=np.maximum(0,np.asarray(model.filter(params).forecast(2)))
                saved=expected[expected.decision_date==series.index[i].date().isoformat()].predicted_units
                np.testing.assert_allclose(estimates,saved,rtol=1e-8,atol=1e-8);filtered_checks+=1
            # Real unchanged simulator, fixed ordering: verify callback forecasts only.
            # Replay the stored fit so this audit tests state updates and callbacks,
            # not whether a fresh optimizer run is identical on a different CPU.
            replay_model=SARIMAX(dev.astype(float),order=spec.order,seasonal_order=spec.seasonal_order,
                                 trend=spec.trend,enforce_stationarity=True,enforce_invertibility=True,
                                 simple_differencing=False)
            replay_params=[final_fit['params'][name] for name in replay_model.param_names]
            with patch('advanced_forecasting.fit_model',
                       return_value=(replay_model.filter(replay_params),final_fit.copy())):
                provider=AdvancedProvider(dev,spec,date(2025,7,1))
            result=simulate(frame,cfg,make_baseline(cfg,scenario),'fixed_daily',forecast_provider=provider)
            verify_run(result,frame,cfg)
            pd.testing.assert_frame_equal(result.daily,pd.read_csv(ROOT/'baseline'/f'baseline_{scenario}_daily.csv'))
            live=pd.DataFrame(provider.records)
            assert live.decision_date.tolist()==expected.decision_date.tolist()
            np.testing.assert_allclose(live.predicted_units,expected.predicted_units,rtol=1e-8,atol=1e-8)
            live_checks+=1
            print(f'{scenario} {family}: saved metrics, full-prefix filtering and simulator callback verified',flush=True)
    summary={'status':'PASSED','forecast_rows':len(records),'metric_rows':len(scores),
             'independent_prefix_filter_checks':filtered_checks,'live_simulator_callback_runs':live_checks,
             'negative_corrections':int(records.negative_correction.sum()),
             'inventory_policy_comparison':'fixed benchmark rerun on Guan inputs; alternative policy comparison pending'}
    (out/'verification.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
