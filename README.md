# Oraculum — Forecast. Test. Learn.

A forecast research website with an integrated **₹1,00,000 virtual investing challenge**. Version 1 runs a transparent statistical model, records predictions and compares them with outcomes. No Qwen, Ollama, paid AI API or brokerage account is required.

**This release uses real historical prices for replay, not live prices.** Newer forecasts use CSVs that you provide. There is no demonstrated predictive edge. The original Python research engine remains in `research-engine/`; it is not silently replaced or automatically run by the website.

## Try it

Open the website, sign in, and click **Start challenge**. You receive ₹1 lakh in virtual cash and the five highest-ranked forecasts are recorded at the initial cutoff. Select a stock, examine its chart and estimated range, write a thesis, and queue a buy order. Click **1 session** to reveal its next opening price and execute the order. Advance **20 sessions** to evaluate the original forecasts. Use **My portfolio** to inspect orders, cancel queued orders, and view holdings and portfolio value against NIFTY. Sell from the same stock panel. All money is virtual.

**Research workspace** accepts 420–2,500 dated daily observations for one stock and a matching benchmark. It computes a forecast server-side, saves the creation time and input fingerprint, and evaluates the prediction when you upload the same history with 20 more observations. Older data is explicitly labelled retrospective. Up to 40 predictions are saved per account; at that limit imports can still update existing outcomes. No automatic daily ingestion is configured.

Your previous fictional-price account is preserved at `/legacy`. It is a separate ledger and does not share the new challenge’s cash or performance.

## Run locally on Windows, macOS or Linux

Install **Node.js 24 or newer**. Extract this source ZIP into a new directory, open that directory in VS Code, and run these commands in its terminal:

```sh
npx --yes pnpm@11.25.0 install --frozen-lockfile
npm run build
npm run db:local
npm run dev
```

Open **http://localhost:5173**. Click **Sign in** to use the starter’s local development identity. Local sign-in does not require a ChatGPT or broker account. On Windows, after setup you can double-click `start-web.cmd` instead of typing the last command.

The first dependency installation needs internet access. Once dependencies and the included archive are present, the local replay and CSV forecast model need no external market or model API. Stop with Ctrl+C. Restart with `npm run dev`. Your local accounts persist in `.wrangler/state`; keep that directory when upgrading and back it up before database changes. The ZIP contains no personal account data.

`npm run db:local` applies missing tables for the initial two migrations and skips them when they already exist. It does not drop tables or reset portfolios. After later schema changes, extend the migration helper rather than editing an already applied SQL file.

The local server is for your own machine. Production identity comes from the Sites gateway; public deployment on another host requires equivalent trusted authentication. Do not expose the raw development server publicly.

## What is included

- Graphite dashboard with translucent panels, responsive navigation, search, ranking sort and watchlist.
- Interactive line/candlestick charts, MA20, volume and an uncertain 20-session projection.
- 49 real historical stock series, with 79 replay sessions from **4 January to 30 April 2021**.
- Per-stock ridge regression: expected stock return and expected excess return over NIFTY.
- Small-sample residual ranges and estimated probability of beating the benchmark, labelled as uncertain.
- Server-owned game balances, next-open fills, partial/full sales, cost basis and thesis journal.
- Prediction records with absolute error, Brier score, range coverage and a simple baseline.
- Private per-account CSV research records with immutable forecast cutoffs and data fingerprints.
- CSV example, source manifest, data-generation scripts, forecast CLI, automated tests and original Python code.

## Model and data boundaries

Eight features: 5/20/60-session momentum, distance from MA50, latest volume relative to its 20-session mean, 20-session daily volatility, benchmark momentum and relative momentum. Features are standardized on the training set; ridge penalty is fixed at 10. Targets are 20-session stock return and stock return minus benchmark return.

Training labels finish before a later validation block begins. Six non-overlapping 20-session validation targets supply residuals. The model is not refitted after validation. The displayed range uses their 10th and 90th percentiles, and the beat probability is the smoothed fraction of residual-adjusted excess outcomes above zero. **Six validation periods are very few: these are rough empirical estimates, not a statistically validated 80% confidence interval or calibrated probability.** A point estimate can sit outside the residual range when the small validation set has biased residuals.

The ranking is in decimal return units:

```text
score = expected_excess_return - 0.004
        - 0.5 * max(0, -lower_excess_estimate)
        - 0.1 * (upper_excess_estimate - lower_excess_estimate)
```

The cost term is an illustrative round-trip allowance. Ranking is an experimental rule, not a proprietary theorem or proven market advantage. Only price, volume and benchmark data feed this version. News, fundamentals, announcements and macro factors are not integrated.

Historical prices come from Rohan Rao’s [NIFTY-50 dataset](https://www.kaggle.com/datasets/rohanrao/nifty50-stock-market-data); the benchmark comes from Vinay’s [NSE indices dataset](https://www.kaggle.com/datasets/vinay20/stock-market-nse-indices-daily-data2000). The publishers declare CC0. `data/provenance.json` records URLs, archive hashes, exclusions and limitations. INFRATEL’s file was empty and is excluded. Do not mistake the 2021-era universe for current NIFTY constituents.

Prices are raw and do not credit dividends or corporate-action entitlements. Training/validation windows crossing a daily move greater than 25% are excluded; a recent such discontinuity withholds a forecast. This heuristic cannot identify all corporate actions and can exclude genuine market moves. Constituent selection creates survivorship bias. This is a price-only learning simulation, not a complete total-return backtest.

Replay forecasts are computed now from archived histories cut off at each replay date. They are **not predictions actually published in 2021**. API responses provide only revealed chart observations and settled outcomes, but the underlying historical data is public. The challenge is not a cheat-proof competition.

## CSV format and future forecasts

```csv
date,open,high,low,close,volume,benchmark
2026-01-02,100,103,99,102,150000,25000
```

The single line above only illustrates the format; supply at least 420 complete observations. Use ISO dates, plain decimal numbers and ascending unique dates. `benchmark` is a corresponding daily benchmark close, not its daily return. Use the same adjusted/unadjusted basis for every OHLC field. The app rejects malformed, future-dated, duplicated and inconsistent rows but cannot verify that your source is truthful or fully adjusted.

Keep the same starting date, stock symbol, benchmark label and source label on each update. Upload the entire original history plus new rows. SHA-256 verifies that the original prefix is unchanged. If the provider revises old data, settlement is blocked and marked **history changed** instead of silently rewriting the forecast. Preserve your original CSV for resolution. Existing resolved outcomes are not silently revised.

To generate a forecast entirely locally without launching the website:

```sh
node scripts/forecast-file.mjs public/example-reliance-history.csv work/example-forecast.json
```

Use your own newer CSV in place of the 2017–2021 example. The CLI does not provide account persistence; the web research workspace does. A local daily scheduler could run this command, but no schedule or automatic data download is enabled in this release.

## Accounting and API

New tables: `replay_accounts` and `research_accounts`. Existing `accounts` and `quotes` remain for the legacy prototype. Each new table contains private, revisioned JSON state keyed by the trusted user ID. No client-supplied price or user ID determines fills or ownership. Mutations require same-origin JSON, bounded bodies and authentication. Optimistic concurrency prevents two stale updates from spending the same balance. Replay request IDs deduplicate retries.

Orders enter at a revealed close and fill at the next revealed open. Buy fills apply +0.1% adverse slippage; sells apply −0.1%. Each side charges 0.1% of gross value. Prices, fees, cash and cost basis use integer paise. At most 10 orders can be queued; a challenge allows 250 lifetime orders. Cash and shares are checked both when queued and when filled. Opening gaps can reject buys; pending sells do not fund pending buys in advance. No shorts, leverage, deposits, withdrawals, resets or cash rewards.

Forecasts measure close-to-close returns; trades measure next-open execution and cash allocation. Therefore forecast accuracy and game profit are different. The record logs the top five hypotheses at each visited cutoff; skipping 20 sessions logs the destination cutoff, while equity still updates daily. Overlapping horizons and related stocks produce correlated samples; these metrics are not independent evidence of predictive skill.

## Code map

| Path | Responsibility |
|---|---|
| `app/forecast-dashboard.tsx` | Forecasts, charts, portfolio, CSV workspace and record UI |
| `app/api/lab/route.ts` | Private replay actions and read-only guest snapshot |
| `app/api/research/route.ts` | Private research import and saved forecasts |
| `lib/forecast.ts` | CSV validation, feature extraction, ridge model and outcome scoring |
| `lib/replay.ts` | Server-side historical replay, cash accounting and snapshot filtering |
| `lib/research.ts` | Input fingerprints and persistent prediction lifecycle |
| `lib/server.ts` | Authentication, body limits, same-origin checks and D1 access |
| `db/schema.ts`, `drizzle/` | Persistent schema and incremental migrations |
| `data/` | Reproducible historical training input and provenance |
| `lib/server-data/` | Precomputed replay archive; never import into client code |
| `scripts/prepare-history.py`, `scripts/build-replay.mjs` | Data preparation and past-only forecast generation |
| `research-engine/` | Preserved earlier Python research project |

To regenerate the replay from the included training data: `node scripts/build-replay.mjs`. To recreate training inputs from the original source ZIPs, run `python scripts/prepare-history.py /path/to/download-cache`. Check archive hashes against the committed manifest; upstream changes require a new dataset version and an explicit account migration, not an in-place replacement.

## Checks and deployment

```sh
npm test
npm run typecheck
npm run build
```

Tests cover historical reproduction at fixed cutoffs, input integrity, forecast maturity, no future observations in snapshots, fill timing and costs, cash conservation, partial sales, rejected/cancelled orders, history-change detection, identity isolation, CSRF, stale revisions, duplicate submissions and concurrent requests. Actual route handlers run with a SQLite-backed D1 adapter and mocked gateway identity. They do not validate hosted sign-in end to end.

This release passed 18 automated checks and TypeScript/build validation. The browser preview service timed out, so interactive visual QA remains unverified. See `docs/VALIDATION.md`.

Sites hosts the Worker, provides trusted identity, provisions D1 and applies migrations during publication. The existing Site ID in `.openai/hosting.json` belongs to this deployment; do not invent or reuse it for a separate Site. GitHub is suitable for the source repository. GitHub Pages cannot execute this backend. There are no project API secrets in this archive; do not upload `.env`, `.dev.vars`, `.wrangler`, personal CSVs or account exports.
