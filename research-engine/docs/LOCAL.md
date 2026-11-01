# Automatic workflow in 0.3.1

> Current automatic news collection is documented in [MILESTONE_6.md](MILESTONE_6.md).
> Older manual-engine instructions and historical release scope below remain separate.

For your first real-stock report, run **research.cmd**. It sets up the price
history and bundled calendar automatically; the manual configuration below is
for the separate full research engine and advanced paper operations. See
**REAL_DATA.md** for the new workflow. `run-daily.cmd` now invokes `research`.

## Workspace paths in 0.3.1

Windows real-data commands default to `%LOCALAPPDATA%\Oraculum\data`, and
the demo defaults to `%LOCALAPPDATA%\Oraculum\demo`. Linux/macOS use the
project's `data/local` and `data/demo`. `--data-dir PATH` overrides the default.
Run **repair.cmd** after applying the Windows patch to recover old price downloads.
Old portfolios and manual settings stay in their original folders; use an explicit
`--data-dir` to work with those folders. See **WINDOWS_FIX.md**.

In the manual examples below, **WORKSPACE** means your chosen real-data folder.

# Local operation at a zero-subscription budget

The core needs Python 3.12+, your existing computer and disk space. Network
access is needed for downloads; imported files, reports and paper bookkeeping
work offline. Ollama is optional. There are no OpenAI or other paid AI calls.

Commands below are PowerShell commands from the folder containing `run.cmd`.
On other systems replace `.\run.cmd` with `python3 -m oraculum.local`.

## 1. Prove the local workflow first

```powershell
.\run.cmd doctor
.\demo.cmd
```

The separate fictional demo persists a research run, queues an explicit order
and settles it. Cash finishes at INR 9609.22. It is safe to repeat. Stop the
server with Ctrl+C before opening another viewer on the same port.

## 2. Set up real-data research

```powershell
.\run.cmd init
```

This creates files in your real-data workspace without replacing existing ones:

| File | Your input |
| --- | --- |
| `watchlist.json` | At most 500 supported NSE symbols and explicit sectors |
| `calendar.json` | Complete actual exchange sessions over its declared coverage |
| `supplement.json` | Verified, sourced non-price metrics; initially empty |

The supplied watchlist is an editable configuration example, not a recommendation.
Use uppercase symbols. The original core currently accepts letters, digits,
underscores, periods, colons and hyphens; names containing `&` are skipped and
counted by the importer. Other exchanges/series and financial-sector research
models are outside this local adapter's scope.

The calendar must contain these fields:

```json
{
  "coverage_start": "2026-10-13",
  "coverage_end": "2026-10-14",
  "source_uri": "https://www.nseindia.com/all-reports",
  "sessions": [
    {"session": "2026-10-13", "open_at": "2026-10-13T09:15:00+05:30", "close_at": "2026-10-13T15:30:00+05:30"},
    {"session": "2026-10-14", "open_at": "2026-10-14T09:15:00+05:30", "close_at": "2026-10-14T15:30:00+05:30"}
  ]
}
```

This short format example is **not a year-long calendar**. Replace it with
the complete session list covering your historical warmup period, today's
date and upcoming paper-execution sessions. Verify holidays, special sessions
and their actual hours against exchange notices. `coverage_end` asserts that
all sessions through that date are accounted for; extending it without adding
the actual sessions is incorrect. The program validates consistency and bounds,
but cannot prove that the supplied calendar is factually complete.

The current date must be inside coverage, even on a holiday. Sessions must be
ordered, unique and inside those bounds. A missing stock bar within that calendar
breaks its price-feature window. Do not manufacture a calendar from only the
files you happened to download; that can conceal missing sessions.

## 3. Import prices and build history

Download **CM-UDiFF Common Bhavcopy Final (zip)** from
<https://www.nseindia.com/all-reports>, or use the optional public-file adapter:

```powershell
.\run.cmd fetch-nse --session 2026-10-13
```

For a file you already downloaded:

```powershell
.\run.cmd import-nse --session 2026-10-13 --input "C:\Downloads\BhavCopy_NSE_CM_0_0_0_20261013_F_0000.csv.zip"
```

Replace the date/path with your actual completed session and file. Do not use the
discontinued legacy bhavcopy format or a derivatives file. The parser recognizes
NSE/CM/EQ/STK/F1 rows, uses `TtlTrfVal` as INR, checks OHLC/volume/turnover geometry,
and reports unsupported identifiers and rows skipped outside this scope.

Import at least **50 consecutive actual sessions** for the full price-feature
window, including every intermediate session even if only a small watchlist is
used. One file imports prices for all supported traded stocks for that date;
scans later select the watchlist. The manual import commands do not backfill automatically; `research` performs
the automatic 60-session backfill. The current features use the last 60 calendar sessions of cache.

Raw files, normalized values, source locations and first-receipt times are saved
in `WORKSPACE/market.sqlite3`. Reimporting identical bytes preserves the first
receipt time. Different bytes for an already stored date are rejected; evaluate
a corrected vendor vintage in a new workspace instead of overwriting history.
Cache growth is roughly the sum of daily source files plus normalized records.

Historical files downloaded today are available to this installation **today**.
They can seed today's price history, but cannot support a claim that a strategy
knew their contents months ago. Publication time is conservatively recorded as
receipt time until a verified publication-vintage source exists.

Prices are **raw and unadjusted**. Corporate actions can distort momentum and
volatility. The original Qwen CSV provider supports explicitly supplied adjusted
research vintages; this NSE adapter does not calculate them. Execution always
uses raw prices.

## 4. Supply fundamentals and reviewed news/announcement metrics

An empty `supplement.json` is valid and leaves those inputs missing. Its shape is:

```json
{
  "sources": [],
  "assets": []
}
```

Add sources in the canonical format from `docs/CONTRACTS.md`, and asset entries
of the form `{"symbol":"YOUR_SYMBOL","metrics":{...}}`. Every symbol must
already be in the watchlist. Each metric has `value`, `observed_at`,
`available_at` and `source_ids`. Every non-null value requires at least one
declared source. No price metric may be inserted through this supplement.

Allowed non-price metrics: `roce`, `revenue_growth_yoy`, `debt_to_equity`,
`pe_to_sector_median`, `news_sentiment`, `announcement_impact`. ROCE and growth
are fractions: 0.12 means 12%. P/E-to-sector is a positive ratio, not an absolute
P/E. Sentiment and announcement impact lie between -1 and 1. Treat missing or
undefined figures as missing, not zero. Ratios must have consistent definitions,
reporting periods and sector comparators. Use actual source publication and
first-availability times; do not backdate a newly received filing.

Examples of the shape are in `examples/qwen/base.json`; their numbers and
companies are **fictional**, so never copy them into a real stock's supplement.
The baseline requires debt-to-equity and sufficient factor coverage as well as
price-risk inputs. A price-only workspace will abstain. This is an intentional
incomplete-data result, not a prompt to lower the risk gates.

This release does not automatically acquire or refresh fundamentals, news or
announcements. Expired metrics are handled by the core's configured freshness
rules. Source timestamps validate internal consistency, not vendor truth.

## 5. Scan and view reports

```powershell
.\run.cmd scan
.\start.cmd
```

Or fetch the latest missing final file and scan in one command:

```powershell
.\run.cmd daily --download
```

The latest closed session in your calendar must have a received final snapshot.
Missing/blocked data produces an actionable error, retains existing history and
never silently reuses an earlier session as today's report. Network calls time
out after 30 seconds; no access-control bypass or endless retry is attempted.
Run again later or import the public report manually.

Research is saved in `runs.sqlite3`; immutable JSON and Markdown exports are in
`reports`, all under the selected data directory. `--data-dir PATH` selects a
separate workspace on each command. `--config PATH` accepts the original full
engine configuration; configuration is included in the saved run identity.

The viewer binds only to `127.0.0.1:8765`. It has no file-serving or order-writing
endpoint. It displays the newest 50 saved cutoffs, each run's factors and source
references, and virtual cash/positions. These positions show average cost, not
live market value or verified performance. `serve --port 8766` selects another
local port. This is a local development viewer, not a public hosting service.

The original core can replay a local run (these PowerShell examples use the
Windows default; substitute your chosen path when different):

```powershell
python -m oraculum history --database "$env:LOCALAPPDATA\Oraculum\data\runs.sqlite3"
python -m oraculum replay RUN_ID --database "$env:LOCALAPPDATA\Oraculum\data\runs.sqlite3"
```

## 6. Persistent paper orders

```powershell
.\run.cmd paper-init --cash 100000.00
.\run.cmd paper-status
```

This creates an **imported-data** ledger. Reinitializing with different settings
is rejected. Demo and imported-data ledgers are separate; a real NSE snapshot
cannot settle a synthetic portfolio.

After a valid research run, explicitly record your paper order:

```powershell
.\run.cmd paper-order --order-id MY-FIRST-ORDER --run-id RUN_ID --instrument NSE:YOUR_SYMBOL --side buy --quantity 1
```

Replace placeholders. A buy must be in that run's shortlist. A sell must refer
to an instrument in the saved report and will be checked against owned shares
by the simulator. The command records the current time; it cannot insert a
historical pre-open order. Repeating an identical order ID is idempotent;
reusing it for different details is rejected. This release has no automatic
allocation or exit policy.

Once the next actual session closes and its final raw file is imported:

```powershell
.\run.cmd paper-settle --session YYYY-MM-DD
```

Each order is assigned to the first supplied calendar open strictly after its
submission. An order at/after today's open waits for the next session. You must
settle earlier due sessions before later ones; a later date cannot be chosen
because its price looks better. EOD settlement reconstructs a virtual open fill
for orders committed beforehand. Missing bars produce terminal rejections.

Fees and slippage default to **10 bps each** for demonstration, not a calibrated
Indian tax/cost schedule. Override both using `--fee-bps` and `--slippage-bps`.
Duplicate or concurrent settlement cannot debit cash twice. SQLite transactions
commit fills, rejections and resulting state together. Events form a SHA-256
chain; SQL triggers block ordinary edits. The database owner could still replace
or rewrite the database, so this is an audit trail, not tamper-proof storage.

No dividends, splits, liquidity caps, sector constraints, mark-to-market equity,
return statistics or automatic exits are included yet. Do not treat ledger
balances as an investment-performance backtest. Back up the whole data directory
when the application is stopped.

## 7. Optional local AI

Install Ollama from <https://ollama.com> and select a local model that fits your
hardware. Model weights can be large; no model is downloaded by Oraculum.
Use `ollama list` to see installed names. Check each model's license before use.

Set **OLLAMA_NO_CLOUD=1** in Windows user environment variables and restart
Ollama, following <https://docs.ollama.com/faq>. This must configure the Ollama
server; setting it only in a different client terminal does not change a running
server. Oraculum also refuses cloud-tagged and remote models exposed by
`/api/show`, uses numeric loopback only, and disables proxies and redirects.

Save a supplied news article or announcement as UTF-8 text, at most 12,000
characters. Preserve its true source URL. Then:

```powershell
.\run.cmd analyze-text --input "C:\path\article.txt" --output "C:\path\article-draft.json" --model YOUR_INSTALLED_LOCAL_MODEL --instrument NSE:YOUR_SYMBOL --source-uri https://example.com/the-original-article --kind news
```

Use `--kind announcement` for a filing/announcement. The native Ollama API is
documented at <https://docs.ollama.com/api/generate>. Oraculum has no paid AI
fallback. The adapter requests bounded JSON, refuses unsupported quote text,
stores a document hash and model metadata, and labels the output an unreviewed
draft. Matching a quote does not prove the model's interpretation or entity
attribution is correct. Review against the original source before deriving any
metric. Drafts do not automatically enter ranking or trigger paper orders.

## 8. Run daily on Windows

First make `research` succeed manually. In release 0.3.1, `run-daily.cmd` invokes
the automatic price/volume workflow described in REAL_DATA.md.
Then open **Task Scheduler > Create Basic Task** and configure:

- A daily trigger after the final NSE file is normally available, such as
  19:00 India time. Verify your PC's time zone.
- Action: Start a program. Program: `C:\Windows\System32\cmd.exe`.
- Arguments: `/d /c ""C:\YOUR_PROJECT_FOLDER\run-daily.cmd""`.
- Start in: the folder containing `run-daily.cmd`.
- Run when your user is logged on; enable running a missed task when available.
  Use the setting that prevents a second instance while one is already running.

Replace `YOUR_PROJECT_FOLDER`. The script fixes its working directory and appends
output to `%LOCALAPPDATA%\Oraculum\data\daily.log`; failures return a nonzero exit code. A nonzero Last Run
Result or error in this log needs attention. You may configure a later retry in
Task Scheduler; avoid rapid repeated requests to the public download service.

This schedule performs research only. The separate advanced command
`daily --download --settle-paper` also
settles existing virtual orders with the example cost defaults, after the ledger
and calendar are ready. It still does not create orders. Missed paper sessions
must be imported and settled chronologically before catching up.

Your PC must be awake and connected. GitHub source hosting does not keep this
Python process running when your computer is off. Existing paid ChatGPT access
is neither required by the application nor a substitute for an API budget.

## Data source notes

- Current NSE report names and legacy retirement:
  <https://www.nseindia.com/all-reports>.
- NSE format specifications:
  <https://www.nseindia.com/static/resources/forms-formats-members>.
- Public-download availability is not a guaranteed service or a complete market
  data license. Source publication packages exclude downloaded market files and
  personal ledgers. Retain those locally.

The local layer is a usable step toward the original goal. It does not yet scan
every aspect of the market autonomously or establish that its ranking equation
has predictive value.
