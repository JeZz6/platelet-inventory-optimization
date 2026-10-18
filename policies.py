"""Baseline ordering policy. Supply uncertainty belongs to the simulator."""
from dataclasses import dataclass
from datetime import date
from math import lcm
import numpy as np
from configuration import round_units


def baseline_target(cfg, scenario):
    # A priori long-run reference mean, never the mean of realized test demand.
    # A 21-day cycle stays aligned with weekdays. Average products over the
    # joint calendar period, rather than incorrectly multiply separate means.
    period = lcm(7, cfg.cycle_period_days) if cfg.cycle_enabled else 7
    weekday_start = date.fromisoformat(cfg.start_date).weekday()
    means = []
    for t in range(period):
        active = cfg.cycle_enabled and (t+cfg.cycle_phase_days) % cfg.cycle_period_days < cfg.cycle_bump_days
        multiplier = cfg.cycle_multiplier if active else 1.0
        means.append(cfg.scenario_scales[scenario] * cfg.weekday_reference_means[(weekday_start+t) % 7] * multiplier)
    return cfg.baseline_supply_factor * float(np.mean(means))


@dataclass
class FixedDailyPolicy:
    quantity: int

    def __call__(self, context):
        return self.quantity


def make_baseline(cfg, scenario):
    return FixedDailyPolicy(round_units(baseline_target(cfg, scenario)))
