"""Member 3 tests in addition to Member 2's unchanged 19 tests."""
from dataclasses import replace
from datetime import date,timedelta
from pathlib import Path
from types import MappingProxyType
import unittest
import numpy as np
import pandas as pd
from configuration import Config
from forecasting import validate_demand,predict
from integration import BaselineProvider,OrderingPolicy,PolicySpec
from experiment import contract_split,load_inputs,baseline_accuracy,run_policy,tune_on_development,verify_run,join_actuals,ROOT
from policies import make_baseline
from simulator import PolicyContext,Observation,OutstandingOrder,simulate,summarize,RandomTape


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.day=date(2025,4,1)
        self.history=tuple(Observation(self.day-timedelta(days=7-i),n,0,0,999,0,0,0)
                           for i,n in enumerate([4,6,5,4,7,2,2]))
        self.ctx=PolicyContext(self.day,"Fixture",(0,0,0,0,0),(),self.history,MappingProxyType({}))
        self.cfg=Config(n_days=56,train_days=21,validation_days=7, scenario_scales={"Fixture": 1.0}, scenario_ids={"Fixture": 0}).validate()
        dates=pd.date_range(self.cfg.start_date,periods=self.cfg.n_days)
        self.frame=pd.DataFrame({"date":dates.strftime("%Y-%m-%d"),"scenario":"Fixture",
                                 "units_requested":[int((i%7)+1) for i in range(self.cfg.n_days)],
                                 "split":["train"]*21+["validation"]*7+["test"]*28})

    def test_supplied_inputs_exact_calendar_and_split(self):
        cfg=Config.load(ROOT/"config.json")
        frames,quality=load_inputs(cfg,ROOT/"inputs")
        split=contract_split(cfg)
        self.assertEqual(str(split.validation_start.date()),"2025-04-01")
        self.assertEqual(str(split.test_start.date()),"2025-07-01")
        self.assertEqual(str((split.end_exclusive-pd.Timedelta(days=1)).date()),"2025-12-30")
        for frame in frames.values():
            self.assertEqual(frame.split.value_counts().to_dict(),{"train":456,"test":183,"validation":91})
        self.assertTrue((quality.invalid_counts==0).all())
        self.assertEqual(int(quality.zero_demand_days.sum()), sum(int((f.units_requested == 0).sum()) for f in frames.values()))

    def test_provider_uses_requested_history_for_both_horizons(self):
        provider=BaselineProvider("seasonal_naive",self.day)
        self.assertEqual(provider(self.ctx),{"2025-04-01":4.0,"2025-04-02":6.0})
        self.assertEqual(provider.records[0]["history_end"],"2025-03-31")

    def test_moving_mean_constant_and_continuous(self):
        values=BaselineProvider("moving_average_7",self.day)(self.ctx)
        self.assertAlmostEqual(values["2025-04-01"],30/7)
        self.assertEqual(values["2025-04-01"],values["2025-04-02"])

    def test_no_provider_before_activation_and_no_same_day_history(self):
        provider=BaselineProvider("seasonal_naive",self.day)
        self.assertEqual(provider(replace(self.ctx,date=self.day-timedelta(days=1))),{})
        bad=replace(self.ctx,history=self.history+(Observation(self.day,100,0,0,0,0,0,0),))
        with self.assertRaises(ValueError):provider(bad)

    def test_input_invalid_counts_duplicates_and_missing_dates(self):
        for frame in [self.frame.assign(units_requested=-1),self.frame.assign(units_requested=.5),self.frame.drop(index=5),pd.concat([self.frame,self.frame.iloc[:1]])]:
            with self.subTest():
                with self.assertRaises(ValueError):validate_demand(frame)

    def test_shared_rounding_is_half_up_not_ceiling(self):
        spec=PolicySpec("historical","historical_base_stock",.6)
        self.assertEqual(OrderingPolicy(spec,3,self.day)(self.ctx),1)
        spec=replace(spec,training_mean=.75)
        self.assertEqual(OrderingPolicy(spec,3,self.day)(self.ctx),2)

    def test_pipeline_only_arrivals_within_protection_horizon(self):
        forecasts={"2025-04-01":4.0,"2025-04-02":6.0}
        spec=PolicySpec("aggregate","forecast_aggregate",3)
        orders=(OutstandingOrder("due",self.day,self.day+timedelta(days=1),3),
                OutstandingOrder("late",self.day,self.day+timedelta(days=2),100))
        ctx=replace(self.ctx,outstanding_orders=orders,forecasts=forecasts)
        self.assertEqual(OrderingPolicy(spec,3,self.day)(ctx),7)

    def test_age_adjustment_discounts_tonight_surplus(self):
        ctx=replace(self.ctx,available_by_life=(100,0,0,0,0),forecasts={"2025-04-01":4.0,"2025-04-02":6.0})
        aggregate=PolicySpec("aggregate","forecast_aggregate",3)
        age=replace(aggregate,name="age",kind="forecast_age_aware")
        self.assertEqual(OrderingPolicy(aggregate,3,self.day)(ctx),0)
        self.assertEqual(OrderingPolicy(age,3,self.day)(ctx),6)
        ctx=replace(ctx,available_by_life=(0,100,0,0,0))
        self.assertEqual(OrderingPolicy(age,3,self.day)(ctx),0)

    def test_policy_does_not_use_trained_mean_before_activation(self):
        policy=OrderingPolicy(PolicySpec("hist","historical_base_stock",100),3,self.day+timedelta(days=1))
        self.assertEqual(policy(self.ctx),3)
        self.assertEqual(policy(replace(self.ctx,date=self.day+timedelta(days=1))),200)

    def test_tuning_rejects_test_rows(self):
        with self.assertRaises(ValueError):tune_on_development(self.frame,self.cfg,buffer_grid=(0,))

    def test_final_test_perturbation_cannot_change_selected_settings(self):
        end=self.cfg.train_days+self.cfg.validation_days
        altered=self.frame.copy();altered.loc[end:,"units_requested"]=999
        a,ca=tune_on_development(self.frame.iloc[:end].copy(),self.cfg,(0,2))
        b,cb=tune_on_development(altered.iloc[:end].copy(),self.cfg,(0,2))
        self.assertEqual(a,b);pd.testing.assert_frame_equal(ca,cb)

    def test_common_warmup_carry_and_reproducibility(self):
        activation=date(2024,1,29);provider_start=date(2024,1,22)
        specifications=[PolicySpec("historical","historical_base_stock",4,buffer_units=2),
                        PolicySpec("aggregate","forecast_aggregate",4,buffer_units=2)]
        results=[]
        for spec in specifications:
            result,_,_=run_policy(self.frame,self.cfg,spec,3,activation,provider_start)
            verify_run(result,self.frame,self.cfg);results.append(result)
        pd.testing.assert_frame_equal(results[0].daily.iloc[:28].drop(columns="policy"),results[1].daily.iloc[:28].drop(columns="policy"))
        self.assertEqual(results[0].audits.opening_stock.iloc[28],results[0].daily.closing_stock.iloc[27])
        metrics=summarize(results[0],self.cfg,28,56,"test")
        self.assertEqual(metrics["starting_inventory"],results[0].daily.closing_stock.iloc[27])
        self.assertEqual(metrics["wastage_denominator_units"],metrics["starting_inventory"]+metrics["units_received"])
        repeated,_,_=run_policy(self.frame,self.cfg,specifications[1],3,activation,provider_start)
        pd.testing.assert_frame_equal(results[1].daily,repeated.daily)

    def test_offline_and_live_forecasts_identical(self):
        _,accuracy,_=baseline_accuracy(self.frame,self.cfg)
        spec=PolicySpec("SN","forecast_aggregate",4)
        result,_,provider=run_policy(self.frame,self.cfg,spec,3,date(2024,1,29),date(2024,1,22))
        live=join_actuals(provider.records,self.frame,self.cfg)
        for part in ("validation","test"):
            for h in (1,2):
                subset=live[(live.decision_split==part)&(live.forecast_horizon==h)&live.included_in_accuracy]
                expected=accuracy[(accuracy.method=="seasonal_naive")&(accuracy.split==part)&(accuracy.horizon_days==h)].iloc[0]
                errors=subset.predicted_units-subset.actual_requested_units
                self.assertEqual(len(subset),expected.n)
                self.assertAlmostEqual(float(abs(errors).mean()),expected.MAE)
        self.assertTrue(pd.isna(live.iloc[-1].actual_requested_units))
        self.assertEqual(live.iloc[-1].target_split,"beyond_data")

    def test_identical_accuracy_dates_and_expected_horizon_counts(self):
        cfg=Config.load(ROOT/"config.json");frames,_=load_inputs(cfg,ROOT/"inputs")
        records,accuracy,_=baseline_accuracy(next(iter(frames.values())),cfg)
        expected={('validation',1):91,('validation',2):90,('test',1):183,('test',2):182}
        for (part,h),n in expected.items():
            frames_by_method=[records[(records.split==part)&(records.horizon_days==h)&(records.method==m)] for m in ("seasonal_naive","moving_average_7")]
            self.assertEqual(len(frames_by_method[0]),n)
            self.assertEqual(frames_by_method[0].target_date.tolist(),frames_by_method[1].target_date.tolist())

    def test_supplied_fixed_baseline_reproduced(self):
        cfg=Config.load(ROOT/"config.json");frames,_=load_inputs(cfg,ROOT/"inputs")
        for scenario,frame in frames.items():
            result=simulate(frame,cfg,make_baseline(cfg,scenario),"fixed_daily")
            reference=pd.read_csv(ROOT/"baseline"/f"baseline_{scenario}_daily.csv")
            pd.testing.assert_frame_equal(result.daily,reference)


if __name__=="__main__":unittest.main()
