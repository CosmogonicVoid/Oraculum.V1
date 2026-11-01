# Qwen implementation notes — data adapters and price features (Oraculum v0.1.0)

Integration update (2026-10-13): this document reflects the corrected code.
The original contributor did not execute tests. The combined integration suite
now passes 161 tests; see VALIDATION.md and INTEGRATION_REVIEW.md.

Original contribution scope: `oraculum/features.py`, `oraculum/providers/`, `tests/test_qwen_*.py`,
`examples/qwen/` fixtures and this document. No core module, config, handoff or
existing test was modified. Standard library only; Python 3.12+ target.

## Part A — numerical functions (`oraculum/features.py`)

Inputs are oldest-first; only the most recent required window is used.
Insufficient history returns `None`; malformed input raises `ValidationError`.
Rejected: booleans, non-finite values, non-positive closes, negative volume or
turnover, non-positive or non-integer window/period arguments, volatility
periods < 2. Sequences are never mutated; nothing is imputed.

| Function | Definition |
| --- | --- |
| `momentum(closes, periods=20)` | `closes[-1] / closes[-(periods+1)] - 1`; needs `periods+1` closes |
| `trend(closes, window=50)` | `closes[-1] / mean(closes[-window:]) - 1`; needs `window` closes |
| `volume_ratio(volumes, window=20)` | `volumes[-1] / mean(volumes[-(window+1):-1])`; `None` if the preceding mean is zero; needs `window+1` volumes |
| `annualized_volatility(closes, periods=20)` | sample std (ddof=1) of the last `periods` simple returns × sqrt(252); needs `periods+1` closes |
| `mean_turnover(turnovers, window=20)` | mean of the last `window` actual traded INR turnover values (never approximated by price × volume) |

Hand checks: `momentum([100,110,121],2)=0.21`, `trend([100,110,120],3)=120/110-1`,
`volume_ratio([100,200,300],2)=2.0`, `annualized_volatility([100,110,121],2)=0`,
`mean_turnover([100,200,300],2)=250`.

### `BasicPriceFeatureBuilder`

`build_metrics(bars, *, as_of)` implements the `PriceFeatureBuilder` port:

- Rejects naive `as_of`; keeps only bars with `available_at <= as_of` and
  `close_at <= as_of` (point-in-time cutoff; late filings and future bars are
  invisible). Empty eligible set returns `{}`.
- Retained bars must share one instrument, one `adjustment_version`, and
  timezone-aware stamps; OHLC geometry (`low <= open/close <= high`, positive
  prices), non-negative integer volume, non-negative finite Decimal turnover,
  `open_at < close_at <= available_at` and matching Indian session dates are enforced. Bars are sorted by session; duplicate
  sessions raise `ValidationError`.
- Returns all six daily metric dicts. `observed_at` is the latest eligible
  close time; `available_at` is the latest dependency availability (floored by
  the observed time); `source_ids` cover every bar used by that calculation.
  Unavailable metrics carry `value: null` with empty `source_ids`.
- Contiguity against an exchange calendar is the provider's job; the builder
  assumes the provider passed a contiguous session suffix.

## Part B — supplied-data CSV adapter (`oraculum/providers/csv_provider.py`)

Command:

    python -m oraculum.providers.csv_provider --prices INPUT.csv \
        --base-bundle BASE.json --sessions SESSIONS.json --output BUNDLE.json [--force]

Inputs:
- CSV header must be exactly:
  `instrument_id,session,open_at,close_at,available_at,open,high,low,close,volume,turnover_inr,source_id,adjustment_version`.
  Monetary fields become `Decimal` in `PriceBar`; dates/times use the existing
  `contracts.day`/`contracts.timestamp` helpers.
- `BASE.json` is a complete ResearchBundle (parsed by `parse_bundle`): it owns
  `as_of`, `last_session`, `session_close_at`, sources, sectors and non-daily
  metrics. Daily metrics may be omitted. If BASE supplies daily metrics for an
  asset that has eligible bars, the recomputed daily metrics replace them;
  non-daily metrics are always preserved verbatim. Nothing is fabricated.
- `SESSIONS.json` is `{"sessions": [{session, open_at, close_at}, ...]}` with
  unique, strictly ordered dates, `open_at < close_at`, and both stamps falling
  on the session date in India (+05:30). The calendar is authoritative; the
  adapter never infers holidays from weekdays.

Row validation (errors cite file row numbers; header is row 1): exact column
count; declared instrument and source IDs; session present in the calendar;
bar `open_at`/`close_at` equal to the calendar times; OHLC geometry and signs;
integer non-negative volume; finite non-negative turnover; timezone-aware
stamps; no duplicate `(instrument, session, adjustment_version)`.

Eligibility and merge semantics:
- Bars with `close_at > as_of` or `available_at > as_of` are excluded, not
  errors: appending valid future bars or late filings does not change any
  historical result.
- For each instrument the adapter uses the contiguous calendar-session suffix
  ending at its latest known session. A missing session or an
  adjustment-version change breaks the window; history is never joined across
  gaps. Insufficient suffix length becomes null metrics, never zeros.
- An asset's output session is its latest eligible bar session, so stale
  assets remain visibly stale. BASE assets without eligible bars are retained
  unchanged (never dropped, never restamped).
- Metric `available_at` is at least the maximum availability of every
  referenced source and of every used bar, and at least `observed_at` — no
  backdating; availability is only pushed later.
- Mode, `dataset_id`, `as_of`, `last_session`, `session_close_at` and source
  records are preserved from BASE. The merged bundle is written only after
  `parse_bundle` validates it.

Adjustment-version policy (disclosure): this phase does **not** implement
corporate-action adjustment. The adapter accepts already correctly prepared
data, requires one consistent documented `adjustment_version` per instrument
calculation, and treats a version change as a window break. When the newest
eligible session carries raw plus one non-raw version, that non-raw version is
used for research. With raw only, raw is used. Two or more non-raw versions at
that session are ambiguous and rejected: supply one research vintage. Selection
is independent of CSV row order, and filtering happens before version selection. Raw execution data is preserved separately by
leaving the input tape untouched and by excluding non-research versions from
metric computation; their presence is visible in the tape.

Output protection: the output path must differ from the three inputs; an
existing output requires `--force`; inputs are only ever opened for reading.
Exit status is 0 on success and 2 on input/storage errors. No network access.

### `CsvResearchProvider`

`CsvResearchProvider(prices_path, base_bundle_path, sessions_path)` implements
the `ResearchProvider` port. `load_bundle(as_of=..., last_session=...)` builds
the merged bundle and rejects requested cutoffs/sessions that do not match the
base bundle, so callers cannot silently re-date a vintage.

## Verification

Commands (from the project root):

    python -m unittest discover -s tests -v
    python -m oraculum.providers.csv_provider --prices examples/qwen/prices.csv \
        --base-bundle examples/qwen/base.json --sessions examples/qwen/sessions.json \
        --output tmp/qwen_bundle.json
    python -m oraculum validate --input tmp/qwen_bundle.json
    python -m oraculum rank --input tmp/qwen_bundle.json --config config/default.json --no-save

**Integration status: executed and passing.** The original unexecuted submission
was corrected during integration. All 161 combined tests passed on Python
3.12.14/Linux. CSV -> canonical validation -> ranking -> SQLite -> export/replay
also passed. QW-ALPHA is a candidate at about 72.91; the other two assets are
excluded. These are fictional fixtures and do not measure forecasting skill.

## Assumptions and disclosures

1. No corporate-action adjustment is implemented; pre-adjusted data is accepted
   as supplied and raw rows are preserved in the untouched tape.
2. Completed daily bars require `available_at >= close_at`. Earlier availability
   is rejected at the CSV row and builder boundaries.
3. Whole-file price source availability propagates to every metric that
   references it, even when individual bars carry earlier timestamps.
4. Calendar adjacency (not weekday arithmetic) defines contiguous sessions.
5. CSV cells are stripped of surrounding whitespace before parsing.
6. The fixture tape's `turnover_inr` values were constructed as close × volume
   for convenience, but the adapter treats them as actual traded turnover.

## Integration notes

- `build_merged_bundle(...)` is the reusable entry point; `CsvResearchProvider`
  satisfies `oraculum.interfaces.ResearchProvider`.
- The merged fixture is a canonical input to `build_run`, `validate` and `rank`.
- CSV syntax, encodings and row data are validated before writing an output.
- Protected inputs include hardlink aliases; `--force` applies only to outputs.
- Public contracts and the scoring formula were not changed. See
  INTEGRATION_REVIEW.md for the defects corrected during integration.
- No corporate-action calculation or predictive performance claim is included.
