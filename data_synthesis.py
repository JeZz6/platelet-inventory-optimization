"""Generate Guan-calibrated synthetic inputs and rerun the fixed-order benchmark."""
from pathlib import Path
import json,platform
import numpy as np
import pandas as pd
from configuration import Config
from demand import generate_demand,policy_demand_view
from policies import make_baseline,baseline_target
from simulator import simulate,summarize
from experiment import verify_run
ROOT=Path(__file__).resolve().parent

def main():
 cfg=Config.load(ROOT/'config.json')
 for name in ('inputs','baseline'):(ROOT/name).mkdir(exist_ok=True)
 metrics=[];stats=[]
 for scenario in cfg.scenario_ids:
  full=generate_demand(cfg,scenario)
  full.drop(columns=['cycle_day','cycle_bump_active']).to_csv(ROOT/'inputs'/f'generator_audit_{scenario}.csv',index=False)
  # Cycle metadata has no meaning in this reference: exclude it entirely from model input.
  frame=policy_demand_view(full).drop(columns=['cycle_day','cycle_bump_active'])
  frame.to_csv(ROOT/'inputs'/f'forecast_input_{scenario}.csv',index=False)
  assert not full.cycle_bump_active.any()
  assert set(full.generator_mean_units)==set(cfg.weekday_reference_means)
  pd.testing.assert_frame_equal(full,generate_demand(cfg,scenario))
  policy=make_baseline(cfg,scenario)
  result=simulate(frame,cfg,policy,'fixed_daily')
  verify_run(result,frame,cfg)
  for name in ('daily','age_states','pipeline','audits'):
   getattr(result,name).to_csv(ROOT/'baseline'/f'baseline_{scenario}_{name}.csv',index=False)
  for label,a,b in [('full',0,cfg.n_days),('train',0,cfg.train_days),('validation',cfg.train_days,cfg.train_days+cfg.validation_days),('test',cfg.train_days+cfg.validation_days,cfg.n_days)]:
   metrics.append({'fixed_daily_order':policy.quantity,'seed':cfg.seed,**summarize(result,cfg,a,b,label)})
  group=full.groupby(['weekday_index','day_of_week']).units_requested.agg(['count','mean','std','min','max']).reset_index()
  group['source_mean']=cfg.weekday_reference_means;group['source_sd']=[7.3,8.7,8.7,8.1,8.4,6.4,6.6]
  group['assumed_poisson_sd']=np.sqrt(group.source_mean)
  stats.append(group)
 pd.DataFrame(metrics).to_csv(ROOT/'baseline/inventory_metrics.csv',index=False)
 pd.concat(stats).to_csv(ROOT/'inputs/weekday_summary.csv',index=False)
 print(pd.DataFrame(metrics).to_string(index=False))
 print('Synthetic overall mean:',full.units_requested.mean())
 print('Reference weekday average:',sum(cfg.weekday_reference_means)/7)
 print('Fixed order before rounding:',baseline_target(cfg,scenario))

if __name__=='__main__':main()
