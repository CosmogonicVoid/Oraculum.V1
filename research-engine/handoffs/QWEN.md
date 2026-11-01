# Qwen assignment: data adapters and price features

Implement your part of Oraculum against the supplied v0.1.0 core. Produce complete,
runnable Python files and tests. Do not redesign the project or change the scoring
formula. This is development work; do not connect a model API or brokerage service.

## Files to read

README.md, docs/PROJECT_SPEC.md, docs/CONTRACTS.md, docs/ALGORITHM.md,
oraculum/contracts.py, oraculum/interfaces.py, oraculum/pipeline.py,
oraculum/serialization.py, and examples/demo_bundle.json.
The source of truth for interfaces is the existing Python code.

## Files you may create

- oraculum/features.py
- oraculum/providers/__init__.py
- oraculum/providers/csv_provider.py
- tests/test_qwen_features.py
- tests/test_qwen_csv_provider.py
- examples/qwen/ containing only clearly labeled synthetic fixtures
- docs/QWEN_IMPLEMENTATION.md

Do not edit existing core modules, config/default.json, handoffs, or existing tests.
If the API needs a change, describe the smallest proposed change separately.
Use Python standard-library modules only. Target Python 3.12+.

## Part A: numerical functions

Implement these pure functions in features.py:

    momentum(closes: Sequence[float], periods: int = 20) -> float | None
    trend(closes: Sequence[float], window: int = 50) -> float | None
    volume_ratio(volumes: Sequence[int], window: int = 20) -> float | None
    annualized_volatility(closes: Sequence[float], periods: int = 20) -> float | None
    mean_turnover(turnovers: Sequence[float], window: int = 20) -> float | None

Import Sequence from typing. Inputs are oldest first. Use the most recent required
window. Insufficient history returns None; malformed inputs raise ValidationError.
Reject booleans, non-finite values, non-positive closes, negative turnover or volume,
and non-positive/non-integer window sizes. Volatility periods must be at least 2.
Do not mutate input sequences. Do not impute missing observations.

Exact definitions:

- Momentum: closes[-1] / closes[-(periods+1)] - 1.
- Trend: closes[-1] / mean(closes[-window:]) - 1.
- Volume ratio: volumes[-1] / mean(volumes[-(window+1):-1]).
  Return None if the preceding mean is zero.
- Volatility: form the last periods simple returns from periods+1 closes; use
  sample standard deviation (ddof=1) and multiply by sqrt(252).
- Turnover: mean of the last window actual turnover values. Do not approximate
  actual turnover by closing price times volume when traded turnover is available.

Hand-check examples:

- momentum([100, 110, 121], 2) = 0.21.
- trend([100, 110, 120], 3) = 120/110 - 1.
- volume_ratio([100, 200, 300], 2) = 2.0.
- annualized_volatility([100, 110, 121], 2) is approximately zero.
- mean_turnover([100, 200, 300], 2) = 250.

Implement BasicPriceFeatureBuilder satisfying PriceFeatureBuilder:

    build_metrics(self, bars: Sequence[PriceBar], *, as_of: datetime) -> dict

Use only bars with available_at <= as_of and close_at <= as_of. All retained bars
must refer to one instrument, use timezone-aware times, and have consistent
adjustment_version. Validate OHLC geometry, nonnegative integer volume and actual
turnover. Sort by session; reject duplicate available sessions. Reject a naive as_of.

Return the six daily metric dictionaries named in CONTRACTS.md, using the latest
eligible close as observed_at and the latest dependency availability as available_at.
Source IDs must cover all bars used by each calculation, not only the last bar.
For unavailable metrics return null values with empty source_ids. With no eligible
bars return an empty dictionary. PriceFeatureBuilder assumes a contiguous sequence
of exchange sessions; the provider checks this against a supplied calendar.

## Part B: supplied-data CSV adapter

Build an offline command:

    python -m oraculum.providers.csv_provider --prices INPUT.csv --base-bundle BASE.json --sessions SESSIONS.json --output BUNDLE.json

The CSV columns are exactly:

    instrument_id,session,open_at,close_at,available_at,open,high,low,close,volume,turnover_inr,source_id,adjustment_version

Monetary values become Decimal in PriceBar; the feature functions may use floats for
ratios/statistics. Dates/times use the existing parsing helpers.

BASE.json follows the complete ResearchBundle schema, including as_of, last_session,
session_close_at, source records, sector metadata and any supplied non-daily metrics.
Daily metrics may be omitted in BASE.json. This is valid input to parse_bundle.
Do not fabricate fundamentals or narrative scores when absent.

SESSIONS.json is an object with a sessions array. Each entry has exactly session,
open_at and close_at. Require unique ordered dates and open_at < close_at, with
matching India session dates. Use this calendar to check that BASE.last_session is
the most recent session closed by BASE.as_of and that close times agree.
Do not infer exchange holidays from weekdays.

For each asset, use the contiguous available session suffix ending at its latest
known session. A gap breaks the calculation window: do not join prices across
missing sessions to obtain a misleading "20-session" return. Insufficient history
becomes missing metrics. Leave a stale asset's session visibly stale.

Reject undeclared instrument/source IDs and invalid data; explain errors with row
numbers. Preserve the mode, dataset identity and non-daily source provenance.
Do not silently drop an input asset, restamp its data as current, or backdate source
availability. Computed availability must be at least the availability of every
referenced source, even if the bars themselves have earlier timestamps.

The adapter must distinguish raw execution bars from corporate-action-adjusted
research bars. Require a consistent, documented adjustment version for each
instrument's calculation. For this phase do not implement corporate-action
adjustment or claim it exists: accept already correctly prepared data and disclose
that assumption. Preserve raw execution data separately.

Write the merged canonical bundle only after parse_bundle validates it.
Never overwrite the input CSV, base bundle or calendar. Existing output needs
explicit --force. No network requests and no automatic scraping.

Expose CsvResearchProvider implementing ResearchProvider. Constructor:

    CsvResearchProvider(prices_path, base_bundle_path, sessions_path)

load_bundle(as_of=..., last_session=...) must check that the requested cutoff/session
match the base bundle and return the merged ResearchBundle.

## Required verification

Test exact formulas, insufficient history, zero volume denominators, constant prices,
negative/NaN values, duplicates, reversed input rows, missing exchange sessions,
future bars, timezone errors and source-availability propagation.

Appending valid future bars must not change a historical feature result. A late
filing must not appear in an earlier cutoff. Produce a fixture bundle the existing
core can validate and rank. All existing core tests must continue to pass.

Return each created file with its path, the commands used, actual test results and
known assumptions. If you could not execute tests, explicitly say "not run".
Never claim real-market predictive performance from synthetic fixtures.
