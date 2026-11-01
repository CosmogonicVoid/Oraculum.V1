# Oraculum 0.8.2 — Research terminal

This replaces the previous dark content panels with a light workspace, dark icon sidebar, global stock search and compact tables, inspired by the supplied Koyfin, Quartr and Finviz references.

## Install over 0.8.1
Close the server terminal. Extract Oraculum-UI-Update-0.8.2.zip into the existing folder containing run.cmd, replace files, restart run.cmd and refresh the browser. This patch targets 0.8.1. For an older installation, use the full ZIP in a separate folder; retain your existing runtime data and settings. No new dependencies, fonts, services or model downloads are required.

## What changed
- Global search submits to the existing screener and searches the latest saved report. Report-specific filters retain their selected report.
- Overview combines the shortlist with score-distribution bars and five momentum leaders among technical passes. Both panels derive only from saved report data. These are not live market feeds or new recommendation signals.
- Score bins include the lower bound and exclude the upper bound, except the final bin includes 100. Missing/nonfinite/out-of-range values are excluded and counted separately.
- Explore displays existing 50-session trend, relative volume and annualized volatility alongside scores, prices and momentum.
- Research briefs use a white document layout; recorded portfolio charts use colors readable on white.
- Narrow displays stack the analytics panels and wrap navigation. Tables retain horizontal scrolling.

All market calculations, eligibility rules, model settings, saved data and launch scripts remain unchanged. The release has no editable investment-thesis editor, drag-and-drop dashboards or unsupported chart controls. No illustrative market prices or fake sparklines are included.

## Validation
472 automated tests passed on the patched release. HTTP/HTML and internal-link checks verify navigation, read-only behavior and unchanged report JSON. Original database bytes and calculation modules are preserved. Native Windows execution and browser visual inspection were unavailable in this environment; responsive CSS has not been visually verified in a browser.
