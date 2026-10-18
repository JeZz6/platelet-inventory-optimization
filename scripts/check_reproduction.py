"""Compare a fresh forecast run with the supplied Guan reference, numerically.

Use after run_project.py, from the repository root. CSV numeric fields allow
rtol=1e-8 and atol=1e-8; dates, keys, eligibility and selected orders must agree.
This checks reproducibility of this reference, not real-world validity.
"""
from pathlib import Path
import argparse
import hashlib
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    actual = args.output_dir
    if not actual.is_absolute():
        actual = ROOT / actual
    reference = ROOT / "results"
    if actual.resolve() == reference.resolve():
        parser.error("Choose independently regenerated outputs, not results itself")

    comparisons = {
        "forecasts.csv": ["scenario", "model", "decision_date", "forecast_horizon"],
        "forecast_accuracy.csv": ["scenario", "method", "split", "horizon_days"],
        "forecast_accuracy_by_weekday.csv": ["scenario", "method", "split", "horizon_days", "weekday"],
        "input_quality.csv": ["scenario"],
    }
    compared = []
    for filename, keys in comparisons.items():
        a = pd.read_csv(reference / filename)
        b = pd.read_csv(actual / filename)
        # Use only existing weekday column names without changing other keys.
        keys = [key for key in keys if key in a.columns]
        a = a.sort_values(keys).reset_index(drop=True)
        b = b.sort_values(keys).reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-8, atol=1e-8)
        compared.append(filename)

    for filename in sorted(reference.glob("selection_frozen_*.json")):
        assert json.loads(filename.read_text()) == json.loads((actual / filename.name).read_text()), filename.name
        compared.append(filename.name)

    audit = json.loads((actual / "verification.json").read_text())
    assert audit["status"] == "PASSED", audit
    assert audit["forecast_rows"] == 2192, audit
    assert audit["metric_rows"] == 16, audit
    assert audit["independent_prefix_filter_checks"] == 6, audit
    assert audit["live_simulator_callback_runs"] == 2, audit

    # Confirm synthesis reproduced the supplied inputs and fixed benchmark.
    original = json.loads((ROOT / "docs/SOURCE_PACKAGE.json").read_text())
    checked = []
    for relative, expected in original["copied_files_sha256"].items():
        if relative.startswith(("inputs/", "baseline/")):
            observed = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            assert observed == expected, f"Synthesis/benchmark changed: {relative}"
            checked.append(relative)

    print(json.dumps({
        "status": "PASSED",
        "comparison": "fresh run against supplied Guan reference",
        "numeric_tolerance": {"rtol": 1e-8, "atol": 1e-8},
        "compared_forecast_files": compared,
        "identical_synthesis_and_benchmark_files": checked,
        "forecast_rows": audit["forecast_rows"],
        "metric_rows": audit["metric_rows"],
    }, indent=2))


if __name__ == "__main__":
    main()
