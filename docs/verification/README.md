# Local repository verification - 18 October 2026

All checks below were executed locally on the prepared repository with Python 3.12.14 and the pinned numerical dependencies. This is not a hosted GitHub Actions run.

| Check | Result |
| --- | --- |
| Existing unit tests | 40 passed |
| Fresh synthetic input and fixed benchmark | All 8 input/benchmark CSV files byte-identical to source |
| Full ARIMA/SARIMA validation search and final evaluation | Completed |
| Reference comparison | All 2,192 forecasts and 16 accuracy rows reproduced within rtol=atol=1e-8 |
| Selected model orders | Identical to supplied reference |
| Independent full-prefix checks | 6 passed |
| Live simulator forecast callbacks | 2 passed; match offline calculations |
| Inventory and requested-unit conservation | Passed |
| Original copied model/configuration files | Unchanged |
| Python compilation / local Markdown links | Passed |

Logs and detailed JSON reports are in this folder. `docs/SOURCE_PACKAGE.json` records the source archive hash and copied-file hashes. `repository_checks.json` records packaging checks. Alternative advanced-model inventory-policy comparisons have not been run by this preparation step.

