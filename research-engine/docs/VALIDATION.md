# Delivery verification — 2026-10-13 integration

Environment: Python 3.12.14 on Linux. The user's Windows/Python 3.14.4 setup
has not been remotely executed; run the same suite there.

Executed from the project root:

```text
python3 -W error -m unittest discover -s tests -v
```

Result: **161 tests passed; no failures, errors or skips.** Warnings are treated
as errors. This includes the original 55 core tests, repaired contributor tests,
and 17 new regression tests from the integration review.

The same suite and the paper demo are checked again from a clean extraction of
the final ZIP. Checksums in MANIFEST.sha256 cover the delivered source and data.

## Evidence covered

| Area | Checks |
| --- | --- |
| Contracts and configuration | Strict fields, types, finite values, timestamp/source ordering, weight totals |
| Scoring | Independent expected values, score bounds, missingness, negative volume confirmation, original 79/68/50/31 demo |
| Risk and freshness | Liquidity, leverage, volatility, coverage, stale observations and financial-sector exclusion |
| CSV adapter | Calendar agreement, source propagation, gaps, row-level errors, deterministic vintages and cutoff invariance |
| Price features | Hand calculations, sample deviation, required windows, zero-volume unknowns, source IDs and numerical limits |
| Paper execution | Raw prices, next supplied open after submission, fees, slippage, cash/shares, weighted costs and duplicate rejection |
| Paper input boundaries | Complete-session chronology, session date, malformed types, caller Decimal context, zero-rounded fills and large balances |
| Audit storage | Full snapshot persistence, immutable history, hashes and replay |
| File protection | Existing exports and direct/symlink resolution; explicit hardlink-alias regression checks |
| CLI | Actual subprocess import, validate, rank, demo, show, history, replay, JSON/Markdown and paper demo |

No check downloads market data or calls an AI service or broker. File-writing
checks use temporary output folders and databases. The user's included database
was compared byte for byte with its copy in the uploaded ZIP and preserved.

## Executed end-to-end workflow

1. Merge examples/qwen/prices.csv, base.json and sessions.json into a bundle.
2. Validate and rank the bundle; write JSON and Markdown and save a research run.
3. Read the report and history, then verify replay from SQLite.
4. Run the original core demo through the same export/persistence/replay checks.
5. Run `python -m oraculum.paper.demo` and verify its exact Decimal cash/fee/fill.

The CSV fixture has one candidate (QW-ALPHA, approximately 72.91) and two
excluded assets. Paper demo: start 10,000.00; buy 3 at 130.1300; gross 390.39;
fee 0.39; cash 9,609.22; average cost 130.26. Reprocessing the order leaves
state unchanged. All prices, costs and instruments in this demo are fictional.

## Original research demo

| Instrument | Score | Status |
| --- | ---: | --- |
| NSE:SIM-ASTER | 79.00 | candidate |
| NSE:SIM-BANYAN | 68.00 | candidate |
| NSE:SIM-CEDAR | 50.00 | watch |
| NSE:SIM-DUNE | 31.00 | watch |
| NSE:SIM-EMBER | 79.00 | excluded: liquidity |
| NSE:SIM-GROVE | 79.00 | excluded: financial-sector model |
| NSE:SIM-HARBOR | 70.00 | excluded: volatility |
| NSE:SIM-FERN | 54.75 | excluded: missing coverage |

These are software verification results. No predictive accuracy, investment
returns, live-source accuracy or realistic historical backtest is established.
Scheduling, live ingestion, portfolio persistence and website integration remain
outside this release. See INTEGRATION_REVIEW.md for corrected defects and limits.
