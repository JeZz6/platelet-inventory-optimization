"""Member 3 callbacks for the unchanged Member 2 contract v1.0.

Only requested-demand history enters the two baseline forecasts. Generator
means, cycle parameters and private supply randomness are never model inputs.
"""
from dataclasses import dataclass
from datetime import date, timedelta
import math
import pandas as pd
from configuration import round_units
from forecasting import predict


class BaselineProvider:
    def __init__(self, method, activation_date):
        self.method = method
        self.activation_date = activation_date
        self.records = []

    def __call__(self, ctx):
        if ctx.date < self.activation_date:
            return {}
        observed = ctx.history[-7:]
        if len(observed) < 7:
            raise ValueError("Need seven pre-decision observations")
        history = pd.Series([x.units_requested for x in observed],
                            index=pd.DatetimeIndex([x.date for x in observed]), dtype=float)
        values = predict(history, ctx.date, 2, self.method)
        result = {}
        for h, value in enumerate(values):
            target = ctx.date+timedelta(days=h)
            # Existing baselines are nonnegative. This rule is explicit for
            # future models, and applies BEFORE accuracy evaluation.
            corrected = max(0.0, float(value))
            result[target.isoformat()] = corrected
            self.records.append({"scenario":ctx.scenario, "model":self.method,
                                 "decision_date":ctx.date.isoformat(), "target_date":target.isoformat(),
                                 "forecast_horizon":h+1, "history_end":observed[-1].date.isoformat(),
                                 "predicted_units":corrected, "negative_correction":float(value)<0})
        return result


@dataclass(frozen=True)
class PolicySpec:
    name: str
    kind: str
    training_mean: float
    method: str = "seasonal_naive"
    buffer_units: float = 0.0


class OrderingPolicy:
    def __init__(self, spec, fixed_quantity, activation_date):
        self.spec = spec
        self.fixed_quantity = fixed_quantity
        self.activation_date = activation_date
        self.decisions = []

    def __call__(self, ctx):
        if self.spec.kind == "fixed_daily" or ctx.date < self.activation_date:
            quantity = self.fixed_quantity
            self.decisions.append({"date":ctx.date.isoformat(), "scenario":ctx.scenario,
                                   "policy":self.spec.name, "stage":"fixed_benchmark" if self.spec.kind=="fixed_daily" else "common_warmup",
                                   "units_ordered":quantity, "target":None, "inventory_position":None,
                                   "projected_expiry_before_tomorrow":None, "buffer_units":None})
            return quantity
        on_hand = sum(ctx.available_by_life)
        tomorrow = ctx.date+timedelta(days=1)
        # Credited quantities are nominal ordered units, NOT tomorrow's
        # realized receipts. Pipeline normally empties after daily arrivals.
        pipeline = sum(o.units_ordered for o in ctx.outstanding_orders if ctx.date < o.due_date <= tomorrow)
        expiry = 0.0
        if self.spec.kind == "historical_base_stock":
            target = 2*self.spec.training_mean+self.spec.buffer_units
        else:
            f0, f1 = (ctx.forecasts[d.isoformat()] for d in (ctx.date, tomorrow))
            if any(not math.isfinite(v) or v < 0 for v in (f0,f1)):
                raise ValueError("Invalid forecasts")
            target = f0+f1+self.spec.buffer_units
            if self.spec.kind == "forecast_age_aware":
                expiry = max(0.0, ctx.available_by_life[0]-f0)
            elif self.spec.kind != "forecast_aggregate":
                raise ValueError("Unknown target policy")
        position = on_hand+pipeline-expiry
        quantity = round_units(max(0.0,target-position))
        self.decisions.append({"date":ctx.date.isoformat(), "scenario":ctx.scenario,
                               "policy":self.spec.name, "stage":"active",
                               "units_ordered":quantity, "target":target, "inventory_position":position,
                               "projected_expiry_before_tomorrow":expiry, "buffer_units":self.spec.buffer_units})
        return quantity
