# Integrated data and fundamentals validation — 16 October 2026

Local release **0.4.0**, Python 3.12.14 on Linux. **266 offline tests pass**, including the original 219 and 47 new data/financial regressions.

## Actual exchange workflow

The live workflow reused verified original price bytes and fetched the missing 15 and 16 October final files. It downloaded official security, symbol-change, corporate-action, industry and financial-catalogue evidence, plus bounded filing batches. The final code then rebuilt the report offline. No fictitious observations were inserted into this real-data report.

Final snapshot: **2026-10-16**, 60 sessions from 2026-07-23; built **2026-10-16T16:07:20.631773Z**.

| Observation | Count |
| --- | ---: |
| Current traded EQ/STK/F1 stocks scanned | 2,691 |
| Eligible after final data/liquidity/risk checks | 997 |
| Stocks with supported action adjustments applied | 617 |
| Stocks blocked by unresolved action records/identities | 231 |
| Technical highlights | 10 |
| Financial profiles with all four screen metrics | 13 |
| Partial financial profiles | 5 |
| Selected financial documents still uncached | 7,099 |

Coverage is intentionally partial. No statement is made that financials are complete for the whole universe. Unsupported schemas, unresolved ISIN joins and missing filings are shown separately in the report. No peer valuation was published because no cached group met the five-other-peer requirement.

Eight identifiers were recovered from the original price bytes: ARE&M, GMRP&UI, GVT&D, J&KBANK, M&M, M&MFIN, S&SPOWER and SURANAT&P. Old cache payloads and original receipt times were not rewritten.

The final identity checks are stricter than the initial development pass: several action entries carried old ISINs that did not match adjacent price rows. Those entries are blocked for review. Two distinct interim-dividend records for one date were also treated as ambiguous instead of added together. A financial filing under an old ticker was accepted only after its official dated rename and unchanged ISIN were confirmed.

## Independent arithmetic checks

The following metrics were recomputed directly from the raw XML using a separate extraction script. They matched the saved report to a tolerance of 1e-10. This checks extraction/definitions, not investment performance or the accuracy of company-reported accounts.

| Metric | TCS | SKYGOLD |
| --- | ---: | ---: |
| Quarter revenue YoY | 11.229654% | 77.928640% |
| Quarter net margin | 19.038640% | 5.211756% |
| Borrowings / equity | 0.00000000 | 0.72072264 |
| Annual ROCE | 58.498987% | 45.926921% |
| Annual-EPS P/E | 18.12366738 | 58.69396790 |

TCS quarter ends 2026-09-30; SKYGOLD quarter ends 2026-06-30. Both annual EPS periods end 2026-03-31. These are dated validation samples, not stock recommendations.

## Integrity and application checks

- Every financial metric source ID resolved to evidence in the report, and no metric availability timestamp was after the report cutoff.
- Split/bonus/dividend economics, fractional volume, ambiguous events, identity mismatch, dated aliases and original-byte preservation were tested.
- XBRL units/precision, nil versus zero, negative profit, segment exclusion, conflicting facts, period matching, stale data, revised URLs and unsupported schemas were tested.
- Bounded download resumption, offline cache reuse, HTTP denial without retry, failed-update pointer preservation and HTML escaping were tested.
- Real local HTTP requests to the homepage, latest report JSON, CSV and paper-status routes all returned 200. Paper status remained uninitialized; no core-runs or paper database was created by the integrated workflow.
- The private original database is preserved byte-for-byte: `ec065b706c4de97f032f25bcc781cb26549d8e90e47af94f6d63f9354501fc05`.
- Windows launchers retain CRLF. Native Windows and Python 3.14 execution were not tested here. The repository retains its Windows/Linux CI configuration.
- Public data interfaces can fail or change. Calendar coverage still ends on 7 November 2026. News, general announcements, complete financial coverage and validated forward performance remain outstanding.

## Included private snapshot

Open `validation/data-fundamentals-2026-10-16.html` for the dated standalone report. Its accompanying hashed JSON and CSV provide all stocks, periods, flags and source hashes. It is a development snapshot, not the current state of your own computer. Raw exchange caches and these private validation reports are excluded from `dist/oraculum-source.zip`.

Report ID: `7ed80a7a7837b4bdd114259356f46d209f1d50baca08ea015647e7e901511108`
