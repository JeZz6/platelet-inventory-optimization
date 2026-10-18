# Current Guan reference assumptions

This records the settings already used in the source package. Repository preparation does not change the modelling contract.

| Item | Current value | Basis / limitation |
| --- | --- | --- |
| Source | Guan et al. (2017), PNAS, Table S3 | DOI 10.1073/pnas.1714097114 |
| Source quantity | Daily platelet units transfused | Proxy for requested units; unmet requests are not observed in the source summary |
| Mon-Sun means | 37.5, 37.3, 39.2, 37.8, 40.5, 27.2, 28.4 | Published weekday means |
| Source weekday SDs | 7.3, 8.7, 8.7, 8.1, 8.4, 6.4, 6.6 | Disclosed but not fitted by current generator |
| Demand | Independent Poisson conditional on weekday | Assumption; understates published within-weekday dispersion |
| Scale and imposed surge | Scale 1.0; surge disabled | One reference, no Low/Mid/High or imposed treatment cycle in current results |
| Random seed | 42 | Reproducibility only |
| Calendar | 730 days, 2024-01-01 to 2025-12-30 | Simulation labels, not source observation dates |
| Split | 456 train / 91 validation / 183 test | Chronological project design |
| Features | Past requested counts only | No generator means, future demand or cycle features |
| Selection | Validation today MAE | Never select settings or buffers using final test outcomes |
| Test update | Fixed fitted parameters; rolling state updates | Observations available through yesterday only |
| Lead time / review | One day / one day | Operating assumptions |
| Allocation | Pooled demand, FEFO | No young/any-age allocation split |
| Receipt quantity | round_half_up(order x max(0, 1 + 0.25 Z)) | Standard-normal Z; supply assumption, receipts can exceed nominal order |
| Remaining usable life on receipt | 1-5 days; probabilities 0.05/0.10/0.20/0.25/0.40 | Assumed; not fitted from Guan |
| Initial inventory / pipeline | Empty / empty | Continuous state carry-over; no reset at split boundaries |
| Fixed ordering | round_half_up(1.05 x 35.4142857143) = 37/day | Assumed benchmark; uses configured source mean |
| Shortage treatment | Recorded as unmet, without automatic backlog | Daily lost-demand accounting |
| Weighted score | 5 x unmet + expired | Nonmonetary assumed weights |

The optional cycle switch and artificial test fixtures remain in the general engine; they are not enabled in this experiment. Only one synthetic seed has been evaluated. Multiple seeds, higher-dispersion demand sensitivity and alternative replenishment-policy comparisons remain unfinished.

