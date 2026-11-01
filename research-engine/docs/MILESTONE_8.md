# Milestone 8 — coverage and operational reliability

Local release 0.8.0, 20 October 2026. Python 3.12+, application dependencies:
standard library only. Optional inference still uses your configured local
Ollama model. No recurring service or paid data/API has been added.

## Apply this update

Close Oraculum's viewer and update terminals and back up the project. Extract
`Oraculum-Milestone-8-Update-0.8.0.zip` into the existing folder containing
`run.cmd`, replacing matching files. The patch targets 0.7.0 and contains no
runtime databases. Do not extract into the inner Python package.

```powershell
cd "C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum"
.\run.cmd --version
.\start.cmd
```

Expected: `Oraculum local 0.8.0; core 0.1.0`. Open **Coverage**. Existing reports
work immediately; new heartbeat and filing-policy details appear on the next
run. Your data stays in `%LOCALAPPDATA%\Oraculum\data` and your existing AI
configuration, model weights, report history and virtual portfolio are retained.
Do not rerun AI setup or download another model merely to install this update.

## Coverage notebook

The Coverage page shows the number of scanned stocks, four-input financial
coverage, combined eligibility, per-input gaps and the last report's filing
batch. Search by company/symbol and filter incomplete profiles, technical
exclusions, unsupported schemas, identity/filing review and older financials.
Each stock links to its report-pinned analysis. CSV and JSON exports include
matching rows (up to 10,000); the page displays 40 rows at a time.

An input is evidenced here only if its value is finite, its referenced source
receipts exist in the report, and its availability, receipts and accounting
periods do not exceed the report cutoff. The page is diagnostic: it does not
recalculate rankings or claim that cited sources are true. A coverage count may
be stricter than a legacy report's original profile count; the original ranking
is preserved. Unknown values never become zero or neutral observations.

Financial ages are measured at the saved report cutoff. The review filter
flags quarters over 180 days old; this is a disclosed operational threshold,
not a legal filing deadline or a new scoring rule. Current price freshness is
shown separately using the saved report's calendar. Outside calendar coverage,
freshness is unknown. The existing bundled calendar still ends 7 November 2026;
this release does not invent later sessions or special-session hours.

Missing inputs have different causes. Another bounded run can collect queued
documents. It cannot resolve unsupported bank/insurance schemas, missing
catalogue entries or conflicting company identity by itself. This release
does not add BSE, all historical listings, full news articles or specialist
financial parsers. Coverage is measurable and recoverable, not universal.

```powershell
.\run.cmd coverage-status
.\run.cmd coverage-status --symbol RELIANCE
.\run.cmd coverage-status --filter incomplete
.\run.cmd coverage-status --report YOUR_SAVED_REPORT_ID
```

These commands only inspect local records; they do not download, infer or trade.

## Understand progress and resume

Each locked workflow writes a best-effort heartbeat every ten seconds.
Detailed price and filing messages now include a last-progress timestamp.
Price-history completion (for example, 60/60 sessions) is explicitly separate
from overall completion. After a normal exit, the activity receipt is marked
stopped; after a crash, an unrevised heartbeat becomes stale after 90 seconds.
An older release's running status without a matching heartbeat is unconfirmed.

A recent heartbeat means the worker thread is alive; it does not prove that
a network request is progressing. Check the terminal if the last progress
message remains unchanged. A stale heartbeat does not prove that a process
has terminated. Never kill processes solely from this display. SQLite's
existing exclusive writer lock still prevents simultaneous updates and releases
on process exit. GET pages do not acquire that writer lock, rewrite status or
start downloads. Refresh the browser page to read updated status.

Once an interrupted process has stopped, resume with:

```powershell
.\research.cmd
```

Completed price files and financial receipts are reused. A failure preserves
the last published report. Inspect **System** and the terminal for the exact
failed phase. There is no destructive reset or automatic deletion of caches.

## Persistent filing retry policy

Default attempts remain bounded to 60 new filing documents per run:

| Failure | Retry delay | Effect |
| --- | --- | --- |
| HTTP 401, 403 or 429 | 24 hours | Pause new filing requests across subsequent runs; reuse cached evidence |
| Invalid/unsupported document or HTTP 400, 404, 410 | 7 days | Defer that filing identity while other documents can progress |
| Other transport/server errors | 1 hour | Defer that filing identity |
| Previous-release failure without retry metadata | 24 hours | Preserve the prior cooldown behavior |

These are application retry delays, not guarantees of provider availability.
No retries bypass access restrictions. A revised filing has a different filing
key, so it does not inherit an older document's failure solely because the URL
is the same. Corrupt retry state or inconsistent future timestamps cause an
explicit error rather than silently discarding protection. Saved reports record
the collection mode, cooldown-document count and provider retry time at cutoff.
An old report's retry timestamp is historical; a new run reevaluates the clock.

## Broader local-model checks

Your configured Qwen2.5 14B remains selected. With Ollama running:

```powershell
.\run.cmd ai-doctor
.\run.cmd ai-evaluate --extended
```

The optional extended suite has eight fictional cases: missing evidence,
conflicting signals, publisher prompt injection, a positive contract award,
mixed developments, a routine notice, positive prices without news, and an
adverse event alongside positive prices. The original three-case smoke suite
remains available without `--extended`. Evaluation uses local inference and can
take time on a large CPU-hosted model. It saves evaluation results separately
from market reports and paper journals.

The new cases are development checks, not a held-out accuracy benchmark.
Their harness is tested with deterministic outputs; this release does not
claim that your Qwen2.5 14B passes them. If any fail, use `ai-disable` while
reviewing the evaluation output. The direct evaluation command reports failure
but does not automatically change your configured enabled state. Do not treat
passing checks as evidence of investment returns.

## Scope and next milestone

This completes the milestone-8 software tranche for inspecting coverage,
reporting live activity, recovering interrupted work and controlling filing
retries. Real coverage growth still depends on available supported documents.
Ranking equations, financial calculations, paper policy and model selection
contract are unchanged. Existing AI selections remain readable and cacheable.

Milestone 9 is forward evaluation and release-readiness assessment: accumulate
actual future paper observations, assess benchmark-relative performance and
frictions, and investigate failure cases. Coding cannot substitute for elapsed
market sessions. More source/parser support remains an ongoing coverage task.
