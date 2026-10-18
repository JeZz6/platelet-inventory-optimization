"""Causal point-forecast ARIMA/SARIMA adapters for Member 2 contract v1.0."""
from dataclasses import dataclass, asdict
from datetime import timedelta
import warnings
import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX


@dataclass(frozen=True)
class ModelSpec:
    family: str
    order: tuple
    seasonal_order: tuple = (0, 0, 0, 0)

    @property
    def trend(self):
        return 'c' if self.order[1] + self.seasonal_order[1] == 0 else 'n'

    @property
    def key(self):
        return f'{self.family}{self.order}x{self.seasonal_order}'

    def settings(self):
        return {**asdict(self), 'trend': self.trend, 'key': self.key}


# Declared before running final evaluation. This is a limited search, not auto-ARIMA.
ARIMA_GRID = tuple(ModelSpec('ARIMA', (p,d,q))
                   for d in (0,1) for p in (0,1,2) for q in (0,1,2))
SARIMA_GRID = tuple(ModelSpec('SARIMA', order, seasonal)
                    for order in ((0,0,0),(1,0,0),(0,0,1),(1,0,1),(0,1,1),(1,1,0))
                    for seasonal in ((1,0,0,7),(0,0,1,7),(1,0,1,7),(0,1,1,7),(1,1,0,7)))


def check_history(series):
    if not isinstance(series.index, pd.DatetimeIndex) or len(series) < 28:
        raise ValueError('At least 28 daily observations with datetime index required')
    dates = series.index
    if dates.has_duplicates or not dates.is_monotonic_increasing or not (dates[1:]-dates[:-1] == pd.Timedelta(days=1)).all():
        raise ValueError('History must be consecutive and chronological')
    y = series.to_numpy(dtype=float)
    if not np.isfinite(y).all() or (y < 0).any() or (y % 1 != 0).any():
        raise ValueError('Observed requests must be nonnegative integer units')


def fit_model(series, spec):
    check_history(series)
    daily = pd.Series(series.to_numpy(dtype=float), index=pd.date_range(series.index[0], periods=len(series), freq='D'))
    model = SARIMAX(daily, order=spec.order, seasonal_order=spec.seasonal_order,
                    trend=spec.trend, enforce_stationarity=True, enforce_invertibility=True,
                    simple_differencing=False)
    messages = []
    # A deterministic retry is allowed for optimizer convergence, not based on test errors.
    for maxiter in (200, 1000):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            result = model.fit(disp=False, maxiter=maxiter)
        messages.extend(str(w.message) for w in caught)
        if result.mle_retvals.get('converged', False) and np.isfinite(result.params).all():
            return result, {'converged': True, 'maxiter': maxiter, 'warnings': list(dict.fromkeys(messages)),
                            'aic': float(result.aic), 'params': {str(k): float(v) for k,v in result.params.items()},
                            'training_end': str(series.index[-1].date()), 'training_n': len(series)}
    raise RuntimeError(f'Nonconverged fit: {spec.key}; warnings={messages}')


class FittedForecaster:
    """Parameters fixed; filter state extends with requests known before decision.

    Forecast before observe. Updating only through yesterday also supports skipped
    decision days. The same adapter serves offline evaluation and live simulator use.
    """
    def __init__(self, fit_history, spec):
        self.spec = spec
        self.result, self.fit_info = fit_model(fit_history, spec)
        self.fit_end = fit_history.index[-1]
        self.last_observed = self.fit_end
        self.known = fit_history.astype(float).copy()

    def predict(self, history, decision_date):
        check_history(history)
        decision = pd.Timestamp(decision_date)
        if history.index[-1] != decision-pd.Timedelta(days=1) or (history.index >= decision).any():
            raise ValueError('History must end yesterday and contain no current/future demand')
        if decision <= self.fit_end or history.index[-1] < self.last_observed:
            raise ValueError('Fitted information unavailable or dates moved backwards')
        overlap = self.known.index.intersection(history.index)
        if not self.known.loc[overlap].equals(history.loc[overlap].astype(float)):
            raise ValueError('Past observations changed')
        new = history.loc[history.index > self.last_observed].astype(float)
        if len(new):
            if new.index[0] != self.last_observed+pd.Timedelta(days=1):
                raise ValueError('Missing state-update observations')
            self.result = self.result.extend(new.asfreq('D'))
            self.known = pd.concat([self.known, new])
            self.last_observed = new.index[-1]
        raw = np.asarray(self.result.forecast(steps=2), dtype=float)
        if raw.shape != (2,) or not np.isfinite(raw).all():
            raise RuntimeError('Invalid point forecast')
        return raw, np.maximum(0.0, raw)


class AdvancedProvider:
    """Member 2 callback: returns ISO target-date point forecasts, no policy randomness."""
    def __init__(self, fit_history, spec, activation_date):
        self.forecaster = FittedForecaster(fit_history, spec)
        self.activation_date = activation_date
        if pd.Timestamp(activation_date) <= self.forecaster.fit_end:
            raise ValueError('Cannot activate before fit data are available')
        self.records = []

    def __call__(self, ctx):
        if ctx.date < self.activation_date:
            return {}
        history = pd.Series([x.units_requested for x in ctx.history],
                            index=pd.DatetimeIndex([x.date for x in ctx.history]), dtype=float)
        raw, corrected = self.forecaster.predict(history, ctx.date)
        values = {}
        for h in (1,2):
            target = ctx.date+timedelta(days=h-1)
            values[target.isoformat()] = float(corrected[h-1])
            self.records.append({'scenario': ctx.scenario, 'model': self.forecaster.spec.family,
                                 'decision_date': ctx.date.isoformat(), 'target_date': target.isoformat(),
                                 'forecast_horizon': h, 'history_end': history.index[-1].date().isoformat(),
                                 'fit_end': self.forecaster.fit_end.date().isoformat(),
                                 'raw_predicted_units': float(raw[h-1]), 'predicted_units': float(corrected[h-1]),
                                 'negative_correction': bool(raw[h-1] < 0)})
        return values
