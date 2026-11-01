# UI release 0.5.1 validation — 17 October 2026

Environment: Python 3.12.14, Linux. Application and delivered tests
use the Python standard library. Release-only HTML inspection also used lxml.

## Automated checks

**332 tests passed** with Python warnings treated as errors: the 316 existing
tests plus 16 UI regressions. Two older presentation assertions were updated
for the moved stock-detail content and renamed Today/History pages.

The new checks cover whole-universe case-insensitive search, pagination beyond
the first page, coverage filters, invalid query rejection, report-pinned links,
HTML escaping, safe source URLs, archive status, legacy reports without
combined scores, history version changes, gaps in performance charts, and
separation of pending paper entries from executed holdings.

HTTP checks cover empty installations, old history bookmarks, explicit stock
404s, Origin/Host protections, read-only GET forms, and navigation with unusable
legacy databases. They verify no runtime state is created or modified by the
new daily pages.

## Retained market evidence

The saved development report with **2,691 scanned instruments**
and prices through **2026-10-16** was opened in an isolated runtime.
This was the retained 0.5.0 development snapshot, not a new scan or the latest
state of the user's Windows installation.

- Rendered and inspected **13 HTML pages**, including the main
  pages, search, the final 40-row page, and complete/partial/excluded stocks.
- Followed **85 unique internal links** successfully.
- Checked one page heading, unique IDs, all five navigation links, labelled
  search controls, and absence of scripts and external image dependencies.
- Matched latest-report JSON and forward-ledger JSON to the saved records.
- Verified all **17 runtime files** remained byte-for-byte unchanged.

Report ID: `06b01d3923341efb37dc169c12732dc0698b8d3eb3185639bcd7185b468db5ac`.

## Research and upgrade compatibility

The combined ranking, forward ledger, daily workflow, financial extraction,
integrated research, report persistence, scheduler and history engine files
are byte-for-byte identical to 0.5.0. No score formula, paper policy, historical
decision, cache or database schema is changed by this release.

The patch is produced against the exact delivered 0.5.0 archive, applied to a
fresh extraction, and verified with the complete test suite and release
version command. Files in the upgraded installation are compared to the full
0.5.1 release, except the full-release checksum manifest.

The private original database remains byte-for-byte preserved:
`ec065b706c4de97f032f25bcc781cb26549d8e90e47af94f6d63f9354501fc05`.

The patch excludes data, caches and real market validation reports. The source
export also excludes runtime state and includes all updated modules and tests.

## Verification limits

The supported control-browser capability was unavailable. **No visual browser
QA or browser interaction run was performed.** Responsive CSS, keyboard focus
rules and semantic markup were inspected in source; actual desktop/mobile
layout, zoom and assistive-technology behavior still need a target-browser
review. No screenshot is represented as a verified browser render.

Native Windows batch execution, Task Scheduler, Python 3.14 and GitHub CI were
not run here. Existing Windows launchers retain their original CRLF bytes.
This UI release makes no claim about new forward returns or profitability.
