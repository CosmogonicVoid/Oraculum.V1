# Oraculum

A local, paper-only stock research application for NSE equities. Built with Python's standard library, with optional local AI through Ollama.

**Status:** experimental prototype, local release 0.8.4. Scores are research heuristics, not validated investment predictions. No brokerage integration or real-money execution.

## Features

- End-of-day price/volume screening and financial evidence coverage.
- Ranked research lists with supporting evidence, cautions and source timestamps.
- Graphite interface with translucent panels and keyboard/touch feedback.
- Cached daily candlestick/line charts, volume, and 20/50-session moving averages.
- Separate manual demo account with INR 100,000 virtual cash, confirmed buys/sells, holdings and P/L.
- Automatic forward paper experiment with benchmark tracking.
- Optional saved AI-selected evidence briefs using an existing local Ollama model.

## Run locally

Requires Python 3.12 or later. No Python dependencies need installing.

On Windows, open a terminal in the folder containing `run.cmd`:

```powershell
.\run.cmd --version
.\start.cmd
```

Use `research.cmd` to collect market evidence. Provider availability and the exchange calendar affect refreshes. Opening the viewer does not download data or run AI.

The Python entry point is:

```sh
python -m oraculum.local --help
```

See [the charts and demo trading guide](docs/CHARTS_AND_DEMO_0_8_4.md) for Buy/Sell instructions. Use the Automatic strategy tab to view the separate forward experiment.

## Simulation limitations

Manual demo trades fill immediately at the latest saved close, which can be stale. They do not model fees, slippage, dividends, splits or symbol changes. They are practice bookkeeping, not a realistic performance backtest. The automatic strategy uses a separate ledger and execution policy.

Stock charts show raw, unadjusted prices from the selected report's cached receipts, normally a 60-session window. Ranking metrics may use adjusted prices. Missing data remains unavailable.

## Tests

```sh
python -W error -m unittest discover -s tests -q
```

The 0.8.4 release passed 489 automated tests in the development environment. Native Windows execution and browser visual verification remain unverified. CI is configured to run on Windows and Linux; results depend on the actual workflow run.

## Data and privacy

This repository contains source code and test/example fixtures only. Runtime databases, local settings, downloaded market reports and model weights are excluded. Keep `.env`, database files and personal runtime data out of commits. Never upload the full local delivery ZIP as repository source.

## Next work

More realistic manual fills/costs and corporate actions; longer and adjusted chart history; watchlists and stock comparisons; broader financial coverage; longer forward evaluation; browser and Windows QA.
