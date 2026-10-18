"""Point forecasts of requested units. No inventory-limited issues are used."""
from dataclasses import dataclass
from typing import Literal
import numpy as np
import pandas as pd

METHODS = ("seasonal_naive", "moving_average_7")


def validate_demand(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "scenario", "units_requested"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Required columns: {sorted(required)}")
    out = frame[list(sorted(required))].copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise")
    if out.isna().any().any() or (out["date"] != out["date"].dt.normalize()).any():
        raise ValueError("Missing values and non-midnight dates are not permitted")
    vals = pd.to_numeric(out["units_requested"], errors="raise")
    if not np.isfinite(vals).all() or (vals < 0).any() or (vals % 1 != 0).any():
        raise ValueError("Demand must be nonnegative integer requested units")
    out["units_requested"] = vals.astype(int)
    out["scenario"] = out["scenario"].astype(str)
    out = out.sort_values(["scenario", "date"]).reset_index(drop=True)
    for name, group in out.groupby("scenario"):
        if group["date"].duplicated().any():
            raise ValueError(f"Duplicate dates in {name}")
        if not (group["date"].diff().dropna() == pd.Timedelta(days=1)).all():
            raise ValueError(f"Missing daily dates in {name}; do not silently impute")
    return out


def predict(history: pd.Series, origin, horizon: int = 2,
            method: Literal["seasonal_naive", "moving_average_7"] = "seasonal_naive") -> np.ndarray:
    """origin is the current day BEFORE its demand. history must end at origin-1.

    Seasonal naive repeats the last observed weekly pattern for any horizon.
    MA7 uses the same last-seven-observation mean for all horizon days;
    it does not use future actuals or recursively insert predictions.
    """
    origin = pd.Timestamp(origin).normalize()
    if horizon < 1 or int(horizon) != horizon:
        raise ValueError("horizon must be a positive integer")
    if len(history) < 7:
        raise ValueError("At least seven observed days required")
    dates = pd.DatetimeIndex(history.index)
    if dates[-1] != origin - pd.Timedelta(days=1) or (dates >= origin).any():
        raise ValueError("History must contain only observations before origin, ending yesterday")
    if dates.has_duplicates or not dates.is_monotonic_increasing or not (dates[1:] - dates[:-1] == pd.Timedelta(days=1)).all():
        raise ValueError("History must be a consecutive daily series")
    values = history.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Invalid demand history")
    if method == "seasonal_naive":
        week = values[-7:]
        return np.asarray([week[h % 7] for h in range(horizon)], dtype=float)
    if method == "moving_average_7":
        return np.full(horizon, values[-7:].mean(), dtype=float)
    raise ValueError(f"Unknown method: {method}")


@dataclass(frozen=True)
class Split:
    start: pd.Timestamp
    validation_start: pd.Timestamp
    test_start: pd.Timestamp
    end_exclusive: pd.Timestamp
    status: str

    def label(self, day) -> str:
        day = pd.Timestamp(day)
        if not self.start <= day < self.end_exclusive:
            raise ValueError("Date outside split")
        return "train" if day < self.validation_start else "validation" if day < self.test_start else "test"

    def as_dict(self) -> dict:
        return {"status": self.status,
                "training": [str(self.start.date()), str((self.validation_start-pd.Timedelta(days=1)).date())],
                "validation": [str(self.validation_start.date()), str((self.test_start-pd.Timedelta(days=1)).date())],
                "final_test": [str(self.test_start.date()), str((self.end_exclusive-pd.Timedelta(days=1)).date())]}


def make_split(dates, fixture: bool = False) -> Split:
    dates = pd.DatetimeIndex(dates)
    start, end = dates.min(), dates.max() + pd.Timedelta(days=1)
    if fixture:
        if len(dates) != 84:
            raise ValueError("Miniature fixture must contain exactly 84 days")
        return Split(start, start+pd.Timedelta(days=42), start+pd.Timedelta(days=63), end,
                     "MINIATURE_FIXTURE_ONLY: 42/21/21 days; not project split")
    if len(dates) < 700:
        raise ValueError("Project workflow needs approximately 24 months (at least 700 days)")
    test_start = end - pd.DateOffset(months=6)
    val_start = test_start - pd.DateOffset(months=3)
    return Split(start, val_start, test_start, end,
                 "Calendar split: last six months test; prior three months validation; earlier training")


def forecast_records(series: pd.Series, scenario: str, split: Split) -> pd.DataFrame:
    records = []
    for origin in series.index:
        part = split.label(origin)
        if part == "train":
            continue
        # Rolling origin: yesterday's actual demand becomes known each day.
        history = series.loc[series.index < origin]
        for method in METHODS:
            estimates = predict(history, origin, 2, method)
            for h, estimate in enumerate(estimates, start=1):
                target = origin + pd.Timedelta(days=h-1)
                # Do not mix validation and test targets or run past data end.
                if target >= split.end_exclusive or split.label(target) != part:
                    continue
                records.append(dict(scenario=scenario, method=method, split=part,
                                    origin_date=origin, history_end=history.index[-1],
                                    target_date=target, horizon_days=h,
                                    units_requested=int(series.loc[target]),
                                    forecast_units=float(estimate)))
    return pd.DataFrame(records)


def error_table(records: pd.DataFrame, by_weekday: bool = False) -> pd.DataFrame:
    data = records.copy()
    keys = ["scenario", "split", "method", "horizon_days"]
    if by_weekday:
        data["weekday"] = pd.to_datetime(data["target_date"]).dt.day_name()
        keys.append("weekday")
    rows = []
    for group_key, group in data.groupby(keys, sort=True):
        errors = group["forecast_units"].to_numpy()-group["units_requested"].to_numpy()
        rows.append(dict(zip(keys, group_key), n=len(group),
                         MAE=float(np.abs(errors).mean()), RMSE=float(np.sqrt(np.mean(errors**2)))))
    return pd.DataFrame(rows)
