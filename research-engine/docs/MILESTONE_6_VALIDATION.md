# Milestone 6 validation — 18 October 2026 (IST)

Release: **Oraculum local 0.6.0; core 0.1.0**.
Environment: Python 3.12, Linux, standard-library application and test suite.
These are development checks, not the current state of the user's Windows PC.

## Automated checks

`python -W error -m unittest discover -s tests -q` passes **374 tests**:
332 existing regressions plus 42 milestone-6 checks. The event tests cover:

- RSS/Atom and official JSON, publication dates/timezones, missing dates,
  unsafe links, redirects, entities/DTDs, malformed/error responses and bounds.
- Official symbol/ISIN agreement, conflicting identities, unique ISIN aliases,
  nested company names, ambiguous names, multiple mentions and common-word tickers.
- Actual receipt cutoff, fractional seconds, late backfills, future publication,
  immutable revisions, repeated/tracking duplicates and latest-version filtering.
- Read-only empty views, store hash integrity, backwards clock detection,
  concurrent ingestion, stale-cache preservation, offline mode, cooldowns,
  HTTP 429 Retry-After and independent source failures.
- Report publication despite optional news-store failure, unchanged ranking
  results with news capture, archive/store identity binding, source escaping,
  CSV formula protection, pagination and new HTTP/CLI routes.

## Live sources

The production collector fetched all three configured sources between
**17 October 2026 19:29:43 and 19:29:57 UTC**
(**18 October 00:59:43–00:59:57 IST**).

| Input | Supplied | Valid items stored | Matched items | Notes |
|---|---:|---:|---:|---|
| NSE announcements, 12–18 October | 2,983 | 2,945 | 2,115 | 38 lacked a usable attachment link; 553 identity conflicts remained unassigned |
| NSE board-meeting RSS | 0 | 0 | 0 | Valid empty feed, not proof of no meetings |
| ET stock RSS | 50 | 50 | 30 | Remaining 20 unassigned; conservative text matching |

There were **2,995 distinct initial records** and **2,145 matched records**.
No received item lacked a parseable publication time or had a future date at
collection. All three original responses and all 2,995 revision hashes passed
the event-store audit. Real feed content is kept only in the private validation
workspace and is excluded from the source/patch ZIPs.

NSE's public announcement RSS was also inspected and was empty just after
midnight. The configured seven-day public JSON listing therefore supplies
recent announcement evidence without depending on a same-day RSS window.
Neither interface guarantees complete history. Observed ISIN mismatches
include announcement metadata retaining a different security identifier from
the final price-file universe. The application deliberately leaves those
records unassigned; it does not infer that the issuer is necessarily wrong.

## Integrated workflow

The real-data validation workspace copied retained price/fundamental caches
and an existing paper experiment. An initial offline run correctly stopped
because master identity evidence was older than its required freshness limit.
An online daily run with `--max-filings 0` then refreshed metadata, reused the
live event receipts within their cooldown, published a new report and completed
the paper phase. No new financial document batch was requested.

- Price session: **16 October 2026**; 60 completed sessions.
- Report cutoff: **17 October 2026 19:31:36.105166 UTC**.
- Report ID: `b9530de56460f7af6788986aa756b332279b8ebb3fd3cf8134619778e8cf2fa4`.
- 2,691 scanned stocks; the retained development cache had 15 complete combined
  profiles, 10 candidates and 10 highlights. This does not describe the user's
  newer financial backfill progress.
- News capture: ready, partial feed coverage, 2,995 visible records, snapshot
  cursor and store identity recorded in the report.
- Existing forward experiment: zero filled positions and five pending entries.
  A weekend update did not invent fills or future performance.

The implementations of combined ranking, forward paper evaluation, financial
calculations, integrated financial research, scheduling and research history
were byte-compared with 0.5.1 and remained unchanged.

## Viewer and update checks

Sixteen rendered pages and **159 internal links** returned successfully over
loopback HTTP. These included News filters, pagination, identity conflicts,
empty board RSS, current and archived news, stocks, System and the existing
main pages. HTML checks verified the six-link navigation, accessible form
labels, one page heading, unique IDs, escaped content and no remote assets.
All **29 runtime files** were byte-identical before and after viewer requests.
The JSON research and paper routes matched their saved records exactly.

The update ZIP is applied over a fresh extraction of the exact delivered
0.5.1 full ZIP. The upgraded source is compared with the new full release and
the entire 374-test suite is run again. Launchers preserve their original CRLF
bytes. The patch excludes runtime databases and dated validation snapshots.
The original private `data/oraculum.sqlite3` is preserved unchanged with SHA-256:

`ec065b706c4de97f032f25bcc781cb26549d8e90e47af94f6d63f9354501fc05`

## Limits of verification

No supported browser-control capability was available for visual screenshots.
Rendered HTML, navigation, data and HTTP behavior were checked; pixel-level
browser layout was not. Windows Task Scheduler and native Windows execution
were not run in the Linux build environment. Feed availability can vary by
network and time. Successful live retrieval does not establish exhaustive
coverage, investment performance or predictive value.
