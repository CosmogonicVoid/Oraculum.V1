# Local release verification — 14 October 2026

Environment: Python 3.12.14, Linux. Local operating release 0.2.0; original
research engine remains 0.1.0 and `bounded-factor-baseline-v1`.

## Automated checks

Command: `python -W error -m unittest discover -s tests -v`.

**185 tests pass**: all 161 integration/core tests and 24 new local workflow tests.
The new checks cover:

- Bhavcopy CSV/ZIP equivalence, archive constraints, wrong sessions, inconsistent
  turnover units, OHLC errors, duplicate stocks and unsupported symbols.
- Idempotent receipts, conflicting revisions, content checksums, SQL immutability,
  real receipt cutoffs, expired calendar coverage and missing-session windows.
- No invented fundamentals: price-only snapshots remain excluded.
- Persistent paper fills across restarts, order-ID collisions, signal timestamps,
  raw-only execution, unavailable bars, terminal rejection, skipped-session
  prevention, same-open submission, mode separation and hash-chain checks.
- Atomic duplicate/concurrent settlement; changed execution assumptions rejected.
- Repeatable combined demonstration: three shares at virtual 130.1300, fees 0.39,
  final cash 9609.22, no second debit on a repeated run.
- Local HTTP report/API routes, host restrictions, no arbitrary file access,
  escaped source text, and no read-time creation of absent databases.
- AI draft schema, sentiment bounds, exact quote membership, cloud rejection,
  document hashing and an explicit advisory-only result.
- Friendly CLI failures and preservation of edited setup files.

The original suite covers the factor equation, source timestamps, CSV histories,
adjustment vintages, audit replay, CLI path protections and simulator accounting.

## Real public-file smoke checks

The NSE CM UDiFF final files for **2026-10-13** and **2026-10-14** were downloaded
through the public archive during this work. They parsed into **2,683** and
**2,681** supported EQ/STK/F1 stock rows respectively. The 13 October file skipped
957 rows outside that scope and eight identifiers unsupported by the core.

A local scan of the three sample watchlist stocks used both snapshots, an explicit
two-session calendar and actual local receipt timestamps. It produced **zero
candidates and three exclusions**, as expected with only two price sessions and
no fundamentals. The saved report was recomputed with the core; its identity and
output matched. No historic availability or missing fundamentals were invented.

This establishes that the adapter worked for those files in this environment;
it is not a reliability guarantee for future downloads or proof of data accuracy
across every instrument. Live source files are not included in the delivery.

## Delivery and limitations

The user's previous `data/oraculum.sqlite3` was compared byte for byte and is
unchanged. Demo, live smoke-test and temporary databases were kept outside the
source delivery. The source export excludes runtime databases and market data.

The user ZIP is checked after extraction with the same test suite and repeated
demo. The original core command still works. Its checksum manifest records the
delivered files, excluding the manifest itself.

Not executed here: Windows batch launchers, Task Scheduler, Python 3.14, an actual
Ollama model, or the GitHub Actions workflow. The AI checks use mocked responses,
not a measured sentiment-quality benchmark. No GitHub repository was published
without a connected account.

Software checks do not establish investment performance. A credible evaluation
still needs point-in-time datasets, corporate-action handling, historical
membership, realistic costs, out-of-sample testing and benchmark comparison.
