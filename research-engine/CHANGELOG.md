# 0.8.4 — Charts and manual demo account

- Receipt-pinned raw daily candles/close line, volume and MA20/MA50.
- Manual saved-close practice account with INR 100,000 virtual cash, confirmed buys/sells, holdings and P/L.
- Separate from the automatic strategy; confirmed POST forms with signed quotes and duplicate protection.
- Existing research calculations, data and model settings retained.

# 0.8.3 — Graphite glass

Graphite surfaces, translucent panels, hover/focus/press feedback, larger touch targets and reduced-motion support. No calculation changes.

# 0.8.2 — Reference-inspired research terminal

- Light panels and dark navigation, persistent stock search and compact tables.
- Report-derived score distribution and momentum leaders.
- More existing metrics in Explore; document-style briefs.
- All calculations and runtime settings preserved.

# 0.8.1 — UI redesign

- Responsive sidebar and overview hierarchy.
- Research entry point with report-pinned links between briefs and news.
- Stock evidence and risk columns; consolidated report-status disclosures.
- Existing calculations, data, Qwen configuration and launcher scripts retained.

# Changelog

## Local release 0.8.0 — 2026-10-20

- Added report-pinned Coverage with per-input source/date checks, search, filters,
  financial-age review and CSV/JSON exports, plus read-only coverage-status CLI.
- Added writer heartbeats and detailed progress timestamps; stopped, stale and
  legacy activity no longer masquerade as confirmed active work.
- Persisted provider-wide filing denial cooldowns across runs; deferred malformed
  documents separately so other queued filings can progress.
- Added optional eight-case local-model evaluation, preserving the three-case
  smoke suite, configured model, accepted briefs and inference contract.
- Preserved scoring, financial formulae, paper policy, saved reports and data.
- See docs/MILESTONE_8_VALIDATION.md for verified scope and platform limits.

## Local release 0.7.0 — 2026-10-19 (IST)

- Added optional local Ollama evidence selection, fixed-template briefs and event
  tone with pinned model digests, strict identifiers and exact source snippets.
- Added report-cutoff evidence notebooks, mandatory coverage warnings, immutable
  journals, cache reuse, bounded retries and isolated fictional evaluations.
- Added Briefs navigation, stock links, read-only JSON/Markdown exports, Windows
  setup, health/status commands and nonfatal daily AI integration.
- Preserved ranking, paper policies, saved reports and runtime databases.
- Validation details and known limits are in docs/MILESTONE_7_VALIDATION.md.

## Local release 0.6.0 — 2026-10-18 (IST)

- Added milestone 6: public NSE announcement JSON, NSE board RSS and Economic
  Times stock RSS collection with bounded downloads and provider cooldowns.
- Added conservative symbol/ISIN and company-name matching, visible unmatched
  items, deterministic categories and direct original-source links.
- Added a separate event store with immutable source receipts and revisions,
  actual collection times, canonical-link deduplication and report snapshots.
- Integrated optional news capture into daily/integrated research; feed or
  event-store failures do not prevent publication or paper advancement.
- Added News, stock evidence sections, System health, news-refresh/news-status,
  JSON/CSV exports and 42 regressions; 374 total tests pass.
- Preserved combined ranking, financial calculations, paper policy, scheduler,
  old reports and runtime databases. AI interpretation remains milestone 7.
- Live validation collected 2,945 valid announcement items and 50 news items;
  board RSS was empty. See docs/MILESTONE_6_VALIDATION.md for limitations.

## Local release 0.5.1 — 2026-10-17

- Added a shared, responsive local shell with Today, Explore, Paper Portfolio,
  History and System navigation; moved the earlier manual engine to Advanced.
- Put the combined shortlist before diagnostics; added searchable whole-universe
  results, filters, sorting, pagination and report-pinned stock evidence views.
- Separated executed holdings from pending entries, added observed-return charts
  with gaps for unavailable values, and clarified empty and stale-data states.
- Simplified history, added same-version shortlist comparisons, and exposed
  data coverage, calendar and workflow diagnostics on a dedicated page.
- Added 16 UI/search/HTTP regressions; 332 tests pass. Existing core, scoring,
  data collection, scheduler and paper-policy implementations are unchanged.
- Browser visual QA was unavailable; rendered HTML, HTTP navigation and data
  preservation were checked. See docs/UI_VALIDATION.md for scope.

## Local release 0.5.0 — 2026-10-17

- Added the disclosed 60/10/10/10/10 combined ranking, complete-input requirements,
  factor contributions, separate technical comparisons and versioned reports.
- Added an immutable research-history index with recovery, daily orchestration,
  status and rotating logs, and current-user Windows Task Scheduler installation.
- Added a separate forward paper experiment with fixed future-open entries,
  five-position allocation, precommitted 20-session exits, estimated costs,
  dividend receivables and supported share actions, a NIFTYBEES/cash comparison,
  daily equity/drawdown records, integrity checks and atomic repeat protection.
- Added history/forward HTML, JSON and CSV routes; existing viewer remains read-only.
- Preserved legacy core versions, report replay, manual paper ledger and user data.
- 50 new regression tests; 316 total. Live research through 16 October exercised
  next-session enrollment; no future returns or actual Windows installation claimed.

## Local release 0.4.0 — 2026-10-16

- Joined supported corporate-action-adjusted research and automatic financial
  statement extraction in `research --integrated`; Windows launchers use it.
- Reparse verified original price bytes for wider symbols, ISIN and company
  identity; join official dated symbol changes without rewriting old cache.
- Apply explicit split, bonus and cash-dividend factors; retain fractional
  normalized volumes and raw execution quotes. Unresolved actions block eligibility.
- Added bounded, resumable official XBRL downloads, revision-aware document keys,
  immutable evidence, source hashes, availability times and failed-URL cooldowns.
- Derive period-matched growth, margin, borrowings/equity, annual ROCE, annual-EPS
  P/E and sufficiently populated cached-peer comparisons; missing stays missing.
- Display financial coverage, sources, dates and a separate financial screen in
  HTML/CSV/JSON. Technical ranking weights and original paper-order gates unchanged.
- 47 new meaningful regression tests; all 266 pass. Live exchange workflow and
  offline rebuild exercised. Coverage is partial; specialist schemas, complex actions,
  news/general announcements and validated forward performance remain unfinished.

## Local release 0.3.1 — 2026-10-16

- Fixed a shared argparse default that incorrectly sent real research commands
  into `data/demo`. Real and fictional demo commands now resolve separate folders.
- Windows defaults now use `%LOCALAPPDATA%\Oraculum\data` and `demo`, outside
  the OneDrive project folder. Explicit `--data-dir` choices are respected.
- Added `repair.cmd` / `repair-local`: verified price-cache recovery with original
  receipts, conflict detection and safe repeat runs; original files stay in place.
- Added bounded retries for file-replacement permission errors. Progress-file
  failures warn without aborting downloads or hiding the actual workflow error.
  Report files and the latest pointer remain mandatory publication steps.
- Added 13 regressions; all 219 tests pass. Recovered 60 real cached sessions and
  reproduced the previous report without a network request. Native Windows
  execution remains unverified in this Linux environment.

## Local release 0.3.0 — 2026-10-15 (India)

- Added one-command real NSE research: automatic 60-session backfill, immutable
  cache reuse, resumable setup and whole supported cash-stock universe inspection.
- Added separate disclosed price/volume ranking, liquidity/continuity/volatility
  filters, raw-price jump exclusions, numeric reasons and downloadable full results.
- Added latest-report homepage, failure/staleness banners, standalone HTML/CSV/JSON
  and a process lock that releases after interruption. No model or key required.
- Added a sourced, bounded exchange calendar. It expires before the unverified
  8 November special session; no missing download is reclassified as a holiday.
- Added `research.cmd`; `run-daily.cmd` now updates this real-data report.
- Added 21 regression tests covering calendar boundaries, missing/future observations,
  score behavior, cache reuse/resume, report integrity and read-only viewer routes.
- Original buy-engine formula, replay identity, fundamental gates and paper-order
  authorization are unchanged. Technical highlights cannot become paper orders.

## 2026-10-13 — integrated contribution release (core 0.1.0)

- Integrated Qwen CSV/feature modules and Kimi paper simulation/audits.
- Fixed cutoff filtering, deterministic adjustment vintage selection, timestamp
  validation, null evidence and numerical boundary behavior.
- Isolated Decimal accounting, preserved large-balance debits and blocked free fills.
- Protected input files from hardlink export aliases and removed a CLI import warning.
- Corrected contributor test fixtures; added 17 integration regressions (161 passing).
- Added an executable combined paper demo and updated Windows setup instructions.
- Preserved the uploaded research database and relocated the nested Qwen README.
- Core formula, schema and research run identities remain unchanged.

## 0.1.0 — core contribution

- Added strict version-1 data contracts and typed extension interfaces.
- Added bounded nine-factor baseline with evidence and hard risk exclusions.
- Added canonical hashing, complete SQLite snapshots and replay verification.
- Added local CLI, JSON/Markdown output and fictional examples.
- Added 55 core tests and separate Qwen/Kimi implementation briefs.
# Local operations release 0.2.0 — 2026-10-14

- Added NSE CM UDiFF snapshot ingestion/download, immutable receipt cache,
  explicit-calendar scanning and watchlist/supplement configuration.
- Added transactional persistent virtual orders and chronological settlement,
  with idempotency, mode separation and a hash-chained ledger.
- Added a read-only loopback report viewer, Windows launchers and daily-run script.
- Added optional local Ollama evidence drafts. These do not alter research scores.
- Added 24 offline regression tests (185 total), local-operation instructions,
  GitHub source export and a cross-platform CI configuration.
- Kept core engine/algorithm versions unchanged; original research replay remains
  compatible. Preserved the user's old database separately from new workspaces.

