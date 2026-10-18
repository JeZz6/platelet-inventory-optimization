"""Small deterministic examples plus reproducibility and interface checks."""
import unittest
from dataclasses import replace, FrozenInstanceError
from datetime import date, timedelta
import numpy as np
import pandas as pd
from configuration import Config, round_units
from demand import generate_demand, policy_demand_view
from policies import FixedDailyPolicy, make_baseline, baseline_target
from simulator import issue_oldest, simulate, summarize, RandomTape, DAILY_COLUMNS


def small_cfg(n=3, **changes):
    return replace(Config(), n_days=n, train_days=0, validation_days=0,
                   supply_cv=0, **changes).validate()


def path(values, cfg):
    first = date.fromisoformat(cfg.start_date)
    return pd.DataFrame({"date": [(first + timedelta(days=t)).isoformat() for t in range(len(values))],
                         "scenario": "GuanReference", "units_requested": values})


class SimulatorTests(unittest.TestCase):
    def test_oldest_first_exact_cohorts(self):
        stock, issued, unmet = issue_oldest([2, 3, 4, 0, 1], 4)
        self.assertEqual(issued.tolist(), [2, 2, 0, 0, 0])
        self.assertEqual(stock.tolist(), [0, 1, 4, 0, 1])
        self.assertEqual(unmet, 0)

    def test_hand_calculated_three_days(self):
        cfg = small_cfg(initial_stock_by_life=[2, 1, 0, 0, 0], shelf_life_probabilities=[0, 0, 0, 0, 1])
        result = simulate(path([1, 2, 1], cfg), cfg, lambda c: 2 if not c.history else 0)
        self.assertEqual(result.daily.units_received.tolist(), [0, 2, 0])
        self.assertEqual(result.daily.units_issued.tolist(), [1, 2, 1])
        self.assertEqual(result.daily.units_expired.tolist(), [1, 0, 0])
        self.assertEqual(result.daily.closing_stock.tolist(), [1, 1, 0])
        closing = result.age_states.query("stage == 'closing_after_expiry_and_age'")
        self.assertEqual(closing.iloc[0][[f"life_{i}" for i in range(1, 6)]].tolist(), [1, 0, 0, 0, 0])
        self.assertEqual(closing.iloc[1][[f"life_{i}" for i in range(1, 6)]].tolist(), [0, 0, 0, 1, 0])

    def test_today_order_cannot_serve_today(self):
        cfg = small_cfg(2, shelf_life_probabilities=[0, 0, 0, 0, 1])
        result = simulate(path([4, 4], cfg), cfg, FixedDailyPolicy(4))
        self.assertEqual(result.daily.units_stockout.tolist(), [4, 0])
        self.assertEqual(result.daily.units_received.tolist(), [0, 4])
        self.assertEqual(len(result.final_outstanding), 1)
        for _, row in result.pipeline.iterrows():
            self.assertEqual(date.fromisoformat(row.due_date) - date.fromisoformat(row.placed_date), timedelta(days=1))

    def test_last_usable_day_is_eligible(self):
        cfg = small_cfg(2, initial_stock_by_life=[2, 0, 0, 0, 0])
        result = simulate(path([1, 1], cfg), cfg, FixedDailyPolicy(0))
        self.assertEqual(result.daily.units_issued.tolist(), [1, 0])
        self.assertEqual(result.daily.units_expired.tolist(), [1, 0])
        self.assertEqual(result.daily.units_stockout.tolist(), [0, 1])

    def test_no_demand_all_initial_stock_eventually_expires(self):
        cfg = small_cfg(5, initial_stock_by_life=[1, 1, 1, 1, 1])
        result = simulate(path([0]*5, cfg), cfg, FixedDailyPolicy(0))
        self.assertEqual(result.daily.units_expired.tolist(), [1]*5)
        self.assertEqual(result.daily.units_issued.sum(), 0)
        summary = summarize(result, cfg)
        self.assertIsNone(summary["fill_rate"])
        self.assertEqual(summary["wastage_fraction"], 1)

    def test_no_supply(self):
        cfg = small_cfg()
        result = simulate(path([1, 0, 2], cfg), cfg, FixedDailyPolicy(0))
        self.assertEqual(result.daily.units_stockout.tolist(), [1, 0, 2])
        self.assertEqual(result.daily.closing_stock.sum(), 0)
        self.assertEqual(result.daily.units_expired.sum(), 0)
        self.assertIsNone(summarize(result, cfg)["wastage_fraction"])

    def test_initial_pipeline_arrives_on_day_zero(self):
        cfg = small_cfg(1, initial_orders_due_day_zero=[3], shelf_life_probabilities=[1, 0, 0, 0, 0])
        result = simulate(path([2], cfg), cfg, FixedDailyPolicy(0))
        self.assertEqual(result.daily.units_received.iloc[0], 3)
        self.assertEqual(result.daily.units_issued.iloc[0], 2)
        self.assertEqual(result.daily.units_expired.iloc[0], 1)

    def test_stock_and_request_conservation_all_scenarios(self):
        cfg = Config().validate()
        for scenario in cfg.scenario_scales:
            result = simulate(generate_demand(cfg, scenario), cfg, make_baseline(cfg, scenario))
            self.assertTrue((result.audits.stock_balance_residual == 0).all())
            self.assertTrue((result.daily.units_requested == result.daily.units_issued + result.daily.units_stockout).all())
            self.assertTrue((result.age_states[[f"life_{i}" for i in range(1, 6)]] >= 0).all().all())
            self.assertEqual(result.daily.columns.tolist(), DAILY_COLUMNS)
            self.assertEqual(summarize(result, cfg)["conservation_residual"], 0)
            self.assertEqual(summarize(result, cfg, cfg.train_days+cfg.validation_days, period="test")["conservation_residual"], 0)

    def test_identical_seed_reproduces_entire_run(self):
        cfg = Config().validate()
        a, b = generate_demand(cfg, "GuanReference"), generate_demand(cfg, "GuanReference")
        pd.testing.assert_frame_equal(a, b)
        r1 = simulate(a, cfg, make_baseline(cfg, "GuanReference"))
        r2 = simulate(b, cfg, make_baseline(cfg, "GuanReference"))
        for name in ("daily", "age_states", "pipeline", "audits"):
            pd.testing.assert_frame_equal(getattr(r1, name), getattr(r2, name))

    def test_scenario_iteration_order_does_not_change_demand(self):
        cfg = Config(scenario_scales={"FixtureA": 1.0, "FixtureB": 1.2}, scenario_ids={"FixtureA": 0, "FixtureB": 1})
        a = {s: generate_demand(cfg, s) for s in cfg.scenario_scales}
        for s in reversed(list(cfg.scenario_scales)):
            pd.testing.assert_frame_equal(a[s], generate_demand(cfg, s))

    def test_policies_share_supply_and_future_shelf_randomness(self):
        cfg = Config()
        a, b = RandomTape(cfg, "GuanReference"), RandomTape(cfg, "GuanReference")
        np.testing.assert_array_equal(a.supply_z, b.supply_z)
        a.receipt_cohorts(1000, 0)
        b.receipt_cohorts(1, 0)
        np.testing.assert_array_equal(a.receipt_cohorts(20, 1), b.receipt_cohorts(20, 1))
        # Prefix coupling: first ten units of a 20-unit arrival share the draws
        # used for a 10-unit arrival. Extra units add nonnegative cohort counts.
        self.assertTrue(np.all(a.receipt_cohorts(20, 4) >= b.receipt_cohorts(10, 4)))
        demand = generate_demand(cfg, "GuanReference")
        r1 = simulate(demand, cfg, FixedDailyPolicy(1))
        r2 = simulate(demand, cfg, FixedDailyPolicy(20))
        np.testing.assert_array_equal(r1.audits.receipt_multiplier, r2.audits.receipt_multiplier)
        np.testing.assert_array_equal(r1.daily.units_requested, r2.daily.units_requested)

    def test_clipping_negative_supply_shock(self):
        cfg = Config()
        tape = RandomTape(cfg, "GuanReference")
        tape.supply_z[0] = -100
        self.assertEqual(tape.receipt_quantity(10, 0), 0)
        self.assertEqual(tape.receipt_cohorts(0, 0).sum(), 0)

    def test_rounding_halves_up(self):
        self.assertEqual([round_units(x) for x in (0, .49, .5, 1.5, 2.5)], [0, 0, 1, 2, 3])

    def test_baseline_joint_weekday_cycle_mean(self):
        cfg = small_cfg(21)
        means = generate_demand(cfg, "GuanReference").generator_mean_units
        self.assertAlmostEqual(baseline_target(cfg, "GuanReference"), cfg.baseline_supply_factor*means.mean())
        self.assertAlmostEqual(baseline_target(cfg, "GuanReference"), 37.185)

    def test_policy_and_forecasts_cannot_see_current_or_future_demand(self):
        cfg = small_cfg()
        seen = []
        def provider(ctx):
            self.assertTrue(all(o.date < ctx.date for o in ctx.history))
            self.assertFalse(hasattr(ctx, "units_requested"))
            self.assertFalse(hasattr(ctx, "generator_mean_units"))
            return {ctx.date.isoformat(): 7.0}
        def policy(ctx):
            seen.append([o.units_requested for o in ctx.history])
            self.assertEqual(ctx.forecasts[ctx.date.isoformat()], 7.0)
            with self.assertRaises(TypeError):
                ctx.forecasts["x"] = 1
            with self.assertRaises(FrozenInstanceError):
                ctx.date = date.today()
            return 0
        simulate(path([3, 2, 9], cfg), cfg, policy, forecast_provider=provider)
        self.assertEqual(seen, [[], [3], [3, 2]])

    def test_future_demand_changes_cannot_change_earlier_decisions(self):
        cfg = small_cfg()
        def policy(ctx):
            return sum(o.units_requested for o in ctx.history)
        a = simulate(path([1, 2, 3], cfg), cfg, policy)
        b = simulate(path([1, 2, 300], cfg), cfg, policy)
        self.assertEqual(a.daily.units_ordered.tolist(), b.daily.units_ordered.tolist())

    def test_cycle_definition_and_disable(self):
        cfg = small_cfg(22, cycle_enabled=True, cycle_period_days=21, cycle_bump_days=4, cycle_multiplier=1.6)
        a = generate_demand(cfg, "GuanReference")
        self.assertEqual(a.cycle_bump_active.tolist(), [1]*4 + [0]*17 + [1])
        b = generate_demand(replace(cfg, cycle_enabled=False), "GuanReference")
        self.assertEqual(b.cycle_bump_active.sum(), 0)
        expected = [cfg.scenario_scales["GuanReference"]*cfg.weekday_reference_means[i] for i in b.weekday_index]
        np.testing.assert_allclose(b.generator_mean_units, expected)
        self.assertNotIn("generator_mean_units", policy_demand_view(a).columns)

    def test_bad_orders_and_inputs_fail(self):
        cfg = small_cfg()
        for bad in (-1, 1.5, True, float("nan")):
            with self.assertRaises(ValueError):
                simulate(path([0]*3, cfg), cfg, lambda c: bad)
        with self.assertRaises(ValueError):
            simulate(path([1.5]*3, cfg), cfg, FixedDailyPolicy(0))
        with self.assertRaises(ValueError):
            replace(cfg, lead_time_days=0).validate()
        with self.assertRaises(ValueError):
            replace(cfg, shelf_life_probabilities=[.2]*4+[.3]).validate()
        with self.assertRaises(ValueError):
            simulate(path([0]*3, cfg).iloc[::-1], cfg, FixedDailyPolicy(0))

    def test_split_calendar_boundaries(self):
        df = generate_demand(Config(), "GuanReference")
        self.assertEqual(df.groupby("split").size().to_dict(), {"test": 183, "train": 456, "validation": 91})
        self.assertEqual(df.iloc[-1].date, "2025-12-30")
        self.assertEqual(df.iloc[456].date, "2025-04-01")
        self.assertEqual(df.iloc[547].date, "2025-07-01")


if __name__ == "__main__":
    unittest.main()
