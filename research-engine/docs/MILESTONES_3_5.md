# Oraculum 0.5.0: combined ranking, daily automation and forward evaluation

This release completes the first working implementation of milestones 3, 4 and 5.
It is a local, unvalidated research experiment. It uses no real money, broker,
paid data subscription, cloud AI API or API key. Python 3.12+ is the only runtime.

## Install into the existing project

1. Close the previous viewer with Ctrl+C and keep a backup of the project folder.
2. Extract `Oraculum-Milestones-3-5-Update.zip` into the existing project root:
   `C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum`.
   This is the folder containing `run.cmd`, `research.cmd` and `README.md`.
   Replace matching code files. Do not put the patch in the inner Python package.
3. Open PowerShell in that project root and run:

```powershell
.\run.cmd --version
.\research.cmd
```

The version should be **Oraculum local 0.5.0; core 0.1.0**. The first daily run
starts a separate experiment with INR 100,000 of virtual cash. Existing market
and filing caches are reused. Existing manual paper ledgers remain unchanged.
The patch contains no runtime databases. The complete `Oraculum.zip` also
preserves the original private research database; do not use it as a public
GitHub upload. Use `dist/oraculum-source.zip` for public source.

`research.cmd` runs the daily workflow and opens the local viewer. `run-daily.cmd`
runs the same workflow without starting a viewer. `start.cmd` only opens the
saved results. A failed paper phase may leave a successfully published research
report: the viewer shows the failed phase separately. Rerun to resume.

## Milestone 3: a combined research score

The existing adjusted technical score T remains visible and unchanged. The new
combined score is:

    S = 0.60*T + 0.10*G + 0.10*M + 0.10*L + 0.10*R

All factor scores are between 0 and 100. `clip(x,0,1)` caps a value to that range.
Ratios below are decimals: 10% is 0.10.

| Factor | Input | Factor score |
|---|---|---|
| T | Existing adjusted momentum/trend/volume/volatility score | Existing 0–100 score |
| G | Quarter revenue growth versus the same quarter a year earlier | `100*clip((growth+0.10)/0.40,0,1)` |
| M | Quarter net profit / revenue | `100*clip(margin/0.20,0,1)` |
| L | Current + noncurrent borrowings / total equity | `100*clip(1-leverage/2,0,1)` |
| R | Annual ROCE using mean opening/closing capital employed | `100*clip(ROCE/0.30,0,1)` |

The input definitions, filing periods, units, freshness and source-availability
checks from 0.4.0 still apply. Every required metric must be available. Missing
values withhold the combined score; available factors are not reweighted.
Every factor's contribution is saved in the report. Ranking ties use the symbol.

A combined candidate additionally needs all existing technical filters, positive
20-session momentum and 50-session trend, score at least 60, and the separate
financial screen: revenue growth > 0, margin > 0, borrowings/equity 0–1.5,
and ROCE >= 10%. Up to ten candidates are highlighted. Complete profiles that
fail a candidate rule can still be inspected in the combined ranking.

For example, T=80, growth=10%, margin=10%, leverage=0.5 and ROCE=15% give factor
scores 80, 50, 50, 75, 50 and a combined score of **70.5**. This is an illustrative
calculation, not a 70.5% probability of profit. Weights and cutoffs are declared
baseline choices, not fitted or validated predictive coefficients.

Annual-EPS P/E and cached-peer P/E remain visible as diagnostics. They are not
scored because matched peer coverage is sparse. News and general announcements
remain unassessed. This version does not claim to cover every market input.

Report schema: `oraculum-integrated-research-v2`. Algorithm: `nse-combined-v1`.
Older price-only and integrated-v1 reports still open with their original values.

## Milestone 4: daily workflow and immutable history

`auto-daily` performs these operations in order:

1. Recover the index of preserved older/interrupted reports.
2. Download missing final price sessions and resume the bounded financial batch.
3. Calculate adjusted technical and combined rankings.
4. Save the hashed JSON, CSV and HTML report and its append-only history index.
5. Advance previously committed paper plans, then record this session's first
   new decision using information available now.

A database lock prevents overlapping daily jobs. The research workflow has its
own lock. Process exit releases locks. Completed downloads remain cached; retries
do not erase inputs or make duplicate paper trades. A failed research phase does
not advance paper evaluation. A failed paper transaction leaves the previous
paper state intact and identifies the error while preserving the new research.

Every refresh retains a distinct dated report, including repeated coverage
updates for the same price session. The paper experiment uses **the first
committed decision per price session**. Later financial downloads cannot rewrite
that earlier decision. Missed days get no reconstructed selections.

Data is stored in `%LOCALAPPDATA%\Oraculum\data` on Windows:

| Item | Purpose |
|---|---|
| `market.sqlite3`, `evidence.sqlite3` | Original prices, filings and receipts |
| `research/` | Hashed reports and current report pointer |
| `research-history.sqlite3` | Immutable report index |
| `forward.sqlite3` | Separate automatic virtual experiment |
| `automation/status.json` | Current daily-job phase and failure state |
| `automation/daily.log` | Rotating log: 2 MiB per file, three backups |
| `automation/run-*.json` | Dated run outcomes |

The website adds Daily history and Forward paper evaluation pages. All HTTP
routes remain read-only and bound to localhost. Viewing a new installation does
not create paper or research databases.

### Install Windows scheduling once

From the same project folder:

```powershell
.\run.cmd schedule-install
.\run.cmd schedule-status
```

Or double-click `install-schedule.cmd`. The task uses the current Python
executable and project folder, runs at **19:00 and 21:00 computer-local time**,
and also runs when that Windows user signs in. Check that the PC's timezone is
India if those should be IST times. The second evening run adds coverage and
provides another chance after a delayed final file; it cannot duplicate a
session's paper decision.

The task uses the current user's interactive account with limited privileges.
It requests no password or administrator rights and changes no execution policy.
The PC must be awake, plugged in, the user signed in, and a network available.
Start-when-available is enabled; missed selections are still not backdated.
A task name belonging to another project installation is not overwritten.
After moving the project, remove the task from the old folder before reinstalling
from the new folder. A running viewer is not necessary for the daily job.

```powershell
.\run.cmd schedule-remove
```

The installer is prepared and its invocation/guards are tested. Native Windows
Task Scheduler cannot be executed in the Linux build environment; installation
is verified on your PC by `schedule-status` and the next run's log.

Microsoft references used for the installer:
- https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal
- https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset
- https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask

## Milestone 5: forward paper experiment

This uses its own `forward.sqlite3`, leaving the earlier manual ledger and its
research-engine authorization rules unchanged. It never calls a broker.

- Start with INR 100,000 virtual cash by default; initial cash can be selected
  on the first `auto-daily --cash AMOUNT` call. Existing cash is never reset.
- At most five simultaneous positions. Each new position's budget is at most
  20% of initial cash and is capped by free cash. No leverage or short sales.
- Choose combined highlights in rank order, skipping held/pending symbols.
- Commit an integer quantity based on the known raw close, modeled costs and
  a 5% sizing buffer. Quantity is fixed before the next scheduled session opens.
- Simulate entry at that session's raw open plus 10 bps slippage, with 10 bps
  fees. Cancel if no traded quote, identity changes, an action occurs, the order
  exceeds reported daily volume, or the opening gap breaches its cash budget.
  Quantity is never resized after seeing the opening price.
- Keep each position for 20 completed market sessions, including entry day.
  At the next traded open, sell with 10 bps slippage and 10 bps fees. This exit
  rule is committed in advance and can be settled after computer downtime.
  A missing quote postpones the exit; there is no invented liquidation price.
- Compare equity to a separate NIFTYBEES buy-and-hold experiment with the same
  initial cash, fixed pre-open sizing, modeled costs and residual cash. A
  cancelled benchmark entry is retried at a later committed decision. Until
  the benchmark enters, its return comparison is withheld. This is an ETF/cash
  proxy, **not the official index total-return series**.
- Mark positions at raw closes and include cash and dividend receivables.
  Report equity, net return, benchmark difference, observed daily drawdown,
  closed-trade outcomes, fees and slippage. Daily CSV/JSON records are available.

Explicit integer split/bonus entitlements change quantities. Fractional
entitlements, unsupported or conflicting actions, unreviewed identity changes,
and changed previously settled action records pause evaluation for review.
Dividends become an **unspendable receivable** on the ex-date; payment dates are
not provided, so the engine does not pretend that cash has been paid. Share
entitlements are an economic simulation, not a model of settlement availability.

Missing held prices retain a clearly stale last mark. Current strategy return
and/or benchmark comparisons are withheld as appropriate. A missing entire
scheduled-session file blocks chronological settlement. Known raw files must
cover every unsettled session; after unusually long downtime, additional
`fetch-nse --session YYYY-MM-DD` calls may be required beyond the 60-session
research backfill. Calendar updates must also cover that entire gap.

Events and state snapshots are append-only and hash-chained. Repeating a daily
run or concurrent invocation cannot double-debit cash. Both strategy and
benchmark are committed atomically. Strategy and ranking policy fingerprints
prevent an existing experiment silently switching rules.

Opening fills and queue priority are assumed, not observed. Costs are research
estimates rather than a broker/tax tariff. Sector concentration, stop-losses and
predictive ML are not part of this baseline. Software tests use fictional
scenarios to verify accounting and timing; real performance must accumulate
in future sessions.

## Useful commands

```powershell
.\run.cmd auto-daily                         # refresh + paper; no viewer
.\run.cmd auto-daily --max-filings 120       # larger bounded filing batch
.\run.cmd auto-daily --no-paper              # research/history only
.\run.cmd research --integrated              # combined report only
.\run.cmd forward-status                     # full virtual experiment JSON
.\run.cmd research-history --recover         # index preserved old reports
.\start.cmd                                  # view saved results
```

Offline mode needs a complete current price cache and fresh metadata. It does
not silently ignore expired metadata or fabricate missing prices.

The bundled calendar remains reviewed only for **1 July–7 November 2026**.
Install a reviewed calendar update before the 8 November special session. Jobs
stop outside that coverage. Financial downloads remain partial and support
nonfinancial IndAS statements; other schemas and complex corporate events need
further work. News analysis, predictive modeling, broader coverage and proven
investment performance are future milestones.
