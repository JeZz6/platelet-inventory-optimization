"""One modelling contract shared by the demand generator and simulator."""
from dataclasses import dataclass, field
from datetime import date
import json
import math
from numbers import Integral
from pathlib import Path


def count(value, name="quantity"):
    """Reject fractional, negative or Boolean unit counts rather than coerce them."""
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer, got {value!r}")
    return int(value)


def round_units(value):
    """Round a finite nonnegative target to nearest integer, with halves up."""
    if not math.isfinite(value) or value < 0:
        raise ValueError("target must be finite and nonnegative")
    return int(math.floor(value + 0.5))


@dataclass
class Config:
    contract_version: str = "1.0"
    seed: int = 42
    start_date: str = "2024-01-01"
    n_days: int = 730
    train_days: int = 456
    validation_days: int = 91
    scenario_scales: dict = field(default_factory=lambda: {"GuanReference": 1.0})
    scenario_ids: dict = field(default_factory=lambda: {"GuanReference": 0})
    weekday_reference_means: list = field(default_factory=lambda: [37.5, 37.3, 39.2, 37.8, 40.5, 27.2, 28.4])
    cycle_enabled: bool = False
    cycle_period_days: int = 7
    cycle_bump_days: int = 0
    cycle_phase_days: int = 0
    cycle_multiplier: float = 1.0
    lead_time_days: int = 1
    review_period_days: int = 1
    supply_cv: float = .25
    shelf_life_probabilities: list = field(default_factory=lambda: [.05, .10, .20, .25, .40])
    initial_stock_by_life: list = field(default_factory=lambda: [0, 0, 0, 0, 0])
    initial_orders_due_day_zero: list = field(default_factory=list)
    baseline_supply_factor: float = 1.05
    shortage_weight: float = 5.0
    expiry_weight: float = 1.0

    def validate(self):
        if self.contract_version != "1.0":
            raise ValueError("unsupported modelling contract")
        date.fromisoformat(self.start_date)
        for name in ("seed", "n_days", "train_days", "validation_days", "cycle_period_days", "cycle_bump_days", "cycle_phase_days"):
            count(getattr(self, name), name)
        if self.n_days < 1 or self.train_days + self.validation_days >= self.n_days:
            raise ValueError("need positive simulation length and at least one test day")
        if self.lead_time_days != 1 or self.review_period_days != 1:
            raise ValueError("v1 implements exactly one-day lead time and daily review")
        if self.cycle_period_days < 1 or self.cycle_bump_days > self.cycle_period_days:
            raise ValueError("invalid cycle length or bump length")
        if not isinstance(self.cycle_enabled, bool):
            raise ValueError("cycle_enabled must be Boolean")
        if len(self.weekday_reference_means) != 7 or len(self.shelf_life_probabilities) != 5 or len(self.initial_stock_by_life) != 5:
            raise ValueError("expect seven weekday means and five life cohorts")
        numbers = self.weekday_reference_means + self.shelf_life_probabilities + list(self.scenario_scales.values())
        numbers += [self.supply_cv, self.baseline_supply_factor, self.cycle_multiplier, self.shortage_weight, self.expiry_weight]
        if any(not math.isfinite(x) or x < 0 for x in numbers):
            raise ValueError("parameters must be finite and nonnegative")
        if not math.isclose(sum(self.shelf_life_probabilities), 1.0, abs_tol=1e-12):
            raise ValueError("shelf-life probabilities must sum to one")
        if set(self.scenario_scales) != set(self.scenario_ids) or not self.scenario_ids:
            raise ValueError("scenario scales and stable RNG ids must match")
        ids = [count(x, "scenario id") for x in self.scenario_ids.values()]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario RNG ids must be unique")
        for x in self.initial_stock_by_life + self.initial_orders_due_day_zero:
            count(x)
        return self

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text())).validate()

    def save(self, path):
        from dataclasses import asdict
        Path(path).write_text(json.dumps(asdict(self), indent=2) + "\n")
