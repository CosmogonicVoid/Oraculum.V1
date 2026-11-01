# Oraculum 0.8.4 — Charts and manual demo trading

## Install
Close the local server. Extract Oraculum-UI-Update-0.8.4.zip into your existing 0.8.3 folder containing run.cmd; replace files, restart run.cmd, and refresh the browser. The full project ZIP is also supplied. No packages or model downloads are needed. Runtime data and Qwen settings are retained.

## Open the charts
Open Explore, search for a company and click its symbol. The stock page now contains a Price & volume panel: candles or close line, aligned raw volume, 20- and 50-session simple moving averages, 20 sessions / 60 sessions / All saved controls, and an expandable exact-values table. Hover a candle to see its native tooltip; keyboard focus outlines the corresponding bar. Timeframe controls reload the view; this is not a drag-to-zoom chart.

Charts read the local market.sqlite3 cache and match the selected report's source receipts and cutoff. They do not fetch prices on page load. History is limited to that report's saved window, normally 60 sessions. Missing rows and identity mismatches stay gaps and restart moving-average warm-up. No synthetic prices are inserted. Raw prices are not adjusted for splits/dividends and can differ from adjusted ranking metrics. Missing cache displays an explanation; corrupt or mismatched receipts fail rather than inventing a chart.

## Make a demo purchase
1. Open Demo trading in the sidebar, or Practice Buy / Sell on a stock page.
2. Enter an exchange symbol from the latest report, choose Buy, and enter a whole-share quantity.
3. Select Preview virtual trade. Review the saved price date, price, quantity and total.
4. Select Confirm virtual buy. The account starts with INR 100,000 virtual cash on its first confirmed trade.
5. Holdings and cash update. To sell, choose Sell and a quantity no larger than your holding, then preview and confirm.

Manual trades execute immediately at the latest saved close. They are a saved-price practice simulator, not live orders, realistic fills or a valid performance backtest. Old prices remain usable but their date is explicitly shown. No leverage or short selling. Fees, slippage, dividends, splits and symbol changes are not applied. Equity and unrealized P/L use the latest saved report's closes and can therefore be stale; missing marks are unavailable, not zero.

Realized P/L uses average-cost bookkeeping with integer-paise cash accounting. The latest 200 trades appear in the UI; all confirmed records remain in the database. The manual account is stored separately in manual_demo.sqlite3. No reset or delete action is exposed in this release.

## Automatic strategy
Use the Automatic strategy tab inside Demo trading to see the original forward experiment. Its policy, modeled costs, future-session execution and benchmark remain unchanged. Manual trades never modify forward.sqlite3 or its performance results.

## Protection and verification
Only preview and confirm use POST. GET requests do not write data. Host/Origin checks, a server-generated CSRF token and a signed, expiring quote guard confirmations. Prices are checked again against the latest report; changed accounts require a new preview. A unique trade ID prevents duplicate submissions. No brokerage connection exists.

Regression checks cover raw-cache chart prices, volume, moving averages, data gaps, receipt mismatches, account balance, partial/full sells, insufficient funds, overselling, quote tampering/expiry, changed prices, stale account revisions, duplicate confirmations, HTTP origin/CSRF boundaries and strategy-file isolation. HTTP checks cover 25 pages and 62 internal links while preserving report JSON and runtime files. Browser visual inspection and native Windows execution were unavailable.

## Remaining roadmap
- Manual simulation realism: future-session fills, fees/slippage, corporate actions, pending/cancelled orders and a recorded equity curve.
- Research tools: saved watchlists, side-by-side comparisons, expanded filters and exportable personal notes.
- Chart depth: longer locally cached history, adjusted series, zoom/crosshair and comparison overlays.
- Evidence quality: broader financial-schema coverage, more reliable data sources and explicit source coverage monitoring.
- Evaluation: longer forward records, benchmark comparison, evaluation across market conditions and checks against selection bias. No validated predictive edge has been established.
- Delivery: native Windows and browser visual QA, backup/restore workflow and a clean source-only GitHub release.

These remaining items are not claimed as implemented in 0.8.4.
