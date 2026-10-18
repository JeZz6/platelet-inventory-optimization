# Simulator and forecasting contract

## Daily event sequence

1. Record opening inventory by remaining usable life.
2. Receive yesterday's due orders using the simulator's supply and shelf-life streams.
3. Pass the sanitized context to the forecast provider, then to the ordering policy, before today's requests are observed.
4. Place a nonnegative integer order that arrives tomorrow.
5. Reveal today's demand, issue first-expiring stock first (FEFO), and record unmet requests.
6. Expire unused life-1 stock, age the remaining stock, and record closing inventory.

Remaining life includes today. An order placed today cannot serve today's demand. No automatic backlog is added. Inventory and pipeline continue across training, validation and test boundaries.

## Interfaces

`simulate(demand, cfg, policy, policy_name="custom", forecast_provider=None)` is defined in `simulator.py`.

`PolicyContext` includes `date`, `scenario`, `available_by_life`, `outstanding_orders`, `history` and optional `forecasts`. Observations end yesterday. Life index zero means one usable day remaining including today. Outstanding orders store nominal ordered quantities, not realized future receipts.

The forecast provider returns a mapping from target-date ISO strings to finite nonnegative point forecasts. The policy returns one nonnegative integer order. Supply randomness belongs to the simulator. Create a fresh stateful provider/policy for each run.

## Planned forecast-dependent heuristic

`Q_t = round_half_up(max(0, F_today + F_tomorrow + b - I - P))`

- `F_today`, `F_tomorrow`: point forecasts from the same start-of-day origin.
- `b`: buffer selected with validation data; no verified service-level guarantee.
- `I`: inventory available after today's receipts.
- `P`: outstanding orders due within the today/tomorrow protection horizon, excluding the order currently being decided.

Under the present one-day lead time, the ordinary pipeline is typically empty after due arrivals are processed. The interface still exposes outstanding orders. An age-aware extension must discount inventory that will expire before it can serve later demand. Forecast sums are expected cumulative demand, not a cumulative quantile.

This formula is a planned heuristic for the next experiment. The current reported inventory outcomes come from fixed ordering. Tests for existing adapters do not establish a completed advanced-model policy comparison or an optimum.

## Metrics

- Forecast MAE: mean absolute difference between predicted and actual requested units.
- Forecast RMSE: square root of mean squared prediction error.
- Fill rate: issued units / requested units within the evaluated window.
- Stockout-day rate: days with unmet demand / evaluated days.
- Wastage: expired units / (opening window inventory + receipts during the window).
- Mean inventory: mean daily closing stock.
- Weighted outcome: `5 x unmet units + expired units`, with assumed nonmonetary weights.
- Report starting and ending stock and ending outstanding nominal orders.

The identities `opening + received = issued + expired + closing` and `requested = issued + unmet` must hold. Compare policies on common demand paths and the simulator's common supply/shelf-life randomness.

