# Guan platelet project: synthesis and forecasting

Download and extract the ZIP. Keep all files together. The package works in Windows, macOS and Linux with Python 3.12. Open a terminal in the extracted Guan_Local_Project directory.

## Install and run

```text
python -m pip install -r requirements.txt
python run_project.py
```

If Windows calls Python `py`, use `py -3.12` in place of `python`. The runner generates 730 synthetic days, reruns the fixed-order benchmark, compares seasonal naive/MA7/ARIMA/SARIMA, audits forecasts, and executes the 40 tests. It chooses single-thread numerical settings for consistent fitting. The complete forecast search can take several minutes.

## Run the two main parts separately

```text
python data_synthesis.py
python forecast_models.py --output-dir my_forecast_results
python verify_advanced.py --output-dir my_forecast_results
python -m unittest discover -s tests -v
```

Choose a new/empty forecast output directory every time. A second full run can use `python run_project.py --output-dir local_results_2`. The synthesis step regenerates the deterministic input and baseline files using config.json. Save those folders elsewhere before changing the seed or configuration if you want to preserve them.

## Main files

- data_synthesis.py: synthesis entry point plus fixed-order benchmark export.
- demand.py: random streams and weekday Poisson demand generation.
- forecast_models.py: chronological model search and final evaluation.
- advanced_forecasting.py: ARIMA/SARIMA grids, fitting and causal state updates.
- forecasting.py: seasonal naive, MA7, data validation and error metrics.
- config.json and configuration.py: current Guan reference values; class defaults also use Guan.
- simulator.py, policies.py and integration.py: unchanged inventory equations and policy interfaces.
- verify_advanced.py and tests/: independent forecast auditing and 40 automated checks.
- source_reference.json: numerical provenance and limitations.

## Outputs

inputs/forecast_input_GuanReference.csv is the data to share with the forecasting member. It contains dates, simulated requested counts and labels, without generator means or cycle features. inputs/generator_audit_GuanReference.csv additionally includes the true configured mean for audit; never give its mean column to forecasting models. inputs/weekday_summary.csv compares generated summaries with published means/SDs.

baseline/ contains fixed-order metrics, daily inventory, age cohorts, pipeline and conservation checks. The generated forecast directory contains raw forecasts, MAE/RMSE, validation search, frozen selections, fitted settings, residual diagnostics and audit summary.

results/ contains the new verified execution of this cleaned package. Use a different directory to preserve it. It reproduces the prior Guan forecast errors and fixed-order inventory outcomes. execution.log and test_results.txt record validation. The notebook is optional and runs the same scripts.

## Scientific boundaries

Source: Guan et al. (2017), PNAS, Table S3, DOI 10.1073/pnas.1714097114. The source records transfused units. Synthetic requested units use its weekday means as a proxy. Scale 1.0, seed 42, no imposed surge. Conditional Poisson draws are an assumption and do not reproduce the larger published SDs. These are newly generated synthetic observations, not hospital records.

Only one synthetic seed is evaluated. SARIMA wins forecast accuracy for this reference; inventory-policy comparisons remain future work. The fixed order is 37 units/day using an assumed 5% margin. The receipt CV, shelf-life probabilities, review interval and lead time remain disclosed simulator assumptions.

The general engine retains an optional cycle switch for possible future sensitivity tests, with the current configuration disabled (bump days zero and multiplier one). A unit test uses an artificial cycle only to check that the generic switch works; it does not enter the reference experiment. Small test fixtures can have labels such as Fixture without representing a project demand scenario.
