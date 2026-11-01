# Kimi assignment: independent checks and paper execution

Implement your part of Oraculum against the supplied v0.1.0 core. Deliver full files,
not fragments. You own independent verification and the paper simulator; ChatGPT owns
shared interfaces and scoring, and Qwen owns data adapters and feature calculations.

## Files to read

README.md, docs/PROJECT_SPEC.md, docs/CONTRACTS.md, docs/ALGORITHM.md,
oraculum/interfaces.py, oraculum/config.py, oraculum/pipeline.py,
oraculum/scoring.py, and examples/expected_demo_report.json.

## Files you may create

- oraculum/paper/__init__.py
- oraculum/paper/simulator.py
- tests/test_kimi_core_audit.py
- tests/test_kimi_simulator.py
- tests/test_kimi_qwen_features.py, after Qwen's implementation is supplied
- docs/KIMI_REVIEW.md

Do not edit existing files or duplicate the contracts under a different schema.
Report defects with a reproducible test and a proposed change for ChatGPT.
Use only the Python standard library; target Python 3.12+.

## Part A: independent review

Check the equation against independently hand-calculated examples. Do not merely
call internal helpers to compute expected values. Look for future information,
wrong units, volume-direction errors, invalid inputs, misleading coverage labels,
replay changes and high-scoring assets slipping through hard exclusions.

Check the exposed entry point build_run and the persisted report, not just private
functions. Extend with test_kimi_core_audit.py. Preserve existing tests.
If Qwen's code has not arrived, complete the core and simulator work now and report
Qwen review as pending. Do not create passing fake substitutes for missing modules.

## Part B: Decimal paper simulator

Implement BasicPaperSimulator in oraculum/paper/simulator.py. It must satisfy the
PaperSimulator protocol with the existing dataclasses:

    execute_session(
        self, state: PortfolioState, orders: Sequence[PaperOrder],
        bars: Sequence[PriceBar], *, fee_bps: Decimal, slippage_bps: Decimal,
    ) -> SessionResult

It is a pure computation: no global state, I/O, network or mutation of inputs.
All bars in a call describe one actual exchange session, one bar per instrument.
Require adjustment_version == "raw" for fills. Research-adjusted prices must not
be used for execution. Validate OHLC relationships and timezone-aware timestamps.

PortfolioState holds cash_inr, positions and processed_order_ids. Order IDs are
globally unique across the simulation. Validate the entire input before processing:
finite Decimal amounts, nonnegative cash, valid positions, no duplicate instruments,
positive integer quantities (bool is invalid), positive prices and recognized sides.
fee_bps and slippage_bps must be finite Decimal values in [0, 1000].
This upper bound is a sanity check, not a recommended trading-cost estimate.

Execution semantics:

1. Sort orders by submitted_at then order_id for deterministic execution.
2. An order may fill only at a raw session open strictly after submitted_at.
   A signal produced after today's close cannot fill at today's open or close.
3. Use that raw open and the configured slippage:
   buy = open × (1 + slippage_bps / 10000);
   sell = open × (1 - slippage_bps / 10000).
4. Round simulated fill price to 4 decimal places with ROUND_HALF_UP. This is a
   simulation convention, not an assertion about an exchange's tick-size rules.
5. Fee = quantity × fill price × fee_bps / 10000, rounded to INR 0.01.
   Round gross cash notional to INR 0.01 as well.
6. Buy requires enough cash for gross notional plus fee. Sell requires enough owned
   shares. Reject the whole order if it cannot fill; do not partially fill it.
   Also reject a sell if net proceeds would be negative under a pathological input.
7. Buys reduce cash, sells increase cash; no borrowing, short positions or negative cash.
8. Maintain quantity and weighted average cost including buy fees. Use Decimal
   precision of at least 28 inside a localcontext; keep average cost unrounded in
   state. A partial sell leaves the remaining average cost unchanged; remove a
   position when its quantity reaches zero.
9. Append each newly handled order ID to processed_order_ids, whether filled or
   rejected. A previously processed ID produces an "already_processed" rejection
   and cannot change cash or positions.
10. Return a new PortfolioState, PaperFill records and OrderRejection records.

These are market-on-open simulation attempts for the supplied session. Missing
instrument bars, same-session lookahead, insufficient cash or insufficient holdings
produce explicit rejections. Rejected orders are terminal; an outer scheduler must
hold future pending orders until the right session, or create a new order ID to retry.
Reject duplicate order IDs within a call as an input error.

Cash and execution sizing must not use that session's high, low, close or total volume.
Those fields may be checked for data consistency, but they were not known at the
open. If liquidity capacity is added later, it must come from pre-open information.

Do not create an allocation policy, automatic order submission or broker integration.
The first simulator only executes explicit paper orders from its caller. Portfolio
sector caps, liquidity limits, corporate actions, dividends, exact market taxes and
20-session exit scheduling need separate, tested policy extensions before a realistic
historical backtest. Document these limits; do not imply the first simulator covers them.

## Required tests

- Cash conservation for a buy then sell, including fees and both-side slippage.
- Insufficient funds, overselling, zero/negative/bool quantities and non-finite Decimals.
- Same-day lookahead rejected; next-open execution verified across a weekend/holiday
  by using supplied session dates rather than adding one calendar day.
- Repeat processing cannot duplicate a fill.
- Duplicate IDs, duplicate bars and mixed sessions rejected.
- Input state and orders remain unchanged.
- Average-cost handling for multiple buys, partial sales and complete exits.
- Later high/low/close changes cannot improve an otherwise valid open fill.
- Explicit rejection of adjusted-price bars.
- Deterministic ordering regardless of input order.

For a hand-check with zero slippage and zero fees:
start cash INR 1000; buy 3 at INR 100 -> cash 700, 3 shares;
sell 2 at INR 120 -> cash 940, 1 share with average cost INR 100.

For a hand-check with 10 bps slippage and 10 bps fees:
buy 2 with raw open INR 100 -> fill 100.1000; gross 200.20; fee 0.20;
cash from INR 1000 becomes INR 799.60.

Run all core and new tests. Return the created files, actual test output, any failing
core examples and a concise review. If tests could not be executed, say "not run".
No performance or profitability claim can be made from these accounting tests.
