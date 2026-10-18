"""Generate exogenous requested units. There is no collection/supply column."""
from datetime import date, timedelta
import numpy as np
import pandas as pd
from configuration import Config


def stream(cfg, stream_id, scenario, *extra):
    """Stable scenario ids ensure dictionary/policy iteration order cannot shift RNGs."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(
        [cfg.seed, stream_id, cfg.scenario_ids[scenario], *extra])))


def generate_demand(cfg: Config, scenario: str):
    cfg.validate()
    rng = stream(cfg, 1, scenario)
    start = date.fromisoformat(cfg.start_date)
    rows = []
    for t in range(cfg.n_days):
        d = start + timedelta(days=t)
        phase = (t + cfg.cycle_phase_days) % cfg.cycle_period_days
        active = cfg.cycle_enabled and phase < cfg.cycle_bump_days
        multiplier = cfg.cycle_multiplier if active else 1.0
        mean = cfg.scenario_scales[scenario] * cfg.weekday_reference_means[d.weekday()] * multiplier
        split = "train" if t < cfg.train_days else "validation" if t < cfg.train_days + cfg.validation_days else "test"
        rows.append({"date": d.isoformat(), "scenario": scenario,
                     "day_index": t, "day_of_week": d.strftime("%A"),
                     "weekday_index": d.weekday(), "month": d.month,
                     "cycle_day": phase, "cycle_bump_active": int(active),
                     "split": split, "units_requested": int(rng.poisson(mean)),
                     "generator_mean_units": mean})
    return pd.DataFrame(rows)


def policy_demand_view(frame):
    """Member 3's forecast dataset excludes the generator's latent true mean.

    Calendar cycle features are optional: use them only if a known schedule is
    deliberately assumed. A full offline dataset is NOT a live policy context.
    """
    return frame.drop(columns=["generator_mean_units"]).copy()
