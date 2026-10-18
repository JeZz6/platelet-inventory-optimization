"""Daily pooled-demand inventory loop, with explicit snapshots and accounting."""
from dataclasses import dataclass, replace
from datetime import date, timedelta
from types import MappingProxyType
from typing import Callable, Mapping
import math
import numpy as np
import pandas as pd
from configuration import Config, count, round_units
from demand import stream

DAILY_COLUMNS = ["date", "scenario", "policy", "day_of_week", "units_requested",
                 "units_ordered", "units_received", "units_issued", "units_stockout",
                 "units_expired", "closing_stock"]


@dataclass(frozen=True)
class OutstandingOrder:
    order_id: str
    placed_date: date
    due_date: date
    units_ordered: int


@dataclass(frozen=True)
class Observation:
    date: date
    units_requested: int
    units_ordered: int
    units_received: int
    units_issued: int
    units_stockout: int
    units_expired: int
    closing_stock: int


@dataclass(frozen=True)
class PolicyContext:
    """Life index 0 = one usable day remaining INCLUDING the current day.

    History ends yesterday. Outstanding quantities are ordered amounts, not
    realized future receipts. Forecast values are optional point forecasts by
    target-date ISO string. A quantile extension must state levels separately.
    """
    date: date
    scenario: str
    available_by_life: tuple[int, ...]
    outstanding_orders: tuple[OutstandingOrder, ...]
    history: tuple[Observation, ...]
    forecasts: Mapping[str, float]


@dataclass
class SimulationResult:
    daily: pd.DataFrame
    age_states: pd.DataFrame
    pipeline: pd.DataFrame
    audits: pd.DataFrame
    final_outstanding: tuple[OutstandingOrder, ...]


class RandomTape:
    """Exogenous randomness indexed by day, never exposed to ordering policies.

    Stream 2 pre-generates one standard-normal shock per ARRIVAL date.
    Stream 3 restarts with [seed, 3, scenario_id, day_index] for each arrival
    date. Same-date unit positions share uniforms across policies. A bigger
    receipt today cannot change shelf draws for any later date.
    """
    def __init__(self, cfg, scenario):
        self.cfg = cfg
        self.scenario = scenario
        self.supply_z = stream(cfg, 2, scenario).standard_normal(cfg.n_days)

    def multiplier(self, day_index):
        return max(0.0, 1.0 + self.cfg.supply_cv * float(self.supply_z[day_index]))

    def receipt_quantity(self, ordered, day_index):
        return round_units(ordered * self.multiplier(day_index))

    def receipt_cohorts(self, received, day_index):
        # One uniform per unit is converted to its remaining life at arrival.
        uniforms = stream(self.cfg, 3, self.scenario, day_index).random(received)
        cdf = np.cumsum(self.cfg.shelf_life_probabilities)
        cdf[-1] = 1.0
        positions = np.searchsorted(cdf, uniforms, side="right")
        return np.bincount(positions, minlength=5).astype(np.int64)

    def audit_frame(self):
        start = date.fromisoformat(self.cfg.start_date)
        return pd.DataFrame({
            "date": [(start + timedelta(days=t)).isoformat() for t in range(self.cfg.n_days)],
            "scenario": self.scenario,
            "arrival_day_index": range(self.cfg.n_days),
            "supply_standard_normal": self.supply_z,
            "supply_multiplier": [self.multiplier(t) for t in range(self.cfg.n_days)],
            "shelf_stream_id": 3,
            "seed": self.cfg.seed,
            "scenario_rng_id": self.cfg.scenario_ids[self.scenario]})


def issue_oldest(stock, requested):
    """Return surviving cohorts and cohort issues. Only life 1..5 exists."""
    stock = np.array([count(x, "cohort stock") for x in stock], dtype=np.int64)
    if len(stock) != 5:
        raise ValueError("expect five life cohorts")
    remaining = count(requested, "requested units")
    issued = np.zeros(5, dtype=np.int64)
    for i in range(5):
        issued[i] = min(int(stock[i]), remaining)
        stock[i] -= issued[i]
        remaining -= int(issued[i])
    return stock, issued, remaining


def simulate(demand, cfg: Config, policy: Callable[[PolicyContext], int],
             policy_name="custom", forecast_provider=None):
    """Policy runs after arrivals and BEFORE reading today's requested quantity.

    Start a fresh policy object for each comparison run if it has mutable state.
    Only the sanitized PolicyContext is passed to a forecast_provider.
    """
    cfg.validate()
    required = {"date", "scenario", "units_requested"}
    if not required.issubset(demand.columns) or len(demand) != cfg.n_days:
        raise ValueError("demand must have required columns and exactly n_days rows")
    frame = demand.reset_index(drop=True)
    start = date.fromisoformat(cfg.start_date)
    expected_dates = [(start + timedelta(days=t)).isoformat() for t in range(cfg.n_days)]
    if frame.date.tolist() != expected_dates or frame.scenario.nunique() != 1:
        raise ValueError("demand must be one scenario on the configured contiguous calendar")
    scenario = frame.scenario.iloc[0]
    if scenario not in cfg.scenario_ids:
        raise ValueError("unknown scenario")
    # Validate units up front. Never truncate user-supplied fractional demand.
    for x in frame.units_requested.tolist():
        count(x, "requested units")
    tape = RandomTape(cfg, scenario)
    stock = np.array(cfg.initial_stock_by_life, dtype=np.int64)
    pipeline = [OutstandingOrder(f"initial_{i}", start - timedelta(days=1), start, q)
                for i, q in enumerate(cfg.initial_orders_due_day_zero)]
    daily, states, pipeline_rows, audits, history = [], [], [], [], []

    def snapshot(d, stage, vector):
        states.append({"date": d.isoformat(), "scenario": scenario, "policy": policy_name,
                       "stage": stage, **{f"life_{i+1}": int(x) for i, x in enumerate(vector)}})

    def pipeline_event(d, event, order, received=None):
        pipeline_rows.append({"date": d.isoformat(), "scenario": scenario, "policy": policy_name,
                              "event": event, "order_id": order.order_id,
                              "placed_date": order.placed_date.isoformat(), "due_date": order.due_date.isoformat(),
                              "units_ordered": order.units_ordered, "units_received": received})

    for t in range(cfg.n_days):
        d = start + timedelta(days=t)
        opening = int(stock.sum())
        snapshot(d, "opening_before_receipts", stock)
        due = [o for o in pipeline if o.due_date == d]
        if any(o.due_date < d for o in pipeline):
            raise AssertionError("overdue pipeline order")
        pipeline = [o for o in pipeline if o.due_date != d]
        received = 0
        # A common day shock affects all orders arriving that day. Rounding is
        # per order. Shelf samples are pooled across the day's actual receipts.
        for o in due:
            if o.due_date - o.placed_date != timedelta(days=1):
                raise AssertionError("lead-time violation")
            receipt = tape.receipt_quantity(o.units_ordered, t)
            received += receipt
            pipeline_event(d, "received", o, receipt)
        cohorts = tape.receipt_cohorts(received, t)
        snapshot(d, "receipts", cohorts)
        stock += cohorts
        snapshot(d, "available_at_decision", stock)
        ctx = PolicyContext(d, scenario, tuple(int(x) for x in stock), tuple(pipeline),
                            tuple(history), MappingProxyType({}))
        if forecast_provider is not None:
            forecasts = dict(forecast_provider(ctx))
            for target, value in forecasts.items():
                if date.fromisoformat(target) < d or not math.isfinite(value) or value < 0:
                    raise ValueError("forecasts need current/future ISO dates and finite nonnegative values")
            ctx = replace(ctx, forecasts=MappingProxyType(forecasts))
        ordered = count(policy(ctx), "policy order")
        if ordered:
            order = OutstandingOrder(f"day_{t}", d, d + timedelta(days=1), ordered)
            pipeline.append(order)
            pipeline_event(d, "placed", order)

        requested = count(frame.units_requested.iloc[t], "requested units")
        stock, by_life_issued, shortage = issue_oldest(stock, requested)
        issued = int(by_life_issued.sum())
        snapshot(d, "issued", by_life_issued)
        snapshot(d, "after_issue_before_expiry", stock)
        expired = int(stock[0])  # Life 1 expires only after today's demand.
        stock = np.concatenate([stock[1:], np.zeros(1, dtype=np.int64)])
        closing = int(stock.sum())
        snapshot(d, "closing_after_expiry_and_age", stock)
        conservation = opening + received - issued - expired - closing
        request_balance = requested - issued - shortage
        if conservation != 0 or request_balance != 0 or np.any(stock < 0):
            raise AssertionError("inventory/request accounting failed")
        audits.append({"date": d.isoformat(), "scenario": scenario, "policy": policy_name,
                       "opening_stock": opening, "stock_balance_residual": conservation,
                       "request_balance_residual": request_balance,
                       "receipt_multiplier": tape.multiplier(t),
                       "outstanding_ordered_units_at_close": sum(o.units_ordered for o in pipeline)})
        for o in pipeline:
            pipeline_event(d, "outstanding_at_end", o)
        daily.append(dict(zip(DAILY_COLUMNS, [d.isoformat(), scenario, policy_name, d.strftime("%A"),
                                              requested, ordered, received, issued, shortage, expired, closing])))
        history.append(Observation(d, requested, ordered, received, issued, shortage, expired, closing))

    pipeline_columns = ["date", "scenario", "policy", "event", "order_id", "placed_date", "due_date", "units_ordered", "units_received"]
    pipeline_frame = pd.DataFrame(pipeline_rows, columns=pipeline_columns)
    pipeline_frame["units_received"] = pipeline_frame.units_received.astype("Int64")
    return SimulationResult(pd.DataFrame(daily, columns=DAILY_COLUMNS), pd.DataFrame(states),
                            pipeline_frame, pd.DataFrame(audits), tuple(pipeline))


def summarize(result, cfg, start_index=0, end_index=None, period="full"):
    """Window uses [start_index, end_index). State carries across boundaries."""
    end_index = cfg.n_days if end_index is None else end_index
    if not 0 <= start_index < end_index <= cfg.n_days:
        raise ValueError("invalid evaluation window")
    df = result.daily.iloc[start_index:end_index]
    initial = int(result.audits.opening_stock.iloc[start_index])
    requested, received, issued, shortage, expired = [int(df[x].sum()) for x in
        ["units_requested", "units_received", "units_issued", "units_stockout", "units_expired"]]
    denominator = initial + received
    ending = int(df.closing_stock.iloc[-1])
    outstanding = int(result.audits.outstanding_ordered_units_at_close.iloc[end_index-1])
    if initial + received != issued + expired + ending:
        raise AssertionError("window conservation failed")
    return {"scenario": df.scenario.iloc[0], "policy": df.policy.iloc[0], "period": period,
            "start_date": df.date.iloc[0], "end_date_inclusive": df.date.iloc[-1], "days": len(df),
            "units_requested": requested, "units_ordered": int(df.units_ordered.sum()),
            "units_received": received, "units_issued": issued, "units_stockout": shortage,
            "units_expired": expired, "fill_rate": issued/requested if requested else None,
            "stockout_day_rate": float((df.units_stockout > 0).mean()),
            "wastage_fraction": expired/denominator if denominator else None,
            "wastage_denominator_units": denominator,
            "mean_closing_stock": float(df.closing_stock.mean()),
            "mean_daily_requested": requested/len(df),
            "weighted_shortage_expiry": cfg.shortage_weight*shortage + cfg.expiry_weight*expired,
            "starting_inventory": initial, "ending_inventory": ending,
            "ending_outstanding_ordered_units": outstanding,
            "conservation_residual": initial + received - issued - expired - ending}
