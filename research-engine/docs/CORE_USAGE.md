Historical integration guide (2026-10-13). For the current local release, start with README.md and docs/LOCAL.md.

# Oraculum — integrated research and paper-trading project

Integration release: 2026-10-13. Core engine and scoring version: 0.1.0.

This package combines the ChatGPT research core, Qwen's offline CSV adapter and
price features, and Kimi's independent core tests and virtual execution simulator.
The integration review fixed defects and verified all **161 automated tests**.

The supplied instruments and prices are fictional. The equation is a transparent,
untrained research baseline; these tests establish software behavior, not investment
performance. No real money, broker account, live data feed or AI API is connected.

## Start in VS Code on Windows

1. Keep your existing project as a backup. Extract this ZIP into a **new folder**.
2. In VS Code, choose **File > Open Folder** and select the extracted `Oraculum`
   folder containing this README, `pyproject.toml`, `tests` and the lowercase
   `oraculum` package. The project root and Python package are different folders.
3. Open a new PowerShell terminal in that project root. Run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m oraculum demo --no-save
.\.venv\Scripts\python.exe -m oraculum.paper.demo
```

Expected: `Ran 161 tests` and `OK`. The research demo has SIM-ASTER at 79.00 and
SIM-BANYAN at 68.00. The paper demo buys three fictional QW-ALPHA shares, ends
with virtual cash `9609.22`, and reports `repeat_state_unchanged: true`.

No pip installation, credentials or environment activation is needed. A virtual
environment is created locally; an uploaded `.venv` is not used or included.
Your existing `data/oraculum.sqlite3` is preserved byte for byte in this ZIP.
The commands above do not modify that database.

Python 3.12 or newer is required. This delivery was executed on Python 3.12.14,
Linux. Windows/Python 3.14.4 has not been executed here; the same test command
checks your installation. On Linux/macOS, use `python3 -m venv .venv` and
`.venv/bin/python` instead of `.\.venv\Scripts\python.exe`.

## Run the CSV contribution

From the same project root, run these PowerShell commands, one line at a time:

```powershell
.\.venv\Scripts\python.exe -m oraculum.providers.csv_provider --prices examples/qwen/prices.csv --base-bundle examples/qwen/base.json --sessions examples/qwen/sessions.json --output reports/qwen_bundle.json
.\.venv\Scripts\python.exe -m oraculum validate --input reports/qwen_bundle.json
.\.venv\Scripts\python.exe -m oraculum rank --input reports/qwen_bundle.json --output reports/qwen_report.json --markdown reports/qwen_report.md
```

The fictional fixture produces one candidate, QW-ALPHA at about 72.91, and two
excluded instruments. The rank command also saves the research run to the database.
Report folders are created automatically. Existing output files require `--force`
to replace them; input files and databases are protected from export overwrites.

For new supplied data, provide the same three input formats. The CSV adapter does
not download market data. Base sources and non-daily metrics must already be valid
at the requested cutoff, and the calendar must list actual sessions.

## Available components

| Component | Delivered behavior |
| --- | --- |
| Shared contracts | Strict canonical JSON, typed snapshots and extension interfaces |
| Price features | Momentum, trend, volume ratio, volatility, turnover and latest close |
| CSV provider | Supplied calendar, cutoff filtering, missing-session gaps and explicit adjustment vintages |
| Ranking | Nine factors, coverage, risk exclusions, evidence and counterarguments |
| Research history | Immutable SQLite snapshots, canonical hashes and replay verification |
| Exports | JSON and Markdown reports |
| Paper simulator | Explicit orders, raw next-open prices, Decimal accounting, fees/slippage and duplicate prevention |
| Combined demo | CSV research -> ranking -> an explicit virtual order -> execution |
| Verification | 161 tests, CLI workflow checks and clean-archive execution |

There is no automatic candidate-to-order allocation policy. The paper demo uses a
fixed three-share example. The simulator returns portfolio state to its caller;
research runs are persisted, but paper portfolios have no persistent ledger yet.

## Core command reference

Below, `python` means your chosen Python executable. On Windows you can use
`.\.venv\Scripts\python.exe` throughout.

```text
python -m oraculum demo --output reports/demo.json --markdown reports/demo.md
python -m oraculum validate --input examples/demo_bundle.json
python -m oraculum rank --input examples/demo_bundle.json --config config/default.json
python -m oraculum history
python -m oraculum show RUN_ID
python -m oraculum replay RUN_ID
```

Replace `RUN_ID` with the full identifier printed by `demo`, `rank` or `history`.
Use `--database PATH` on history/report commands to select a different database,
or `--no-save` with `demo`/`rank` to calculate without saving. Repeating the same
input/config/engine version returns the first saved report. Commands return status
0 for success and 2 for validation/storage errors.

## Python integration

```python
from oraculum.pipeline import build_run
from oraculum.providers import CsvResearchProvider
from oraculum.paper import BasicPaperSimulator
from oraculum.repository import RunRepository

# canonical_bundle is a validated bundle object or a canonical dictionary.
report = build_run(canonical_bundle)
saved = RunRepository("data/oraculum.sqlite3").save(report)
```

See `oraculum/paper/demo.py` for explicit `PaperOrder`, `PriceBar` and
`PortfolioState` construction. Rejected order IDs are terminal. Hold an order
until its intended session, or use a new ID when deliberately retrying it.

## Work remaining for the full product

- Licensed market data, historical universe membership, reliable exchange calendars,
  corporate-action adjustments and verified point-in-time fundamentals.
- News and corporate-announcement ingestion, with evaluated extraction/sentiment.
- Persistent paper portfolio/order history, allocation, exits, liquidity and sector
  limits, dividends/corporate actions, and realistic transaction-cost assumptions.
- Chronological evaluation against benchmarks before changing the baseline or
  making forecasting claims.
- Scheduling, retries, monitoring, a service API, UI integration and hosting.

This release is a working offline foundation. It does not yet run daily market
scans unattended. The existing website has not been modified.

Read `docs/INTEGRATION_REVIEW.md` for fixes, `docs/VALIDATION.md` for results,
`docs/ALGORITHM.md` for the equation, and `docs/CONTRACTS.md` for interfaces.
The `handoffs` folder preserves the original contributor assignments.
