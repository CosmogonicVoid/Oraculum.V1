# Oraculum integration review — 2026-10-13

## Result

The uploaded ChatGPT core, Qwen additions and Kimi additions are integrated.
Initial execution: **144 tests; 3 failures and 20 errors**. Final execution:
**161 tests passed** on Python 3.12.14/Linux, with warnings treated as errors.
Windows/Python 3.14.4 was not executed in this environment.

## Corrections

| Finding | Correction and evidence |
| --- | --- |
| Future/unavailable CSV rows influenced suffix/version selection | Apply cutoff before choosing a session, vintage or contiguous window; regressions cover later sessions, unavailable latest revisions and unavailable middle sessions |
| Research vintage depended on CSV row order | At the latest eligible session, use the unique non-raw vintage when present, otherwise raw; reject multiple non-raw vintages as ambiguous; reverse-order check |
| Naive timestamps caused Python type errors before validation | Validate timestamp types before comparing cutoffs; reject malformed sequences cleanly |
| Unknown zero-baseline volume ratio retained evidence | Null metrics now have empty source IDs |
| Invalid volume lacked reliable row-level rejection | Validate nonnegative volume during CSV parsing; errors identify the row |
| Completed daily bars allowed impossible timestamps | Enforce open < close <= available and session dates in India; simulator checks these too |
| Finite inputs could produce non-finite feature values | Stable means/sample deviation and finite-result checks; reject unsupported numeric ranges |
| Paper accounting inherited caller Decimal settings | Isolated deterministic context, at least 28 digits, expanded precision for large amounts; verify exact debits and hostile caller context |
| Tiny values could round to free paper shares | Reject execution prices or gross amounts that round to zero |
| Export aliases could overwrite protected inputs | Block hardlink aliases in both CSV and core CLI paths; tests reproduce both original failures |
| Provider CLI emitted an import warning | Lazy package export avoids preloading the module executed by Python |
| Qwen README was in examples/examples/qwen | Move to examples/qwen/README.md |

The isolated Decimal precision budget is limited to 10,000 digits. Inputs beyond
that budget produce a validation error. Weighted average costs retain Decimal
precision without explicit cent rounding; a repeating quotient is still a
finite-precision approximation.

## Test fixture corrections

Kimi's default session close did not match its declared session date. That made
many audits fail before reaching the calculation under test. Fixed the fixture,
then corrected impossible momentum values, coverage omissions using factor names
instead of metric names, and freshness fixtures with inconsistent timestamps.
The maximum-score case now supplies zero risk penalty, matching its expected 100.
Persistence is checked through a fresh repository instance.

Qwen tests compared canonical ISO timestamp strings with datetime objects, created
invalid CSV cells inside a helper that crashed before parsing, and compared two
inputs pointing to the same overwritten file. These fixtures now exercise the
intended boundary. The raw/adjusted test no longer creates duplicate adjusted rows
or expects CSV row order to determine the vintage.

Kimi's weekend test tried to refill an ID already terminally rejected on Friday.
The corrected test verifies that the old ID stays rejected and a deliberate new
order fills at Monday's supplied open. Production duplicate protection is retained.

The original 55 core tests remain intact. Existing contributor tests were repaired,
and 17 additional integration regressions were added. Qwen and Kimi's original
notes said their tests had not been run; the executed results above are from this
integration review, not those earlier sessions.

## Scope and compatibility

No scoring equation, weights, contract schema or research run-identity algorithm
changed. The core engine version remains 0.1.0 so existing canonical research runs
retain their identities. Adapter fixes can correctly change the canonical bundle
for previously mishandled input; that changes the input hash and research run ID.
The dated integration release and MANIFEST.sha256 identify this source package.

The uploaded data/oraculum.sqlite3 is included byte for byte. All verification
writes used separate temporary databases. Virtual environments, Python caches and
machine-specific compiled files are omitted. Create your own environment locally.

The new `python -m oraculum.paper.demo` command demonstrates the whole path with
explicit fictional data: 10,000 starting virtual rupees; three shares at 130.1300;
0.39 fee; 9,609.22 ending cash; duplicate attempt rejected with state unchanged.
It performs no network or database writes and does not create an allocation policy.

## Limits

The simulator executes attempts against a supplied actual session. It does not
independently prove that a bar is the earliest possible exchange open after a
signal: the caller must supply the intended session and calendar. It validates
completed historical bars while using only the raw open for fill decisions.

The CSV provider validates the complete tape, including future rows, before using
eligible observations. Malformed future rows are errors; valid future observations
do not affect an earlier snapshot. Source metadata in the base bundle must itself
be point-in-time valid. The feature builder alone assumes its provider supplied
contiguous history; it has no independent holiday calendar.

No external market data, trained model, automated ingestion, scheduler, web server,
portfolio persistence, realistic historical backtest or demonstrated predictive
advantage is supplied. See README.md for the next product milestones.
