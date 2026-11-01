# Oraculum contract v1

The executable definitions are in oraculum/contracts.py and oraculum/interfaces.py.
Unknown fields are rejected. Whole malformed bundles are rejected rather than
partially ranked. Valid but incomplete/stale assets receive coverage penalties and
possibly exclusions. All numeric JSON values must be finite, and booleans are not numbers.

## Research bundle

| Field | Meaning |
| --- | --- |
| schema_version | Integer 1 |
| dataset_id | Stable identifier for the input dataset/vintage |
| mode | synthetic or imported; all demonstration outputs must be synthetic |
| as_of | ISO timestamp with offset; decision-information cutoff |
| last_session | YYYY-MM-DD; latest completed exchange session, supplied by the provider |
| session_close_at | Actual close timestamp for that session; must be <= as_of |
| sources | Array of Source records |
| assets | Array of AssetSnapshot records |

See examples/demo_bundle.json for a complete, runnable example.
as_of is the information cutoff, not the wall-clock time when the program happens to run.
India's +05:30 offset is used for session dates. The core does not guess weekends,
holidays or special trading-session hours.

## Source

All fields are required; content_sha256 may be null.

| Field | Meaning |
| --- | --- |
| id | Unique identifier; metrics reference this value |
| kind | prices, fundamentals, news, announcement or derived |
| title | Short source description |
| uri | https://, http:// or file://; fixture:// only in synthetic mode |
| published_at | When the source was published |
| available_at | Earliest time this source/version was available to the strategy |
| content_sha256 | Lowercase 64-character SHA-256 of archived source bytes, or null |

Require published_at <= available_at <= as_of. Preserve first-availability records.
Current restatements cannot be backdated to an earlier fiscal period.
For a derived model output, include model/version provenance in the archived source.
There is no automatic URI fetch, content-hash verification or fact-checking in the core.

## Asset snapshot

symbol is uppercase, exchange is NSE or BSE, session is a date, and metrics is an
object whose keys are the metric names below. Instrument identity is EXCHANGE:SYMBOL.
Use a stable instrument master to resolve symbol changes and cross-listings in the provider.
The core detects duplicate instrument IDs, not two listings of the same economic company.

Supported sectors: industrials, technology, consumer, healthcare, energy, materials,
utilities, real_estate, telecom, financials, other. Financials are parsed but excluded.

Every metric has exactly:

    {
      "value": 0.08,
      "observed_at": "2026-10-09T10:00:00Z",
      "available_at": "2026-10-09T10:05:00Z",
      "source_ids": ["prices-vintage-001"]
    }

observed_at is the end of the underlying measurement period or the observed event.
available_at is when the computed metric and all dependencies were actually available.
Require observed_at <= available_at <= as_of and every source.available_at <=
metric.available_at. A non-null value needs at least one valid source reference.
Use null or omit the metric for unknown data; never substitute zero.

For daily metrics, observed_at must match asset.session in India; on the latest
session it must equal session_close_at. All fractions use 0.05 for 5%.

| Metric | Units and intended construction |
| --- | --- |
| close_inr | Positive last-session closing price in INR |
| turnover_20d_inr | Mean of actual traded INR turnover over 20 sessions through t |
| volatility_20d_annualized | Sample standard deviation of 20 close-to-close simple returns × sqrt(252); needs 21 closes |
| momentum_20d | close[t] / close[t-20] - 1; needs 21 closes |
| trend_50d | close[t] / mean(close[t-49:t+1]) - 1; needs 50 closes |
| volume_ratio_20d | volume[t] / mean(volume[t-20:t]); excludes today's volume from the denominator |
| roce | Trailing EBIT / average capital employed; decimal fraction; exclude unusable denominator |
| revenue_growth_yoy | Latest comparable quarter revenue / prior-year same-quarter revenue - 1; prior denominator positive |
| debt_to_equity | Latest total interest-bearing debt / equity; nonnegative; equity must be positive |
| pe_to_sector_median | Positive trailing company P/E divided by positive, point-in-time sector median P/E |
| news_sentiment | Sourced [-1, 1] aggregate over the configured news window |
| announcement_impact | Sourced [-1, 1] signed materiality assessment over the configured event window |

The first six are daily metrics. Price-return calculations must use one consistent
point-in-time corporate-action treatment. The current baseline is a price-return,
not a dividend-reinvestment, model. Preserve raw execution prices separately.
Do not claim split adjustment is correct without testing it on known actions.

Fundamental and narrative metric production is a provider/extraction task. Missing
observations must remain missing. Quality numbers from different accounting definitions
are not automatically comparable just because they use the same field name.

## Public Python API

    report = build_run(raw_bundle, raw_config=None, generated_at=None)

Import from oraculum.pipeline. raw_bundle is a dictionary or ResearchBundle;
raw_config is a full configuration dictionary, EngineConfig or None. The public entry
point revalidates objects. Internal scoring helpers assume already validated objects.
generated_at, when supplied for a fixture, must be timezone-aware.

The report contains the full input, full config, versions, hashes, shortlist, decision
statuses, full factor breakdowns, blockers, warnings and generated_at/as_of.
Look up assets by instrument_id. Do not treat an array position as a stable instrument key.
Scores are stored unrounded; UI rounding must not be used to change rank order.

## Extension ports

ResearchProvider.load_bundle(as_of=..., last_session=...) returns ResearchBundle.
PriceFeatureBuilder.build_metrics(bars, as_of=...) returns canonical metric dictionaries.
See handoffs/QWEN.md for the initial adapter and calculation contract.

PriceBar, PaperOrder, PaperFill, Position, PortfolioState, OrderRejection and SessionResult
are frozen dataclasses in interfaces.py. Monetary amounts in these paper-execution
contracts use Decimal. PaperSimulator.execute_session returns SessionResult.
See handoffs/KIMI.md for execution ordering, validation and accounting rules.

These Protocol classes declare interfaces only. No unimplemented provider/simulator
is selected by the working core CLI.
