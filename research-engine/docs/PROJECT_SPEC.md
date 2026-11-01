# Shared project specification

## Product goal

Oraculum is a paper-only research system for Indian listed equities. Its long-term
goal is a daily, ranked, evidence-backed shortlist with an honest record of how
signals perform after they are produced.

The first executable core accepts a versioned snapshot of metrics, validates it,
ranks it, explains it and stores the complete decision record. This specification
and the Python contracts are shared across the contributors.

## Decisions fixed for this milestone

- End-of-day research. The supplied exchange session must have closed.
- INR monetary inputs; decimal fractions for returns and financial ratios.
- A future evaluation horizon of 20 actual trading sessions. Baseline scores
  themselves have no calibrated horizon or predicted-return meaning.
- Long-only paper simulation will be a separate consumer of research reports.
- No real broker connection, money movement, leveraged or short positions.
- Standard-library Python, local JSON and SQLite. No runtime AI/API dependency.
- Synthetic fixture mode is visibly separate from imported-data mode.
- Financial-sector companies are excluded until an appropriate quality model exists.
- Data provider owns calendars and historical vintages; core verifies the timestamps
  it receives but cannot establish that those timestamps are truthful.

## Module boundaries

| File / folder | Owner | Purpose |
| --- | --- | --- |
| oraculum/contracts.py | ChatGPT | Canonical source, metric, asset and bundle parsing |
| oraculum/interfaces.py | ChatGPT | Provider, feature-builder and paper-simulator interfaces |
| oraculum/config.py | ChatGPT | Explicit model configuration |
| oraculum/scoring.py | ChatGPT | Factors, eligibility and ordering |
| oraculum/pipeline.py | ChatGPT | Public build_run entry point |
| oraculum/repository.py | ChatGPT | Complete immutable application run history |
| oraculum/serialization.py | ChatGPT | Strict JSON and canonical hashing |
| oraculum/reporting.py | ChatGPT | Machine and human reports |
| oraculum/cli.py | ChatGPT | Executable command interface |
| oraculum/demo.py | ChatGPT | Reproducible fictional fixtures |
| oraculum/features.py | Qwen, new | Price and volume calculations |
| oraculum/providers/ | Qwen, new | Canonical bundle creation from supplied data |
| oraculum/paper/ | Kimi, new | Decimal-based simulation and accounting |
| tests/test_qwen_*.py | Qwen, new | Adapter and numerical tests |
| tests/test_kimi_*.py | Kimi, new | Independent checks and simulator tests |

Neither contributor edits an existing core file. If the shared API needs a change,
return the proposed change and reason with the deliverable. ChatGPT integrates it.
This avoids silent changes to units, function names or the scoring equation.

## Reproducibility

The run identifier hashes normalized input, full config, engine version and algorithm
version. Every saved report contains those items and all evidence references.
The database rejects application-level updates/deletes. Report checksums detect
accidental modification; an administrator with file access can defeat these controls.
This is not a cryptographic notarization or proof of historical data quality.

Scoring behavior changes require an algorithm/engine version change. Shared schema
changes require a schema version change and migration plan. Save the corresponding
source revision alongside research experiments; version labels alone do not archive code.

## Acceptance and release sequence

1. Core: all bundled tests pass; demo scores match the supplied example.
2. Qwen: a supplied CSV plus supplemental bundle creates valid metrics with no lookahead.
3. Kimi: independent numerical tests and a cash-conserving next-open execution simulator.
4. Integration: a local import-to-research-to-paper-results flow on fixtures.
5. Evaluation: frozen experiments on appropriate historical and forward paper data.
6. Product: reliable data ingestion, schedule, alerts and website integration.

Source licensing and any public distribution requirements must be resolved for the
chosen feeds and product before going live. This spec does not assert a legal exemption.

## Evaluation requirements before claiming a market advantage

Use a point-in-time universe including delisted securities where relevant. Keep a
final untouched chronological test period and document every experiment. With
overlapping 20-session labels, remove training examples whose outcome windows reach
the validation/test period. Fit preprocessing using training data only.

Measure benchmark-relative return, drawdown, turnover, trading costs, coverage,
stability across periods and sector concentration. Include a simple momentum baseline,
an appropriate broad-market benchmark and an abstention policy. A positive backtest
is insufficient by itself; retain immutable forward paper records.

If an LLM extracts historical events, examine whether its pretraining or retrieval
contains information from the future. Prefer source-contained extraction with
quotations/evidence IDs and audit the result. Model agreement is not an accuracy metric.
