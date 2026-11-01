# examples/qwen — clearly labeled SYNTHETIC fixtures (not real market data)

These files demonstrate the Qwen CSV adapter end to end. All instruments,
prices, volumes and timestamps are fictional and were constructed by hand for
contract testing. They demonstrate plumbing and arithmetic, not market behavior,
and they carry no predictive meaning.

Files:
- `sessions.json` — explicit NSE-style session calendar (09:15–15:30 IST,
  03:45Z–10:00Z), 2026-07-27 through 2026-10-09 plus one future session
  (2026-10-12) to show that the calendar may extend past `as_of`.
- `base.json` — valid ResearchBundle base: dataset identity, `as_of`, sources
  (`qw-prices`, `qw-fundamentals`), sectors and non-daily fundamentals. Daily
  metrics are intentionally omitted.
- `prices.csv` — price tape with columns exactly as specified in
    handoffs/QWEN.md:
  - NSE:QW-ALPHA: 55 contiguous sessions, linear uptrend, last-day volume
    1.8x -> all six daily metrics computable.
  - NSE:QW-BETA: 5 sessions ending 2026-10-08 -> visibly stale asset.
  - NSE:QW-GAMMA: 7 sessions with a gap before 2026-10-08 -> contiguous suffix
    of 2 sessions; only `close_inr` is available.

Build, validate and rank (run from the project root):

    python -m oraculum.providers.csv_provider --prices examples/qwen/prices.csv --base-bundle examples/qwen/base.json --sessions examples/qwen/sessions.json --output tmp/qwen_bundle.json
    python -m oraculum validate --input tmp/qwen_bundle.json
    python -m oraculum rank --input tmp/qwen_bundle.json --config config/default.json --no-save

Verified in the 2026-10-13 integration review (Python 3.12.14/Linux):
QW-ALPHA candidate with score about 72.91 and coverage 0.80; QW-BETA and
QW-GAMMA excluded (stale session / missing required risk inputs). Counts:
candidate 1, watch 0, excluded 2.
