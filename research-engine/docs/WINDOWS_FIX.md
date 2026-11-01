# Windows scan repair — local release 0.3.1

## What failed

The screenshot showed Windows denying replacement of `research/status.json`
with WinError 5. It does not identify which process or permission caused that
denial. An open handle, sync process or access policy can interfere with writes;
the screenshot alone does not prove that OneDrive caused it.

The `data/demo` path also exposed a reproducible Oraculum bug: a shared argparse
parent gave every command the demo command's default. Release 0.3.1 removes that
shared default mutation and chooses real/demo workspaces after parsing.

## Apply the small patch to your existing project

1. Close any running Oraculum viewer with Ctrl+C. If the failed command says
   "Press any key to continue", press a key to return to the prompt.
2. Extract **Oraculum-Windows-Fix.zip** into the folder containing `research.cmd`
   and `run.cmd`. For the installation in the screenshot, that is
   `C:\Users\YOUR_NAME\OneDrive\Desktop\Oraculum\oraculum`.
   Replace matching code files. The patch contains no databases or runtime data.
   Do not put its contents inside the inner Python-package `oraculum` folder.
3. Double-click **repair.cmd** in that folder, or run:

```powershell
.\repair.cmd
```

The repair looks for `market.sqlite3` in the project's old `data/demo` and
`data/local` folders, verifies stored hashes, and imports the original price files
into the new local workspace. It preserves source URLs and receipt times. It
then runs research and opens the report when research succeeds. Incomplete
history resumes downloading. If no old cache is present, it downloads the needed
history. Public-source availability is still required for missing sessions.

You do not need to move the project, erase downloads, reinstall Python or run as
administrator. Originals are left in place. If sources contain different bytes
for the same session, repair stops for review before copying any of those files.
An interrupted copy is safe to rerun.

## Data folders after repair

| Use | Windows default | Linux/macOS default |
| --- | --- | --- |
| Real research and manual paper workflows | `%LOCALAPPDATA%\Oraculum\data` | Project `data/local` |
| Fictional demo | `%LOCALAPPDATA%\Oraculum\demo` | Project `data/demo` |

Paste `%LOCALAPPDATA%\Oraculum\data` into File Explorer's address bar to inspect
the new market workspace. `run.cmd doctor` prints the resolved path. The project
may remain in OneDrive; frequently updated market files use the local application
data folder. An explicit `--data-dir PATH` overrides this choice.

The repair copies **only verified price snapshots**. It does not merge portfolios,
research history, old status files, watchlists or manually supplied settings.
Those remain in their original folders. To inspect an old local workspace, use
an explicit folder, for example `run.cmd serve --data-dir data/local` after
stopping another viewer on the same port. The original `data/oraculum.sqlite3`
core database also remains untouched.

After a successful repair, use **research.cmd** for future updates, **start.cmd**
to view saved research, and **demo.cmd** only for the fictional demo. Scheduled
`run-daily.cmd` writes to `%LOCALAPPDATA%\Oraculum\data\daily.log`.

Advanced: recover a cache from another known folder without opening the viewer:

```powershell
.\run.cmd repair-local --from-dir "C:\path\to\old\data\demo"
```

## File-write behavior

Temporary permission errors during atomic replacement get up to six attempts
over approximately 2.8 seconds. The previous destination is never deleted to
force a write. A persistently unavailable progress file prints a warning and
does not interrupt caching, ranking or error reporting. The terminal still shows
the actual outcome; the viewer's progress state can be out of date while that
file is unavailable.

Research JSON, CSV, HTML and `latest.json` remain required. A failure saving any
of them prevents publication of a new report. This fix does not bypass filesystem
permissions or promise that every possible Windows permission problem is solved.

## Verification on 16 October 2026

- 219 tests passed under Python 3.12.14 on Linux, with warnings treated as errors.
- New tests exercise Windows path resolution, explicit overrides, real/demo
  separation, temporary/permanent permission errors, safe progress-file failure,
  preservation of previous reports, recovery conflicts, corruption and reruns.
- Recovered all 60 actual NSE files from the earlier cache (21 July–14 October),
  preserving every raw byte, payload, receipt and source URL. The original database
  stayed byte-for-byte unchanged. A second repair copied zero sessions.
- Offline research from the recovered cache made no network calls and reproduced
  report `70a18ed5835db741ca11cfc38fa87f644f5cd2b5f365c875f04559751699e11e`:
  2,681 stocks, 1,132 eligible and ten technical highlights.
- Windows batch files and native Windows locking were not executed here.
  Permission failures were simulated. The supplied Windows/Linux CI has not been
  run on GitHub by this delivery.

The scoring algorithm is unchanged. This patch adds no new market coverage,
fundamentals, news, trading or claims of predictive performance.
