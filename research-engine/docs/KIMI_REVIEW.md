# Kimi review — independent core audit and paper simulator

> Historical contributor review, retained for context. The statements below about
> tests not running and Qwen being unavailable describe the original Kimi session.
> Integration on 2026-10-13 corrected the submitted fixtures and simulator,
> combined both contributions, and passed 161 tests on Python 3.12.14/Linux.
> Current results and changes are in VALIDATION.md and INTEGRATION_REVIEW.md.
> The current simulator uses an isolated Decimal context with at least 28 digits,
> expands precision for large amounts, validates session chronology, and rejects
> fills that round to zero. It is demonstrated by `python -m oraculum.paper.demo`.

## Scope and environment

Delivered files (all new; no existing file modified):

- `oraculum/paper/__init__.py`
- `oraculum/paper/simulator.py`
- `tests/test_kimi_simulator.py`
- `tests/test_kimi_core_audit.py`
- `docs/KIMI_REVIEW.md`

`tests/test_kimi_qwen_features.py` was **not** created: Qwen's implementation
was not supplied, and no substitute or fake-passing test was written.

Inspection coverage in this session: `handoffs/KIMI.md`, `oraculum/interfaces.py`,
`oraculum/scoring.py`, `oraculum/config.py`, `oraculum/pipeline.py`,
`oraculum/contracts.py` (nearly complete), `docs/ALGORITHM.md`, `README.md`.
Not inspected: `oraculum/repository.py`, `oraculum/serialization.py`,
`docs/CONTRACTS.md`, `docs/VALIDATION.md`, `examples/expected_demo_report.json`,
existing tests.

## Test execution status

**Tests not run.** No Python execution environment was available in this
session, so `python -m unittest discover -s tests -v` was not executed here and
no output is claimed. The two simulator hand-checks were verified by hand
arithmetic (see below). The integration harness must run the full suite on
Python 3.12+ (including Windows) and treat any failure as a finding.

Hand-check verification (manual):

1. Zero fees/slippage: 1000 - 3x100 = 700 cash, 3 shares; then
   700 + 2x120 = 940 cash, 1 share, average cost 100. Correct.
2. 10 bps both: fill = 100 x 1.001 = 100.1000; gross = 200.20; fee = 0.20;
   cash = 1000 - 200.40 = 799.60. Correct.

## Part A — core audit findings

Method: expected scores are re-derived inside `tests/test_kimi_core_audit.py`
from the published equation in `docs/ALGORITHM.md` by independent code that
does not call `oraculum.scoring` helpers. The public `build_run` entry point
is exercised end to end with hand-built canonical bundles, plus SQLite
persistence via `RunRepository` as documented in `README.md`.

Behaviors verified statically and encoded as tests:

- Scoring equation: `clip(50 + 50*sum(w*z) - 15*(1-C) - 10*clip((s-0.20)/0.40,0,1), 0, 100)`
  matches the code; the documented worked fixture (79.00 = 50 + 30 - 0 - 1)
  reproduces from independently chosen metric values that yield the same
  factor contributions listed in `docs/ALGORITHM.md`.
- Coverage is the sum of weights of available factors (not a factor count),
  and missing factors are penalized, not reweighted.
- Volume confirmation direction: falling prices with a volume surge
  contribute negatively; zero momentum contributes exactly zero.
- Hard exclusions: liquidity floor, financials sector, volatility ceiling,
  debt ceiling, minimum coverage, stale price session, and the four required
  risk inputs (`close_inr`, `turnover_20d_inr`, `volatility_20d_annualized`,
  `debt_to_equity`). An excluded asset keeps its diagnostic score but never
  enters the shortlist.
- Freshness cutoffs: daily observation age 7 days, fundamental availability
  200 days / observation 550 days, news 7 days, announcements 14 days; each
  produces the documented `unavailable_reason` text and, for required
  controls, a blocker.
- Input validation through `build_run`: missing/unknown fields, naive
  timestamps, invalid sector, non-numeric metric values, config weights not
  summing to 1, naive `generated_at` — all must raise `ValidationError`.
- Replay consistency: identical input/config/version reproduce `run_id`,
  hashes, decisions and shortlist regardless of `generated_at`; any input
  change changes `run_id`. The persisted-report test saves twice (idempotent),
  verifies on-disk content via `sqlite3`, replays from the persisted
  `input`/`config` snapshot, and explicitly closes every connection before
  temporary-directory cleanup (Windows-safe).

**No confirmed core defects** were found by static review. Residual risks for
integration: (a) `repository.py` internals were not read — the persistence
test assumes the README-documented `RunRepository(path).save(report)` API
returning the saved report; (b) audit bundles use `mode="synthetic"` and
complete `ResearchBundle.to_dict()` round-trips, which should satisfy
`parse_bundle`, but that strict parser's full rule set (clipped during
inspection) was not re-verified line by line; (c) the cross-check against
`examples/expected_demo_report.json` (SIM-ASTER 79.00, SIM-BANYAN 68.00,
SIM-CEDAR 50.00, SIM-DUNE 31.00, four excluded) should be run at integration
via `python -m oraculum demo`.

## Qwen audit status

**Pending.** Qwen's price-feature and CSV adapter implementation was not
supplied, so no feature audit was possible and no stand-in modules were
created. `tests/test_kimi_qwen_features.py` remains to be written once Qwen's
real code arrives.

## Part B — simulator notes and limitations

`BasicPaperSimulator` is a pure function: no I/O, network, global state or
input mutation; Decimal accounting inside a `localcontext(prec=28)`;
whole-input validation before processing; deterministic ordering by
`(submitted_at, order_id)`; fills only at a raw open strictly after
submission; 4-dp ROUND_HALF_UP fill prices; INR 0.01 fee/gross rounding;
no partial fills; average cost includes buy fees and stays unrounded;
filled and rejected IDs are recorded as processed and can never fill again;
adjusted (`adjustment_version != "raw"`), duplicate, mixed-session and
inconsistent-OHLC bars are input errors; the session's high/low/close/volume
are validated but never used for execution or sizing.

Documented limitations (not implied to be covered): sector caps, liquidity
capacity, corporate actions, dividends, exact market taxes, 20-session exit
scheduling, allocation policy, automated order submission, broker integration
and any real-money functionality. Rejected orders are terminal; an outer
scheduler must hold future pending orders for the right session or issue a
new order ID to retry.

## Disclaimer

All accounting tests verify cash/share bookkeeping only. They demonstrate
nothing about investment profitability, and no performance claim is made.
