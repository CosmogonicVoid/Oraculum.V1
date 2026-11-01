# Legacy raw-price research — local release 0.3.1

> Current automatic news collection is documented in [MILESTONE_6.md](MILESTONE_6.md).
> Older manual-engine instructions and historical release scope below remain separate.

The default Windows launchers now use the 0.4.0 integrated workflow described in
[DATA_FUNDAMENTALS.md](DATA_FUNDAMENTALS.md). This page retains the legacy method
for `run.cmd research` without `--integrated`.

## Data-folder defaults

Windows stores market data in `%LOCALAPPDATA%\Oraculum\data`; Linux/macOS
use the project's `data/local`. In the paths below, **WORKSPACE** means that
folder, or the explicit folder supplied with `--data-dir`. The demo has its own
separate default. Existing Windows users can run **repair.cmd** to recover old
price downloads; see **WINDOWS_FIX.md**.

## One command

Run `.\research.cmd` from the project root in Windows PowerShell, or double-click
it. Python 3.12+ is the only software dependency. There is no paid API or model
call. This release uses deterministic price/volume features; optional Ollama
summaries are a separate capability.

The program chooses the latest **completed** session in its reviewed exchange
calendar, retrieves the final NSE cash-market files for it and the preceding
59 sessions, caches them, and builds a report. Before the market closes, the
latest completed session is the previous trading session. Shortly after close,
the final file may not yet be published: rerun later if NSE cannot serve it.
The program never labels an older snapshot as today's market.

Downloads are sequential and cached. Each request has a 30-second network timeout.
A broken connection or timeout receives one retry after two seconds. HTTP errors
(including access denials and absent files) and malformed data are not retried.
Failed setup preserves completed files. Rerunning resumes. First setup can take
several minutes. Afterward a normal new session needs one file. The cache grows
over time; use `doctor` to check available disk space.

## What is ranked

The universe is every supported, traded **NSE CM / EQ / STK / F1** row in the latest
final file. Other series, instrument types, session types, zero-trade rows and
unsupported symbols are counted as skipped. The original identifier contract
does not accept an ampersand, so symbols such as M&M are skipped in this release.
This is not full coverage of NSE/BSE, derivatives, ETFs or all listed securities.

Missing observations break a stock's consecutive-session window. No price is
filled forward. A new listing without 50 consecutive observations is excluded.
Every global session file must exist; a missing file blocks the new report.

Eligibility requires:

- At least 50 consecutive traded sessions ending at the report's latest session.
- Average **actual traded turnover** over 20 sessions >= INR 50,000,000 (5 crore).
- Sample standard deviation of the last 20 simple returns × sqrt(252) <= 0.80.
- Every adjacent raw close-to-close move within the last 50 closes has absolute
  magnitude < 20%. This anomaly filter does not identify corporate actions.

Prices are raw. A split, bonus, dividend, merger or symbol change can distort the
features. The extreme-move filter catches only some distortions. No dividend,
split or bonus adjustment is inferred from a price change.

## Reproducible formula

Algorithm identifier: `nse-price-watchlist-v1`.

Let `clip(x,a,b) = min(b,max(a,x))`:

```text
m = latest_close / close_20_sessions_ago - 1
t = latest_close / mean(last_50_closes) - 1
v = latest_volume / mean(previous_20_volumes)
s = sample_std(last_20_simple_returns) * sqrt(252)

M = 22.5 * clip(m / 0.20, -1, 1)
T = 17.5 * clip(t / 0.15, -1, 1)
V = 10 * sign(m) * clip((v - 1) / 2, 0, 1)
R = -15 * clip((s - 0.20) / 0.60, 0, 1)
score = clip(50 + M + T + V + R, 0, 100)
```

Score is stored to six decimal places. Sort descending by score, then ascending
symbol for a stable tie break. The page highlights at most the first ten eligible
stocks with `m > 0`, `t > 0` and `score >= 55`. It can highlight none. Low latest
volume supplies no confirmation bonus; high volume confirms momentum's direction
and therefore penalizes negative momentum rather than rewarding it.

These weights and thresholds are chosen research heuristics, not trained or
validated market discoveries. A score of 80 does not mean an 80% chance of profit.
The report also shows the one-session return, 50-session maximum peak-to-trough
drawdown, turnover, volume and annualized volatility, plus numeric explanations.

This report has a separate schema from the original `bounded-factor-baseline-v1`
buy engine. It does not insert candidates into `runs.sqlite3`, bypass debt or
fundamental gates, authorize paper orders or fabricate neutral news values.

## Calendar and source maintenance

The bundled schedule covers **2026-07-01 through 2026-11-07**. It was reviewed on
2026-10-14 using these NSE primary sources:

- [Capital-market holiday circular NSE/CMTR/71775](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf)
- [NSE market timings and holidays](https://www.nseindia.com/resources/exchange-communication-holidays)
- [NSE closing auction and post-close sessions](https://www.nseindia.com/static/products-services/closing-auction-session)
- [NSE daily reports](https://www.nseindia.com/all-reports)
- [NSE file-format resources](https://www.nseindia.com/static/resources/forms-formats-members)

Within this period, the 14 September, 2 October and 20 October holidays are
excluded. The daily bar uses 09:15 IST as its start and **16:00 IST as a conservative
whole-day cutoff including post-close trading**. This does not mean continuous
trading lasts until 16:00: NSE lists CAS through 15:35 for eligible securities
and post-close through 16:00. The final bhavcopy may be published later; an
actual received final file is still required. The announced **8 November 2026
Muhurat session needs verified special hours**. The calendar stops before that
date and must be maintained; it is not automatically sourced from changing
exchange notices. Unexpected closures/special sessions also need an update.
A download error cannot create a new holiday.

Advanced users can supply a complete sourced calendar:

```powershell
.\run.cmd research --calendar "C:\path\complete-nse-calendar.json"
```

Its schema is the same as the explicit calendar in `docs/LOCAL.md`. The generated
bundled schedule is saved as `WORKSPACE/calendar-auto.json` after a successful
run. Your existing `calendar.json` and `watchlist.json` are not overwritten or
silently used by this whole-universe workflow. The custom calendar must cover
the current Indian date and at least 60 completed sessions, including specials.
Supplying a calendar is a claim about completeness; the software cannot
independently verify a user-authored schedule.

The final-file pattern is:

```text
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
```

The importer validates row dates, segment/series, OHLC geometry, nonzero volume,
finite prices and actual turnover units against each row's price/volume range.
No login challenge or access restriction is bypassed. Public files have no
availability guarantee. Use data in accordance with the provider's terms; raw
downloaded files and private databases are not bundled in the GitHub source ZIP.

## Saved files and audit

| Local path | Contents |
| --- | --- |
| `WORKSPACE/market.sqlite3` | Immutable snapshots, first receipts and hashes |
| `WORKSPACE/research/<report-id>.json` | All results, settings, source hashes and calendar |
| `WORKSPACE/research/<report-id>.csv` | Every inspected stock and exclusion |
| `WORKSPACE/research/<report-id>.html` | Standalone readable report |
| `WORKSPACE/research/latest.json` | Pointer to the last complete report |
| `WORKSPACE/research/status.json` | Current/last attempt, failure or completion |
| `WORKSPACE/calendar-auto.json` | Schedule used by the last successful run |
| `WORKSPACE/workflow.sqlite3` | Process lock, automatically released on exit |

Each report ID is SHA-256 of canonical content excluding the ID itself. Cache
and report hashes are checked on read. The last-report pointer is replaced only
after JSON, CSV and HTML are written. A failure never replaces a good report with
a partial ranking. The viewer flags failed updates when status writes succeed and sessions older
than the latest completed session. A locked progress file prints a warning in the
terminal and does not prevent report generation; progress shown in the viewer
can remain outdated until the file is writable. Standalone HTML freshness is recorded at export time;
always read its session date when opening an old file.

Actual first-receipt times are retained. Downloading July history in October does
not make it eligible for a July point-in-time backtest. Current-universe rankings
also cannot establish historical performance or account for delisted companies.

The read-only viewer binds to 127.0.0.1, uses no remote web assets and exposes no
order endpoint. `/` opens the real-data report; `/history` retains access to the
separate full-engine runs and virtual portfolio. CSV/JSON are also available
through local read-only routes.

## Windows scheduling (optional)

After a successful run, use Windows Task Scheduler:

1. Create a basic task named `Oraculum daily research`, triggered daily at 18:30
   **your computer's local time**. The intended zone is India; adjust the trigger
   if your computer uses another zone.
2. Program: `C:\Windows\System32\cmd.exe`.
3. Arguments: `/d /c ""C:\path\to\oraculum\run-daily.cmd""`.
4. Start in: the project folder containing `run-daily.cmd`.
5. Use your own logged-in account, run missed tasks when next available, avoid
   overlapping instances, and keep the PC awake and connected.

`run-daily.cmd` now invokes **research**, replacing its old manual `daily --download`
invocation. Weekend/holiday runs reuse the latest completed session. Logs append
to `%LOCALAPPDATA%\Oraculum\data\daily.log`; inspect errors there and open `start.cmd` for the report.
The process lock also prevents overlaps. Extracting the ZIP installs no scheduled
task on your computer.

If the viewer is already running, use `.\run.cmd research` and refresh. If port
8765 is occupied by a demo serving a different folder, stop that terminal first.
Advanced alternate port: `.\run.cmd serve --port 8766 --open-browser`.

## Next milestones

Release 0.4.0 adds supported corporate-action adjustments and sourced financial
metrics with explicit partial coverage. Remaining work: broader schema/action
support and complete financial backfill; automated news collection and entity matching; maintained exchange
calendar updates; frozen daily recommendations followed by measured forward
outcomes and a benchmark; portfolio allocation and exit policies. These remain
separate work, and this release does not claim they are complete.
