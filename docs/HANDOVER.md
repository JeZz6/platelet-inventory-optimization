# GitHub repository handover

Prepared 18 October 2026 from the existing `Guan_Local_Project.zip` and its saved results. The original archive and its digest are recorded in SOURCE_PACKAGE.json. Original modelling scripts, tests, configuration and saved reference outputs were copied without scientific changes.

## Completed in the research package

- One 730-day Guan-mean-calibrated synthetic demand reference, seed 42.
- Seasonal naive, MA7, ARIMA and weekly SARIMA forecasting with chronological selection and final testing.
- Fixed-order age-structured inventory simulation and period-specific metrics.
- Forty existing code tests and an independent saved-forecast audit.
- 2,192 forecast records, 16 metric rows, six full-prefix filtering checks and two simulator callback runs for the current reference.

## Added for GitHub

- A project README with installation, execution, actual reference results and limitations.
- Git ignore rules, line-ending rules and Python-version guidance.
- This handover, explicit assumptions and a simulator/forecasting contract.
- GitHub Actions for tests and saved-result auditing, with optional full reproduction.
- A numerical comparison script for fresh forecast results.
- Fresh local verification logs and repository-integrity checks.

## Model and simulator changes

No forecasting algorithm, candidate grid, split, simulator event, supply model, shelf-life rule or metric definition was changed during repository preparation. The older Low/Mid/High results are not included as current evidence. The root README supersedes the original package README for repository navigation; the original is retained in ORIGINAL_PACKAGE_README.md.

## Remaining work

- Publish to the user's selected GitHub repository once account access is connected.
- Run the hosted GitHub Actions workflow after publication; local checks do not establish hosted CI success.
- Select forecast-dependent buffers with validation data and compare policies fairly.
- Complete explicit age-aware advanced-model policy experiments.
- Evaluate independent seeds and demand-dispersion sensitivity.
- Validate with actual hospital data if available.

The included plot is a supplied reference figure. The complete pipeline regenerates numerical outputs; it does not regenerate that static plot. The optional notebook needs a notebook environment in addition to the core requirements.

