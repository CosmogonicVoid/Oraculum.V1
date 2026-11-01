# Milestone 7: local AI evidence briefs

Release 0.7.0, 19 October 2026 (IST). Oraculum remains a local, paper-only
research application. Its application code needs Python 3.12+ and no pip
dependencies. Optional AI requires a separately installed Ollama runtime and
downloaded model weights. There is no paid API, subscription or broker connection.

## Install the update

Close the viewer and daily-run terminals and keep a backup. Extract
`Oraculum-Milestone-7-Update-0.7.0.zip` directly into your existing project
folder containing `run.cmd`, replacing matching files. This patch targets
0.6.0 and contains no runtime databases. Do not put it in the inner Python
package. The complete ZIP is an alternative for a fresh checkout.

```powershell
cd "C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum"
.\run.cmd --version
.\start.cmd
```

Expected: `Oraculum local 0.7.0; core 0.1.0`. The new **Briefs** tab already
provides evidence notebooks for saved reports, even without an AI model.
Keep your existing `%LOCALAPPDATA%\Oraculum\data` directory. Demo data is
separate. Older reports may have less evidence and no captured news.

## Enable local AI

1. Install Ollama from https://ollama.com/download/windows and start it.
2. Reopen PowerShell so the `ollama` command is on PATH.
3. Run `.\ai-setup.cmd` from the project root.
4. After its checks pass, run `.\run.cmd ai-refresh`, then open Briefs.

Setup downloads `qwen3.5:2b` (the tested weights are approximately 2.68 GB),
pins its actual local digest and runs three fictional development checks.
Allow additional disk and RAM for the runtime, context and cache. CPU-only
operation is supported; actual memory needs and speed depend on your PC.
Model weights are not included in either ZIP. Initial installation/downloads
and market refreshes require Internet access; inference uses localhost.

The setup script sets `OLLAMA_NO_CLOUD=1` in its own process environment.
For an already running Ollama app, set that Windows user environment variable
and restart Ollama to disable its cloud features globally. Oraculum itself
only calls `127.0.0.1`, refuses cloud model aliases and remote model metadata,
ignores HTTP proxies and does not send research to a hosted AI service.

If any setup evaluation fails, setup disables AI generation. Ordinary research,
paper accounting and the evidence notebooks remain available. Read the error,
check the model/runtime, and rerun setup. Do not interpret a failed evaluation
as a market prediction. The direct `ai-configure` command is an advanced
configuration operation; unlike the setup script it does not run evaluation.

## What the model actually does

The model selects saved evidence identifiers for a summary, favorable
observations, cautions, comparisons and unresolved information gaps. It also
labels the tone of captured event headlines/excerpts. The application copies
exact evidence snippets and uses fixed comparison/question templates.

**This is AI-selected evidence, not a freely written analyst report.**
Freeform drafting experiments produced unsupported statements, so this release
does not accept model-written prices, financial figures, quotations or prose.
The model can still select poorly, omit important evidence or misclassify tone.
Reference and type validation cannot establish semantic correctness.

Each notebook includes the saved report cutoff, price session, coverage gaps,
source receipts and hashes. Accepted briefs additionally show model identity,
generation time and supporting snippets. JSON and Markdown exports are
available from the detail page. Rejected or failed attempts are withheld from
the accepted brief; the evidence notebook remains readable.

Evidence is bounded to six technical metrics, four financial metrics and up
to seven captured events (three announcements, three news items, one board
meeting), subject to availability and source checks. Screen warnings and
mandatory coverage limitations are attached separately. This is not an
exhaustive scan of every filing, article or market influence. Full articles
and filing PDFs are not read. Missing news is not neutral sentiment.

Source receipt, publication and accounting-period checks exclude information
that was not available by the saved report cutoff. Later news does not enter
an archived brief. A brief generated today about an old report still describes
that old snapshot; generation time does not make it current market research.

## Daily behavior and commands

After successful research/history/paper work, the daily workflow optionally
generates a bounded batch. Defaults: three stocks, 600 seconds per inference,
1,800 seconds per batch. Two consecutive generation failures stop the batch.
Ollama must be running in the local user session. A missing or failed model
does not undo completed research or paper work. A scheduled job can therefore
finish with ordinary research ready and AI unavailable.

```powershell
.\run.cmd ai-doctor
.\run.cmd ai-status --audit
.\run.cmd ai-refresh
.\run.cmd ai-refresh --symbol RELIANCE
.\run.cmd ai-refresh --limit 5
.\run.cmd ai-refresh --symbol RELIANCE --retry
.\run.cmd ai-evaluate
.\run.cmd ai-disable
```

`--retry` retries failed/rejected attempts; accepted selections are reused.
An optional `--report REPORT_ID` pins generation to an archived report.
Configuration can change local model, port, limit, timeout and batch budget:

```powershell
.\run.cmd ai-configure --model qwen3.5:2b --limit 3 --timeout 600 --budget 1800
.\run.cmd ai-evaluate
```

Model changes require explicit reconfiguration and should be reevaluated.
Cache keys bind the evidence packet, local model digest and prompt contract.
Accepted cached briefs can be read with Ollama stopped. Browser GET requests
never run inference or change research data. Model generation is a CLI/daily
operation, not a button that silently starts on page load.

## Persistence and limits

Under the existing data directory, `ai/config.json` stores local settings;
`ai-briefs.sqlite3` stores append-only evidence packets and start/finish
receipts; `ai/` also holds batch/evaluation status. Hashes and immutable SQL
triggers help detect accidental edits; this is not a tamper-proof security
boundary against someone controlling the filesystem. Disabling AI preserves
the journal. Keep normal backups. Do not commit runtime data to GitHub.

The deterministic ranking equations, financial calculations and virtual
portfolio policies are unchanged. Event tone does not alter ranks or orders.
No real trading is implemented. No backtest or three-case model check proves
profitable stock selection. Test symbols in the validation report are examples,
not recommendations.

## What remains

- **Milestone 8:** expand and measure reliable data coverage, investigate source
  gaps, improve operations and evaluate more AI cases across representative
  companies and failures.
- **Milestone 9:** accumulate actual forward paper observations, compare against
  benchmarks and realistic frictions, assess robustness, and decide release
  readiness from evidence. Elapsed market time cannot be generated in a coding
  session.

See `MILESTONE_7_VALIDATION.md` for this build's tested scope and limitations.
