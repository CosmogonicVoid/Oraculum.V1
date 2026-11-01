> Version note: This document describes the 0.4.0 data layer. Release 0.5.0 adds
> combined ranking and a separate automatic forward experiment; see
> [MILESTONES_3_5.md](MILESTONES_3_5.md) for current launchers and scoring.

# Data and fundamentals integration — local release 0.4.0

This release joins two workstreams in one local workflow: corporate-action-aware
price research and automatic financial statement evidence. Python 3.12+ and its
standard library are sufficient. There is no subscription, API key, broker,
external AI request or order placement in this workflow.

## Run or update

For an existing 0.3/0.3.1 installation, close the viewer, back up the project, and
copy the contents of `Oraculum-Data-Fundamentals-Update.zip` into the folder that
contains `run.cmd` and `research.cmd`. Replace matching source files. The update
ZIP has no enclosing project folder and contains no databases or runtime caches.
It must not be copied into the inner Python-package folder.

For this installation, the project folder is:

```text
C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum
```

Then run from PowerShell:

```powershell
cd "C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum"
.\run.cmd --version
.\research.cmd
```

The version must say **Oraculum local 0.4.0**. `research.cmd` calls
`research --integrated`, builds the combined report and opens the read-only viewer
at `http://127.0.0.1:8765`. Keep its terminal open while using the viewer.

Real-data caches and reports remain in `%LOCALAPPDATA%\Oraculum\data` on Windows.
The old private `data/oraculum.sqlite3`, virtual ledgers, manual supplements and
configuration are not changed by the integrated scan. If upgrading from the
pre-0.3.1 folder problem, use `repair.cmd` once; its cached-price recovery now
continues into the integrated scan.

Other commands, from the same project root:

```powershell
.\run.cmd research --integrated                  # update without opening a second viewer
.\run.cmd research --integrated --max-filings 200 # larger resumable filing batch
.\run.cmd research --integrated --max-filings 0   # refresh metadata/prices; no new filing downloads
.\run.cmd research --integrated --offline        # no network; requires current valid metadata and price cache
.\start.cmd                                     # view last successfully saved report
.\run.cmd research                              # explicitly use legacy raw-price-only research
```

On Linux/macOS, use `python3 -m oraculum.local` in place of `.\run.cmd`.
`run-daily.cmd` also uses integrated mode. Existing Task Scheduler setup can keep
calling that file; this update does not create a scheduled task for you.

## Batches, recovery and failure behavior

- Every required one of the 60 scheduled price files must be available.
- The security master, symbol-change list, corporate-action coverage and filing
  catalogue must load successfully. Metadata is cached for at most 24 hours;
  actions and catalogue are also scoped to their requested dates. An empty error
  response is not treated as complete corporate or financial coverage.
- Individual financial statement downloads are limited to **60 attempts per
  run**, configurable from 0 to 10,000. Highlights are handled first, then
  technically eligible stocks ordered by actual traded turnover, then others.
  The selected latest quarter, year-ago quarter, annual and prior-annual filing
  need at most four distinct documents per stock. Some periods share one file.
- Rerunning extends coverage using the immutable cache. A whole-market backfill
  can need thousands of documents and many batches; the first scan is explicitly
  partial. Larger batches take longer and remain subject to exchange access.
- A failed document receives a 24-hour cooldown. HTTP 401, 403 or 429 stops the
  filing batch immediately without retries or attempts to bypass source access.
  Remaining metrics are marked missing; a partial report can still be saved.
- A blocked critical metadata source or missing required price session fails the
  update. The previous latest-report pointer remains intact. The viewer shows the
  previous report with a failure/staleness notice when status can be saved.
- No download time is backdated to a financial period or an exchange publication.
  Already verified successful filing downloads retain their first local receipt.
  The document key includes both URL and publication/revision time: a revised
  filing cannot silently reuse older bytes at the same URL.
- A lost connection or Ctrl+C does not erase completed downloads. Run again to
  resume. A process lock prevents two research refreshes from overlapping.

## Market universe and identity

The latest NSE final CM UDiFF file defines the current universe: traded EQ-series,
STK instruments in session F1. The extended research parser accepts identifiers
such as `M&M` and `J&KBANK`; it reads ISIN, exchange identifier and company name.
It reparses original cached bytes without changing the old price payload or
its source identity. Core contracts and earlier report replays remain compatible.

History joins use dated official symbol changes, never a fuzzy company-name
match. An unexplained ISIN change breaks continuity. A split/bonus can explain a
same-date ISIN change; mismatched action and adjacent-price ISINs block adjustment.
The current security-master ISIN must agree with the latest price identity before
financial filings are joined. Older filing tickers are accepted only when a dated
official symbol change confirms the alias at publication; the ISIN must still match. Old-ISIN filings after a share-capital change are
withheld for manual identity review in this release.

This does not add BSE, ETFs, derivatives, every security series, delisted stocks,
or a historically survivorship-free universe. An unexplained missing stock row
still breaks its consecutive trading history.

## Corporate-action math

Original OHLC, volume and actual traded turnover remain unchanged in storage.
The report's `close_inr` is the raw quote, and paper settlement continues to use
raw execution prices. Only research close history and split/bonus volume are
adjusted backwards, before each ex-date.

| Supported event | Price factor on earlier closes | Volume factor on earlier sessions |
| --- | --- | --- |
| Bonus `new:old` | `old / (old + new)` | inverse price factor |
| Face value split/consolidation | `new face value / old face value` | inverse price factor |
| Explicit cash dividend `D` | `(previous raw close - D) / previous raw close` | 1 |

Multiple explicit cash amounts within one exchange entry are summed. Separate
same-day records are withheld because they may be revisions or duplicates, rather
than additional entitlements. Decimal arithmetic
preserves fractional adjusted volume, e.g. a 2:5 bonus on 101 old shares becomes
141.4 normalized shares, not 141. Actual turnover is never reconstructed as price
multiplied by adjusted volume. Dividend adjustment is a price-history convention,
not an exact dividend-reinvestment total-return index.

Rights issues, demergers, ambiguous distributions, mixed same-day share actions,
invalid ratios, missing ex-date prices, and conflicting identities block technical
eligibility. The parser does not infer unknown action economics. Meeting-only
entries cause no adjustment. Future ex-dates do not change historical features.
Coverage still depends on the completeness of the exchange's public data.

The technical formula and thresholds remain the previous disclosed heuristic,
but its momentum/trend/volatility/drawdown inputs now use adjusted closes and its
volume ratio uses split/bonus-adjusted volume. The 20% extreme-move filter applies
to adjusted daily moves. Breadth is explicitly labelled as raw latest-session
price changes. The JSON exposes every applied factor and action subject.

## Financial extraction and metrics

The financial catalogue uses NSE Integrated Filing–Financials, including its
reported publication, dissemination and revision times. The newest known filing
for each company/basis/period is selected before downloads; a missing latest
revision never falls back to an older revision. Consolidated is preferred at the
latest quarter when available, and one reporting basis is used throughout a
company's profile.

Only general IndAS instance XML is supported. Bank, NBFC, insurance and other
specialist schemas are explicitly unavailable. XML is bounded, disallows DTDs,
entities and unsupported encodings, and never retrieves external schemas.
Declared namespaces, units and context periods are checked. Dimensioned segment
facts are not mistaken for company totals. Conflicting duplicate totals reject
the document. `xsi:nil` is missing, zero is zero, and losses remain negative.
XBRL `decimals` describes precision; amounts already in INR are **not** scaled
again by lakhs or crores.

| Metric | Exact definition and requirements |
| --- | --- |
| Quarterly revenue YoY | Current-quarter revenue / same prior-year quarter revenue − 1. Prior revenue must be positive; matched quarter dates and basis; latest quarter at most 180 days old. |
| Quarterly net margin | Group profit/loss for the quarter / revenue from operations. Revenue must be positive; latest quarter at most 180 days old. |
| Borrowings/equity | (Current borrowings + noncurrent borrowings) / total equity. Both debt components required, equity positive. Uses latest quarter balance if present, otherwise selected annual balance; at most 240 days old. Excludes lease liabilities. |
| Annual ROCE | (Annual profit before tax + finance costs) / average opening and closing (assets − current liabilities). Both capital bases must be positive. Full-year duration 330–380 days; annual period at most 450 days old. No quarter annualization or invented opening balance. |
| Annual-EPS P/E | Latest raw close / positive basic EPS for the supported full year. Not TTM. Withheld if action coverage starts too late or any non-cash/share-related unresolved action occurs after year-end. |
| P/E / cached-peer median | Own annual P/E divided by the median of at least five other cached, positive-P/E peers with identical current industry, basis and fiscal-year-end. Peer identities and count are disclosed. |

Annual document selection currently targets March year-ends. Non-March reporters
can still have quarterly metrics but their annual metrics require a later
extension. Latest-quarter debt may use the annual balance when that quarter has
no balance statement; the displayed balance date makes this visible. A stale or
unsupported newer balance is not silently replaced with an older one.

Every available metric records its formula, accounting periods, source IDs and
availability time. P/E also records the price and action evidence; peer valuation
includes industry mapping evidence. Industry mapping covers only current Nifty
Total Market constituents, not every NSE company. It is not used to reconstruct
historical membership. The peer sample is incomplete and changes as data fills.

## Ranking and the financial screen

**Technical ranking is still price/volume-based.** Financial statement metrics
appear alongside it; they are not silently mixed into the score with new weights.
The original full-engine formula and paper-order permissions remain untouched.

A separate, fully disclosed financial screen requires all four fresh metrics:
revenue YoY > 0, net margin > 0, borrowings/equity between 0 and 1.5 inclusive,
and annual ROCE ≥ 10%. It reports `passes`, `does_not_pass`, or `not_assessed`.
These cutoffs are unvalidated research filters, not predictions or financial
advice. A technical highlight can fail or lack the financial screen; the report
shows that state. Missing information never becomes zero or an automatic pass.

No automated news sentiment, general announcement analysis, trained model,
portfolio allocation, exits or benchmark-tested forward performance is added by
this release. No claim of a profitable or exclusive market equation is made.

## Files and compatibility

New code: `nse_evidence.py`, `corporate_actions.py`, `financials.py`,
`integrated_research.py`, `integrated_view.py`.
New runtime cache: `evidence.sqlite3`, an append-only, checksum-verified evidence
store; `fundamental-attempts.json` holds failed-download cooldowns only.
New report schema: `oraculum-integrated-research-v1`.
Old `oraculum-price-research-v1` reports still open in the same viewer.
CSV includes all stocks, metric values, periods, coverage, blockers and notes.
Standalone HTML, CSV, JSON and the latest pointer are published in that order
of dependency; the pointer only advances after all report files exist.

The included reviewed calendar still expires on **7 November 2026**. Future
session maintenance is a separate task. Windows launchers retain CRLF and the
existing `%LOCALAPPDATA%` behavior. Native Windows execution must be checked on
your computer; development validation used Linux/Python 3.12.

## Primary sources

- NSE securities master and official symbol-change downloads:
  https://www.nseindia.com/static/market-data/securities-available-for-trading
- NSE corporate-action records:
  https://www.nseindia.com/companies-listing/corporate-filings-actions
- NSE Integrated Filing–Financials:
  https://www.nseindia.com/companies-listing/corporate-integrated-filing
- NSE XBRL information and taxonomy:
  https://www.nseindia.com/static/companies-listing/xbrl-information
- Nifty Total Market constituent industry mapping:
  https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-total-market

Source access succeeded during development on 16 October 2026. Public endpoint
availability and formats are not guaranteed. There are no credentials, cookies,
proxy workarounds or subscription assumptions in the downloader. Raw exchange
caches are not bundled in the public GitHub source archive.
