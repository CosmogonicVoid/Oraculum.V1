# Milestones 3–5 validation — 17 October 2026

Local release **0.5.0**; original core **0.1.0**. Python 3.12.14, Linux.

## Automated checks

**316 tests pass**, including the original 266 and 50 new regressions. The suite uses fictional fixtures; it does not manufacture market-performance history.

New checks cover combined-score arithmetic, missing and future financial inputs, deterministic ranking, incomplete-profile exclusions, history immutability/recovery and timestamp ordering, daily phase failures, repeat/concurrent paper runs, cash reservations, fees/slippage, future-open decisions, 20-session exits, gaps, stale or missing prices, split/bonus/dividend accounting, action revisions, identity changes and read-only HTTP routes.

## Live exchange evidence and repeat run

The validation copied existing caches into a separate workspace, refreshed public exchange metadata and downloaded 12 additional official financial filings. It then rebuilt the report offline using the final code. No validation database is installed in the delivered project.

Price session **2026-10-16**; report cutoff **2026-10-17T07:20:49.810473Z**.

| Check | Result |
|---|---:|
| Supported traded EQ/STK/F1 instruments inspected | 2,691 |
| Technically eligible | 997 |
| Complete combined rankings | 15 |
| Combined candidates/highlights | 10 / 10 |
| Financial profiles with all four screen metrics | 15 |
| Partial financial profiles | 6 |
| Selected financial documents still uncached | 7,088 |

Coverage remains partial. This confirms an operational path, not a complete market feed or validated stock-selection edge.

An independent Decimal calculation matched all **15** published combined scores within 1e-10. All financial availability timestamps preceded the report cutoff. An offline repeat preserved the price/evidence cache bytes and left the saved paper decisions and cash exactly unchanged. The report history retained both refreshes.

## Forward enrollment

The isolated validation experiment began with **INR 100,000 virtual cash**, recorded **five pending stock entries** and one benchmark entry, and had **zero executed positions and zero completed forward sessions**. Entries were committed for **19 October 2026**, a future reviewed exchange session. Cash had not been debited. No returns were claimed before execution.

The repeated run did not replace the first decision with a newer same-session report. Fictional scenarios separately verified exact cash debits, dividend receivables, share adjustments, drawdown and holding-period exits. These scenarios are software tests, not evidence of profitability.

## HTTP, upgrade and privacy checks

Ten actual local HTTP requests succeeded: homepage, latest research JSON/CSV, history HTML/JSON, forward HTML/JSON/CSV, automation status and the earlier paper status. Read operations left paper state unchanged; the old manual paper and core-run databases were not created.

The update ZIP is tested by applying it over the exact delivered 0.4.0 archive, then running the complete regression suite and checking the release version. The complete ZIP has a file checksum manifest. The public source export excludes real market reports, runtime databases, logs, evidence caches and credentials. Windows launchers retain CRLF.

Original private database SHA-256: `ec065b706c4de97f032f25bcc781cb26549d8e90e47af94f6d63f9354501fc05` (unchanged).

## Limits of this verification

Native Windows Task Scheduler, Windows batch execution, Python 3.14, GitHub CI and future exchange sessions were not executed here. Scheduler arguments, account privilege choices and error behavior were checked using mocks and official Microsoft documentation. Install and inspect the task on the target Windows PC.

The bundled reviewed calendar ends on **7 November 2026**. Financial backfill, other filing schemas, complex corporate actions, news/general announcements and proven forward performance remain unfinished. The benchmark is a NIFTYBEES/cash simulation, not an official total-return index.

The complete private ZIP contains `validation/milestones-3-5-2026-10-17.html` plus matching hashed JSON/CSV. This is a dated development snapshot, not the state of the user’s installation. The smaller patch does not include real validation snapshots.

Final validation report ID: `06b01d3923341efb37dc169c12732dc0698b8d3eb3185639bcd7185b468db5ac`
