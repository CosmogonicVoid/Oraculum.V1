# Milestone 6 — news and corporate announcements

Local release **0.6.0**, 18 October 2026 (IST). This adds a working, free local
collection and evidence workflow. It does not add AI sentiment, forecast
probabilities, a new ranking equation, or trade execution.

## Install over 0.5.1

1. Close Oraculum's viewer and any daily update terminal. Keep a backup of the
   project and `%LOCALAPPDATA%\Oraculum\data`.
2. Extract **Oraculum-Milestone-6-Update-0.6.0.zip** into the existing project
   folder containing `run.cmd` and `research.cmd`. Replace matching code files.
   Do not extract it into the inner Python package or a new nested folder.
3. In PowerShell:

```powershell
cd "C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum"
.\run.cmd --version
.\research.cmd
```

Expected version: `Oraculum local 0.6.0; core 0.1.0`. The daily command opens
http://127.0.0.1:8765 when finished. Select **News**, or open a stock's Analysis
page and its **News & announcements** section.

The patch applies to **0.5.1** and contains no runtime databases. Prices,
financial statements, archived reports and paper ledgers remain in their current
workspace. The complete `Oraculum.zip` is an alternative for a fresh checkout
or older source versions; its outer lowercase `oraculum` is the project root.
An existing Windows scheduled task pointing to this same project path uses the
updated workflow automatically. Installing the update does not create a task.

To collect news without a price or financial refresh:

```powershell
.\run.cmd news-refresh
.\start.cmd
```

This uses the company identities in the latest saved report. It updates the
current News page; a new daily report is required to capture a new stock-page
news snapshot. Old reports retain their original knowledge cutoff.

## What is collected

| Source | Input | Coverage |
|---|---|---|
| NSE corporate announcements | Public exchange JSON listing; links to original attachments | Current IST date and preceding six dates |
| NSE board meetings | Official RSS | Rolling feed, sometimes empty after a reset |
| Economic Times, Stocks | Publisher RSS headlines and short supplied excerpts | Rolling feed, not a complete news archive |

Source directories: [NSE RSS](https://www.nseindia.com/static/rss-feed),
[NSE announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements),
[ET RSS](https://economictimes.indiatimes.com/rss.cms).

The application uses public HTTPS endpoints without cookies, credentials, paid
subscriptions or a model. It does not scrape full publisher articles or download
announcement PDFs. Each item links directly to its original article or filing.
Feed content is retained for the user's personal local research. The source ZIP
for GitHub excludes collected data; publisher rights still apply to any later
redistribution. There is no guarantee of permanent availability or free access.

Feeds are requested once per eligible refresh. Successes are cached for two
hours; ordinary failures wait one hour. HTTP 401/403/429 wait at least 24 hours;
a longer valid Retry-After is respected up to seven days. There is no force
option to bypass cooldown. Each response has a 25-second socket timeout,
12 MiB byte limit and 20,000-item limit; redirects stay on the feed's approved
host. Declared XML entities/DTDs, unexpected schemas and unsafe source links
are rejected. A failed feed retains previous evidence and does not block the
other feeds. A failed event store is reported without preventing research
publication or the paper phase.

Zero items means an empty response, not an absence of company developments.
Missing source links are skipped and counted. Rolling RSS windows and offline
periods can leave permanent gaps; there is no historical news backfill claim.
The normal pages show a 30-day publication window. Items without a usable
publication date use collection time for this window and are visibly labelled.

## Matching, categories and duplicates

- Official announcement symbol and ISIN must agree with the report universe.
  A unique current ISIN can resolve an old/unknown symbol. A conflicting ISIN
  stays unassigned even if the name looks familiar. Some exchange announcement
  records retain earlier ISINs; review is needed to distinguish stale metadata
  from an actual identity change.
- Publisher and board RSS text uses unique company names with at least two
  words and eight normalized characters, or an explicit `NSE:SYMBOL` reference.
  Company suffixes are normalized. Longer names take precedence over contained
  names. Bare ticker words, fuzzy names and ambiguous names are not guessed.
- Publisher name matches are tentative mentions. A story mentioning two firms
  may be attached to both; the matcher does not establish relevance or impact.
  Abbreviated brands can be missed. Unassigned items remain in News.
- Categories such as results, capital, governance, deals and regulatory matters
  are deterministic keyword labels. They are not sentiment, direction,
  materiality or AI judgments. A board item has a publication date; this release
  does not infer a separate upcoming meeting date from prose.
- Stable exchange IDs or canonical article links identify an item. Tracking
  parameters and fragments are removed. Repeated identical items do not create
  duplicate revisions. A changed headline, excerpt, time or company mapping
  creates an append-only revision. Separately published similar stories are
  retained as separate sources; their semantic similarity is not proof that
  they report the same underlying event.

## Evidence and archived views

`events.sqlite3` is a separate database in the existing local data workspace.
It stores original feed responses with SHA-256 hashes, actual receipt times,
normalized records, matching evidence and immutable revisions. Feed health
and cooldown state are mutable; collected evidence is append-only.

Publication time, first collection time, and this revision's collection time
are separate. Future-dated items cannot appear before their publication cutoff.
A report records the event store identity, final revision cursor and capture
cutoff. Queries select the latest revision known within those boundaries before
filtering by company. This prevents a later correction, backfilled headline or
reassigned company from changing an older report's view. A stock's ISIN is also
checked. If the original event database is absent or replaced, the report
states that its news evidence is unavailable.

Back up `events.sqlite3` along with the existing databases and `research/`
folder. A report JSON includes collection status and a snapshot reference;
it does not embed all feed bytes or headlines. Copying the JSON alone therefore
does not copy the event evidence. There is no automatic deletion policy in this
release; disk usage grows as feeds and revisions accumulate.

## Pages and commands

**News** provides search, exact-symbol, type, source and matching filters,
pagination, direct source links and expandable collection evidence. JSON and
CSV export the current page. CSV cells are protected against spreadsheet
formula injection. **System** shows per-source success/failure, stale data,
skipped items, identity conflicts and the next permitted refresh time.
All browser routes remain read-only; opening a page never fetches remote data.

```powershell
.\run.cmd news-refresh                   # collect using latest report identities
.\run.cmd news-refresh --offline         # inspect cache without network requests
.\run.cmd news-status                    # show feed health
.\run.cmd news-status --audit            # verify feed bytes and revision hashes
.\run.cmd auto-daily                     # ranking + news + history + paper
.\run.cmd research --integrated          # ranking + news + history, no paper advance
```

On Linux/macOS replace `.\run.cmd` with `python3 -m oraculum.local`.
`--data-dir PATH` is supported for manual commands. `research` without
`--integrated`, the manual/fictional engine and the optional older `analyze-text`
command keep their previous behavior. No Ollama installation is needed here.

## Remaining milestones

**7: Local AI synthesis** — sourced summaries, extraction and calibrated
uncertainty, evaluated before any ranking use.

**8: Broader coverage and reliability** — more filing schemas, more robust
company identity histories, maintained calendars and operational hardening.

**9: Forward evaluation and release readiness** — accumulate actual future
sessions, examine costs/drawdowns/benchmark comparisons and document results.
This requires elapsed market time; code cannot manufacture a performance record.

The existing 60/10/10/10/10 combined equation and paper policy are unchanged.
News presence does not make a stock eligible and news absence is not a neutral
sentiment value. This release establishes no investment edge.
