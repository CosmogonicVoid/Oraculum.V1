# Real-data release validation — 0.3.0

Executed on 15 October 2026 (India) / 14 October UTC using Python 3.12.14 on Linux.

## Real exchange data, not the fictional demo

- Downloaded and parsed **60 actual NSE CM UDiFF final files** for **2026-07-21
  through 2026-10-14**, using the reviewed exchange calendar.
- Original first receipts are between **2026-10-14T19:06:14Z** and
  **2026-10-14T19:16:02Z**. Historical availability was not backdated.
- The first attempt encountered a connection failure after 50 files. The failed
  attempt published no partial report. Rerunning reused all 50 files and completed
  the remaining ten. The release additionally retries a broken connection once;
  HTTP denials and invalid data are not retried.
- The final report inspects **2,681** supported stocks:
  **1,132 eligible**, **1,549 excluded**,
  **256 positive setups**, and **10 highlights**.
- Latest-file skips: **983** rows outside EQ/STK/F1, **8** unsupported symbols.
- Feature computation/report export from the complete cache took **2.69 seconds**
  in this environment; no network requests were made in that offline rerun.
  This is a measured run, not a performance guarantee for other computers.
- The 60-file SQLite cache was **32,104,448 bytes**. The report JSON was
  **1,917,164 bytes**. Neither the downloaded archive files nor this cache are
  redistributed in the delivered source package.
- Independently compared reported closes for TCS, RELIANCE and DHAMPURSUG with
  the actual CSV rows read directly from the cached original final ZIP; all matched.
- Exercised the local homepage, complete JSON route and CSV route against this
  real report: all returned HTTP 200 and the expected actual results.

Final report ID:

`70a18ed5835db741ca11cfc38fa87f644f5cd2b5f365c875f04559751699e11e`

Report cutoff: `2026-10-14T19:16:47.570194Z`. Price session: **2026-10-14**.
The daily-bar time is a conservative **16:00 IST** cutoff including post-close
trading; it is not a claim that continuous trading continues until 16:00.

The private user ZIP includes `validation/real-market-2026-10-14.html` plus its
linked CSV and JSON. This is a **dated snapshot**, not an auto-updating report.
Open it to inspect the output immediately; run `research.cmd` for your own current
report. The source-only GitHub archive excludes this validation data.

## Offline regressions

**206 tests pass**, with Python warnings treated as errors. Full output is in
the original 0.3.0 test log. The current `TEST_RESULTS.txt` contains the 0.3.1
run (219 tests); see `WINDOWS_FIX.md` for repair verification. The prior 185 tests still pass; 21 new regressions cover:

- NSE holiday/weekend handling, auction/post-close cutoff and explicit calendar expiry.
- Missing files, incomplete stock histories, duplicate and future receipts.
- Computed features, exact 20% raw-price move exclusion, scoring direction and abstention.
- Cache reuse, interrupted-download recovery and bounded transient-network retry.
- No retries on HTTP access denial; no paper orders or full-engine candidates produced.
- Failed refreshes preserving prior reports and displaying explicit staleness.
- Concurrent-update exclusion, saved-report integrity and safe local report routes.

The original core formula/schema/engine version remain unchanged. The new
`nse-price-watchlist-v1` is a separate, disclosed technical heuristic. Passing
software tests does not demonstrate investment returns or forecasting skill.

## Limits of this verification

- Windows batch files and Python 3.14 were **not run here**. Batch files use CRLF,
  and the packaged GitHub workflow is configured for Windows/Linux on 3.12/3.14.
- Browser routes and generated HTML were checked; no browser screenshot review was
  performed in this environment.
- The public source worked in this session, with one recoverable interruption;
  availability on another network is not guaranteed.
- Fundamentals, news, announcements, adjusted price history, calibrated AI and
  benchmarked performance are not added by this release. Highlights cannot
  authorize trades in the separate paper ledger.
- Calendar coverage ends **2026-11-07**. It needs a maintained update before the
  announced 8 November special session; the program fails outside coverage.
- The optional Ollama path still has mocked adapter tests, not a real local-model
  execution in this environment.
- Your prior database remains byte-for-byte unchanged; its SHA-256 is
  `ec065b706c4de97f032f25bcc781cb26549d8e90e47af94f6d63f9354501fc05`.
- No GitHub repository has been published and no scheduled task has been installed
  on your Windows computer by this delivery.
