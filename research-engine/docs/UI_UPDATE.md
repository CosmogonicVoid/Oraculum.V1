# Local UI release 0.5.1

This release reorganizes the existing local research app. It adds no paid
services, web dependencies, model downloads, database migrations or trading
connections. The scoring, paper policy and collection algorithms remain the
0.5.0 versions.

## Install over 0.5.0

1. Let any active research run finish. Close the viewer terminal with Ctrl+C.
2. Keep a backup of the project.
3. Extract `Oraculum-UI-Update-0.5.1.zip` into the existing folder containing
   `run.cmd` and `research.cmd`. Replace matching files. Do not extract into
   the inner Python package folder.
4. From that project folder in PowerShell:

```powershell
.\run.cmd --version
.\start.cmd
```

Expected version: `Oraculum local 0.5.1; core 0.1.0`.

Open http://127.0.0.1:8765. The viewer renders existing report JSON using the
new UI immediately; a fresh market scan is unnecessary for this update.
Refresh the browser if a tab was already open. Run `research.cmd` when you
want another data refresh and paper evaluation.

For the current installation, the project folder is:

```text
C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum
```

The patch has no enclosing project folder. The complete `Oraculum.zip` has
an outer lowercase `oraculum` folder and can be extracted into a fresh
directory. The patch requires the 0.5.0 foundation; use the complete release
for older code. Windows runtime data remains in `%LOCALAPPDATA%\Oraculum\data`.
If moving the project, reinstall its scheduled task from the new location.

## Pages

| Page | What it shows |
| --- | --- |
| Today `/` | Price/report dates, three summary counts, the combined shortlist, cautions and a concise financial-coverage notice. |
| Explore `/explore` | All scanned stocks, company/symbol/ISIN search, screening and coverage filters, sorting and 40-row pages. |
| Stock `/stock` | Reasons, blockers, score contributions, metrics with reporting periods, source availability and audit references. |
| Paper Portfolio `/forward` | Virtual cash/equity, holdings, pending entries, recorded returns, benchmark details, costs and exports. |
| History `/research-history` | Archived reports, plain-language ranking versions, highlights and additions/removals compared with the preceding loaded report of the same version. |
| System `/system` | Data freshness, workflow status, financial downloads and coverage, calendar dates and setup commands. |
| Advanced `/advanced` | Earlier imported-dataset and fictional-demo engine. |

The old `/history` bookmark now opens daily research history. Existing manual
run URLs, JSON APIs, CSV downloads and forward routes remain available.

Search uses a standard GET form. Apply submits the selected filters; Reset
clears them. JavaScript is unnecessary. The report ID stays in search,
pagination and stock links, so a background refresh cannot silently replace
the evidence you were inspecting.

## Reading the screens

- The combined score and technical score are different measures. Unavailable
  combined scores stay unavailable; they are not rendered as zero.
- Candidate ranks can have gaps because additional shortlist rules are applied
  after complete combined scores are ranked.
- “Complete” financial coverage refers to the four required screen metrics.
  Valuation diagnostics can still be unavailable. Financial dates are shown per
  metric in the stock view.
- Pending paper entries are not executed holdings. A new experiment has no
  performance result. The chart requires at least two recorded sessions and
  available returns; missing observations break its lines.
- Marked equity can include stale quotes and unspendable dividend receivables.
  The stale-price warning and withheld comparisons remain visible.
- System shows the recorded workflow result. It does not claim that Windows
  Task Scheduler is installed: verify it using `run.cmd schedule-status`.

The new layout includes labelled controls, keyboard focus, a skip link,
text status labels, accessible scroll regions and narrow-screen styles.
Critical refresh and coverage warnings remain visible. Long formulas and
audit details are expandable.

Existing standalone HTML report files retain their saved presentation.
The local viewer renders their JSON using the new screens; no archive
rewrite is required. Newly exported standalone reports keep the detailed
offline report format and have no navigation links to a local server.

## Scope still outstanding

Broader financial/schema coverage, news and announcement analysis, local AI
explanations, calendar maintenance and measured forward performance remain
separate milestones. This UI release does not establish a forecasting edge.
