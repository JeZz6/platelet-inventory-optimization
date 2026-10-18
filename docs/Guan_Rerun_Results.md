# Guan reference rerun — actual results

Completed 8 October 2026. This replaces the earlier Farrington-calibrated Low/Mid/High results for the main reference experiment. Original packages were preserved.

## What changed

The generator now uses the weekday platelet-transfusion means in Guan et al. (2017), Table S3: Monday 37.5, Tuesday 37.3, Wednesday 39.2, Thursday 37.8, Friday 40.5, Saturday 27.2, Sunday 28.4 units. Scale is 1.0. The imposed 21-day surge is disabled. All forecasting methods, candidate grids, chronological splits, inventory mechanics, and other numerical assumptions are retained.

Source: Guan et al., *Big data modeling to predict platelet usage and minimize wastage in a tertiary care system*, PNAS 114(43), 11368–11373. DOI: https://doi.org/10.1073/pnas.1714097114 . Table S3: https://pmc.ncbi.nlm.nih.gov/articles/PMC5664553/ . PNAS SCIE status is identified by its publisher: https://academic.oup.com/pnasnexus/pages/submitting-to-the-pnas-portfolio . This is PNAS, not PNAS Nexus. Indexing of the source does not make this synthetic dataset an observed clinical dataset.

**Data boundary:** the published observations are transfused units. We use their weekday means as a proxy to generate simulated requested units; unfulfilled requests cannot be inferred from that paper's transfusion summary. These 730 days are newly generated and are not reconstructed Stanford records. Dates 2024–2025 are simulation labels.

## Generator and assumptions

D_t ~ Poisson(mu_weekday), with no scaling or surge. The equal-weekday expected average is 35.414286 units/day; the realized 730-day mean is 35.608219. Independent Poisson draws conditional on weekday retain the old distributional assumption.

| Parameter | Value | Basis |
| --- | --- | --- |
| Weekday means | 37.5, 37.3, 39.2, 37.8, 40.5, 27.2, 28.4 | Published Table S3, Monday–Sunday |
| Weekly seasonal period | 7 days | Repetition of weekday profile; does not establish all real seasonality |
| Scale | 1.0 | Unscaled reference; avoids unsupported size multipliers |
| Imposed surge | Disabled | No imposed clinical/treatment cycle |
| Distribution | Poisson | Retained exploratory assumption, not fitted from raw observations |
| Seed | 42 | Reproducibility only; no scientific significance |
| Horizon | 730 synthetic days | Retained experiment design, not source sample size |
| Train/validation/test | 456/91/183 days | Retained chronological design; not an optimized split |
| Lead time / review interval | 1 day / 1 day | Retained operating assumptions |
| Receipt multiplier | max(0, 1 + 0.25 Z), Z standard normal | Retained supply assumption; rounding follows multiplication and receipts may exceed orders |
| Remaining life on receipt | 1–5 days, probabilities 0.05/0.10/0.20/0.25/0.40 | Retained simulation assumptions, not observed Guan estimates |
| Initial stock/pipeline | Empty | State initialization; no reset at test boundary |
| Fixed-order factor | 1.05 times reference mean | Assumed 5% margin, not tuned or recommended as optimal |
| Optional shortage/expiry score | 5 × unmet + expired | Arbitrary evaluation weights, not monetary or clinical costs |

**Dispersion limitation:** Table S3 also reports weekday SDs of 7.3, 8.7, 8.7, 8.1, 8.4, 6.4, 6.6. This run does not calibrate those SDs. Its assumed within-weekday SD is sqrt(mu), about 5.22–6.36, lower than every corresponding published SD. It therefore represents a mean-calibrated Poisson reference and may understate shortage/tail risk. A separate mean-and-variance-calibrated count-model sensitivity analysis is still needed. No raw serial dependence, monthly pattern, holidays or patient covariates were reconstructed.

## Held-out forecast results

Training: 1 January 2024–31 March 2025 (456 days). Validation: 1 April–30 June 2025 (91 days). Test: 1 July–30 December 2025 (183 days).

| Model | Today MAE | Today RMSE | Tomorrow MAE | Tomorrow RMSE |
| --- | --- | --- | --- | --- |
| Seasonal naïve | 7.060 | 8.910 | 7.055 | 8.915 |
| MA7 | 6.778 | 8.304 | 6.703 | 8.312 |
| ARIMA | 6.156 | 7.571 | 6.127 | 7.543 |
| SARIMA | 5.142 | 6.329 | 5.104 | 6.284 |

All errors are in simulated requested units. Today is forecast before today's demand is observed (one step); tomorrow is two steps from the same origin. There are 183 scored today forecasts and 182 scored tomorrow forecasts per model. The final tomorrow target lies outside the dataset and is excluded. Validation tomorrow forecasts crossing into test are also excluded from validation scoring.

The 18 ARIMA and 30 SARIMA candidates all converged and were eligible. Selection used validation today MAE; selected orders were then refitted on 547 development days, with fixed fitted parameters and daily state updates using observed demand only through yesterday.

- Selected ARIMA: (2,0,2), with constant.
- Selected SARIMA: (0,0,0)(1,0,1)[7], with constant; d = D = 0.
- SARIMA had the lowest held-out MAE and RMSE among these four methods at both horizons. Its today MAE was 24.15% below MA7.
- Weekly SARIMA can represent the weekday pattern built into this generator. MA7 smooths across weekdays; seasonal naïve repeats one noisy prior-week observation. The result is conditional on this construction and one seed, not evidence of universal superiority.
- Development residual diagnostics are included. SARIMA Ljung–Box p-values at lags 7/14/21 were 0.390/0.376/0.290; these do not establish real-data validity. Selected fits include coefficients close to stationarity/invertibility boundaries, and the SARIMA final fit recorded a starting-value warning before convergence. Optimizer convergence and independent forecast replay passed; stability across other datasets remains untested.

## Fixed-order inventory results

The daily order is round_half_up(1.05 × 35.4142857143) = round_half_up(37.185) = **37 units**. This uses the generator reference mean, not the realized test mean. It is a synthetic benchmark, not a hospital recommendation.

| Test-window measure | Actual rerun result |
| --- | --- |
| Days | 183 |
| Requested units | 6,600 |
| Issued units | 6,565 |
| Unmet units | 35 |
| Days with unmet demand | 3 |
| Expired units | 233 |
| Received units | 6,780 |
| Opening test stock | 65 |
| Closing test stock | 47 |
| Fill rate | 99.47% |
| Stockout-day rate | 1.64% |
| Wastage | 3.40% |
| Mean closing inventory | 80.67 units |
| Weighted shortage/expiry score | 408 (assumed weights; not currency) |

Fill rate = 6565/6600. Stockout-day rate = 3/183. Wastage = 233/(65+6780). Inventory balance: 65+6780 = 6565+233+47. Inventory carries from development into test; full-run results, including the empty initial state, are separately supplied in baseline/inventory_metrics.csv. These inventory figures come from fixed ordering, not SARIMA-driven ordering. Do not attribute the fill rate or wastage to SARIMA.

## Verification and scope

40 code tests passed. The single reference generated 2,192 forecast records (four methods × 274 validation/test origins × two horizons), 16 metric rows, six independent full-prefix filtering checks and two real simulator callback runs. All checks passed; no negative forecast corrections occurred. All daily inventory/request conservation residuals were zero. Callback forecasts matched saved offline forecasts and did not change fixed-policy inventory results.

This run completes the source replacement, four-model forecast comparison, fixed-order baseline, and callback verification. It does not compare alternative inventory policies or provide 30-seed confidence intervals. Those remain future work. Thirty proposed replications would test Monte Carlo variability under the same model; they would not create 30 real hospitals or validate generalization.

## How to answer the guide

“We replaced the preprint-based weekday values with published platelet-transfusion means from Guan et al. in PNAS. We regenerated the data at scale one, removed the unsupported 21-day surge, and reran the same forecasting protocol. SARIMA gave the lowest errors among our four models for this weekly synthetic reference. We have not yet shown that this produces the best inventory policy. Our next comparison will evaluate established policies on shortage, expiry and stock levels across independent replications. The current Poisson model matches weekday means only, so matching the published variability is an additional sensitivity test.”

The research question remains whether forecast accuracy gains translate into better shortage–wastage trade-offs when existing replenishment alternatives are compared under a common age-structured simulator. This is a specific project evaluation question, not proof that the literature has never integrated forecasts and inventory.

## Files and reproduction

This report describes the same verified outcomes. See this package's README.md for current entry points data_synthesis.py, forecast_models.py and run_project.py. Forecast_Comparison.png is ready for slide use. Prism_Full_Update_Current_PPT.md contains the complete 23-slide update for the latest presentation. Full-precision CSVs, candidate search, fitted settings, raw forecast records, simulator logs, tests and code are included.
