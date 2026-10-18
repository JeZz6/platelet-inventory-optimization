"""Meaningful temporal and simulator-contract checks for fitted forecasters."""
import unittest
from datetime import date
from types import SimpleNamespace
import numpy as np
import pandas as pd
from advanced_forecasting import ModelSpec, FittedForecaster, AdvancedProvider
from forecast_models import rolling_records, accuracy, select_on_development
from configuration import Config


def fixture():
    dates=pd.date_range('2024-01-01',periods=90,freq='D')
    values=np.random.default_rng(70).poisson(4.0,90)
    return pd.Series(values,index=dates)


class AdvancedTests(unittest.TestCase):
    def test_future_actual_does_not_change_today_or_tomorrow_prediction(self):
        y=fixture();fit=y.iloc[:60];spec=ModelSpec('ARIMA',(1,0,0))
        base,_=rolling_records(y.iloc[60:65],fit,spec,'Fixture','validation')
        altered=y.iloc[60:65].copy();altered.iloc[0]=999
        changed,_=rolling_records(altered,fit,spec,'Fixture','validation')
        np.testing.assert_allclose(base.predicted_units.iloc[:2],changed.predicted_units.iloc[:2])
        self.assertFalse(np.allclose(base.predicted_units.iloc[2:4],changed.predicted_units.iloc[2:4]))

    def test_cannot_predict_before_fit_available_or_use_today(self):
        y=fixture();f=FittedForecaster(y.iloc[:60],ModelSpec('ARIMA',(1,0,0)))
        with self.assertRaises(ValueError):f.predict(y.iloc[:59],y.index[59])
        with self.assertRaises(ValueError):f.predict(y.iloc[:61],y.index[60])

    def test_live_provider_matches_offline_for_two_horizons(self):
        y=fixture();spec=ModelSpec('SARIMA',(0,0,0),(1,0,0,7))
        offline,_=rolling_records(y.iloc[60:65],y.iloc[:60],spec,'Fixture','validation')
        provider=AdvancedProvider(y.iloc[:60],spec,y.index[60].date())
        self.assertEqual(provider(SimpleNamespace(date=y.index[59].date())),{})
        values=[]
        for i in range(60,65):
            ctx=SimpleNamespace(date=y.index[i].date(),scenario='Fixture',history=tuple(
                SimpleNamespace(date=d.date(),units_requested=int(v)) for d,v in y.iloc[:i].items()))
            forecasts=provider(ctx)
            self.assertEqual(len(forecasts),2)
            values.extend(forecasts.values())
        np.testing.assert_allclose(values,offline.predicted_units,rtol=1e-10,atol=1e-10)

    def test_missing_dates_invalid_counts_and_revised_past_rejected(self):
        y=fixture();spec=ModelSpec('ARIMA',(0,0,0))
        for bad in (y.iloc[:60].drop(y.index[5]), y.iloc[:60].astype(float)+.1):
            with self.assertRaises(ValueError):FittedForecaster(bad,spec)
        f=FittedForecaster(y.iloc[:60],spec);bad=y.iloc[:60].copy();bad.iloc[2]+=1
        with self.assertRaises(ValueError):f.predict(bad,y.index[60])

    def test_metrics_exclude_last_unobserved_tomorrow_and_keep_zeros(self):
        y=fixture();y.iloc[60]=0
        rows,_=rolling_records(y.iloc[60:65],y.iloc[:60],ModelSpec('ARIMA',(0,0,0)),'Fixture','validation')
        scores=accuracy(rows).set_index('horizon_days')
        self.assertEqual(scores.loc[1,'n'],5);self.assertEqual(scores.loc[2,'n'],4)
        self.assertEqual(rows.actual_requested_units.iloc[0],0)
        self.assertTrue((rows.predicted_units>=0).all())

    def test_selection_rejects_test_length(self):
        cfg=Config.load('config.json')
        with self.assertRaises(ValueError):select_on_development(fixture(),cfg,'Fixture',None)


if __name__=='__main__':unittest.main()
