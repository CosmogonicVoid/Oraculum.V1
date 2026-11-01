"""Basic pure paper execution simulator.

Implements the PaperSimulator protocol from oraculum.interfaces using only the
Python standard library and Decimal accounting.

Execution rules (per handoffs/KIMI.md):
  * The entire input is validated before any order is processed.
  * Every bar in a call describes one actual exchange session; one bar per
    instrument; adjustment_version must be "raw" (research-adjusted prices are
    never used for execution).
  * Orders are executed in deterministic order: submitted_at, then order_id.
  * An order may fill only at a raw session open strictly after submitted_at;
    a signal produced after a session's open cannot fill at that session.
  * Buy fill = open x (1 + slippage_bps/10000); sell fill = open x
    (1 - slippage_bps/10000); fill price rounded to 4 decimal places,
    ROUND_HALF_UP (a simulation convention, not an exchange tick-size claim).
  * Gross notional and fee are rounded to INR 0.01, ROUND_HALF_UP.
  * Buys require cash >= gross + fee; sells require owned shares and
    nonnegative net proceeds. Orders never partially fill.
  * Weighted average cost includes buy fees and stays unrounded in state; a
    partial sell leaves average cost unchanged; a zero-quantity position is
    removed.
  * Filled and rejected order IDs are appended to processed_order_ids; a
    previously processed ID yields an "already_processed" rejection and can
    never change cash or positions again.

Documented limitations (not covered by this first simulator): sector caps,
liquidity capacity, corporate actions, dividends, exact market taxes, exit
scheduling, allocation policy, automatic order submission, broker integration
and any real-money functionality. Execution sizing uses only the session open;
high/low/close/total volume of the session are validated for consistency but
never used to decide execution or sizing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

from ..contracts import IST, ValidationError
from ..interfaces import (
    OrderRejection,
    PaperFill,
    PaperOrder,
    PortfolioState,
    Position,
    PriceBar,
    SessionResult,
)

_CENT = Decimal("0.01")
_PRICE_QUANT = Decimal("0.0001")
_BPS_DENOMINATOR = Decimal("10000")
_ONE = Decimal(1)
_MAX_COST_BPS = Decimal("1000")
_SIDES = frozenset({"buy", "sell"})

# Stable rejection reasons; part of the module's observable behavior.
ALREADY_PROCESSED = "already_processed"
NO_BAR = "no_bar"
SESSION_NOT_AFTER_SUBMISSION = "session_not_after_submission"
INSUFFICIENT_CASH = "insufficient_cash"
INSUFFICIENT_SHARES = "insufficient_shares"
NEGATIVE_NET_PROCEEDS = "negative_net_proceeds"


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ValidationError(f"{path}: {message}")


def _finite_decimal(value: object, path: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise ValidationError(f"{path}: expected a Decimal amount")
    if not value.is_finite():
        raise ValidationError(f"{path}: expected a finite Decimal amount")
    return value


def _aware(value: object, path: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError(f"{path}: expected a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{path}: timezone-aware timestamp required")
    return value


def _identifier(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{path}: expected a nonempty identifier")
    return value


def _quantity(value: object, path: str) -> int:
    # type(value) is not int also excludes bool, which is required.
    if type(value) is not int:
        raise ValidationError(f"{path}: expected a positive integer quantity")
    if value <= 0:
        raise ValidationError(f"{path}: quantity must be positive")
    return value


def _validate_cost_bps(value: object, path: str) -> Decimal:
    bps = _finite_decimal(value, path)
    _require(Decimal(0) <= bps <= _MAX_COST_BPS, path,
             f"must be a finite Decimal within [0, {_MAX_COST_BPS}]")
    return bps


def _validate_state(state: object) -> None:
    if not isinstance(state, PortfolioState):
        raise ValidationError("state: expected a PortfolioState")
    cash = _finite_decimal(state.cash_inr, "state.cash_inr")
    _require(cash >= 0, "state.cash_inr", "cash must be nonnegative")
    _sequence(state.positions, "state.positions")
    _sequence(state.processed_order_ids, "state.processed_order_ids")
    seen_instruments: set[str] = set()
    for index, pos in enumerate(state.positions):
        path = f"state.positions[{index}]"
        if not isinstance(pos, Position):
            raise ValidationError(f"{path}: expected a Position")
        instrument = _identifier(pos.instrument_id, f"{path}.instrument_id")
        _require(instrument not in seen_instruments, f"{path}.instrument_id",
                 "duplicate instrument in positions")
        seen_instruments.add(instrument)
        _quantity(pos.quantity, f"{path}.quantity")
        cost = _finite_decimal(pos.average_cost_inr, f"{path}.average_cost_inr")
        _require(cost >= 0, f"{path}.average_cost_inr",
                 "average cost must be nonnegative")
    seen_ids: set[str] = set()
    for index, order_id in enumerate(state.processed_order_ids):
        _identifier(order_id, f"state.processed_order_ids[{index}]")
        _require(order_id not in seen_ids, f"state.processed_order_ids[{index}]",
                 "duplicate processed order id")
        seen_ids.add(order_id)


def _validate_order(order: object, index: int, seen_ids: set[str]) -> None:
    path = f"orders[{index}]"
    if not isinstance(order, PaperOrder):
        raise ValidationError(f"{path}: expected a PaperOrder")
    order_id = _identifier(order.order_id, f"{path}.order_id")
    _require(order_id not in seen_ids, f"{path}.order_id",
             "duplicate order_id within one call")
    seen_ids.add(order_id)
    _identifier(order.instrument_id, f"{path}.instrument_id")
    _require(isinstance(order.side, str) and order.side in _SIDES, f"{path}.side",
             "side must be 'buy' or 'sell'")
    _quantity(order.quantity, f"{path}.quantity")
    _aware(order.submitted_at, f"{path}.submitted_at")
    _identifier(order.signal_run_id, f"{path}.signal_run_id")


def _validate_bar(bar: object, index: int, session_holder: list,
                  seen_instruments: set[str]) -> None:
    path = f"bars[{index}]"
    if not isinstance(bar, PriceBar):
        raise ValidationError(f"{path}: expected a PriceBar")
    instrument = _identifier(bar.instrument_id, f"{path}.instrument_id")
    _require(bar.adjustment_version == "raw", f"{path}.adjustment_version",
             "only raw adjustment_version bars may be used for execution")
    _require(type(bar.session) is date, f"{path}.session",
             "expected an exchange session date")
    if session_holder[0] is None:
        session_holder[0] = bar.session
    else:
        _require(bar.session == session_holder[0], path,
                 "all bars must describe one actual exchange session")
    _require(instrument not in seen_instruments, f"{path}.instrument_id",
             "duplicate instrument bar within one call")
    seen_instruments.add(instrument)
    open_ = _finite_decimal(bar.open, f"{path}.open")
    high = _finite_decimal(bar.high, f"{path}.high")
    low = _finite_decimal(bar.low, f"{path}.low")
    close = _finite_decimal(bar.close, f"{path}.close")
    for name, price in (("open", open_), ("high", high),
                        ("low", low), ("close", close)):
        _require(price > 0, f"{path}.{name}", "price must be positive")
    _require(low <= open_ and low <= close, f"{path}.low",
             "low must not exceed open or close")
    _require(high >= open_ and high >= close, f"{path}.high",
             "high must not be below open or close")
    _require(type(bar.volume) is int and bar.volume >= 0, f"{path}.volume",
             "expected a nonnegative integer volume")
    turnover = _finite_decimal(bar.turnover_inr, f"{path}.turnover_inr")
    _require(turnover >= 0, f"{path}.turnover_inr",
             "turnover must be nonnegative")
    _aware(bar.open_at, f"{path}.open_at")
    _aware(bar.close_at, f"{path}.close_at")
    _aware(bar.available_at, f"{path}.available_at")
    _identifier(bar.source_id, f"{path}.source_id")
    _require(bar.open_at < bar.close_at <= bar.available_at, path,
             "require open_at < close_at <= available_at for a completed daily bar")
    _require(all(stamp.astimezone(IST).date() == bar.session
                 for stamp in (bar.open_at, bar.close_at)), path,
             "open_at/close_at must match the session date in India")


def _sequence(value: object, path: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValidationError(f"{path}: expected a sequence")


def _accounting_context(state, orders, bars, fee, slippage) -> Context:
    """Isolate arithmetic from caller settings and retain small cash debits.

    Precision expands for large balances and detailed input costs. Recurring
    average costs remain finite-precision Decimals, with at least 28 digits.
    The 10,000-digit bound rejects unusable numeric inputs before execution.
    """
    amounts = [state.cash_inr, fee, slippage]
    amounts.extend(p.average_cost_inr for p in state.positions)
    amounts.extend(b.open for b in bars)
    integer_digits = max(max(1, value.adjusted() + 1) for value in amounts)
    fractional_digits = max(max(0, -value.as_tuple().exponent) for value in amounts)
    quantities = [p.quantity for p in state.positions] + [o.quantity for o in orders] + [1]
    # A bit-length bound avoids converting arbitrarily large integers to text.
    quantity_digits = max(q.bit_length() * 30103 // 100000 + 1 for q in quantities)
    precision = max(28, integer_digits + 2 * fractional_digits + 2 * quantity_digits
                    + len(str(len(orders) + 1)) + 12)
    if precision > 10000:
        raise ValidationError("accounting: inputs exceed the supported 10,000-digit precision budget")
    # Explicit constructor settings prevent caller rounding/traps from leaking in.
    return Context(prec=precision, rounding=ROUND_HALF_UP, Emin=-999999, Emax=999999,
                   capitals=1, clamp=0, flags=[], traps=[])


class BasicPaperSimulator:
    """Pure market-on-open paper simulator; see the module docstring."""

    def execute_session(
        self, state: PortfolioState, orders: Sequence[PaperOrder],
        bars: Sequence[PriceBar], *, fee_bps: Decimal, slippage_bps: Decimal,
    ) -> SessionResult:
        _sequence(orders, "orders")
        _sequence(bars, "bars")
        orders_list = list(orders)
        bars_list = list(bars)

        # Validate the entire input before processing anything.
        fee = _validate_cost_bps(fee_bps, "fee_bps")
        slippage = _validate_cost_bps(slippage_bps, "slippage_bps")
        _validate_state(state)
        seen_order_ids: set[str] = set()
        for index, order in enumerate(orders_list):
            _validate_order(order, index, seen_order_ids)
        session_holder: list = [None]
        seen_instruments: set[str] = set()
        for index, bar in enumerate(bars_list):
            _validate_bar(bar, index, session_holder, seen_instruments)

        bar_by_instrument = {b.instrument_id: b for b in bars_list}
        cash = state.cash_inr
        qty_by_inst = {p.instrument_id: p.quantity for p in state.positions}
        cost_by_inst = {p.instrument_id: p.average_cost_inr
                        for p in state.positions}
        processed = set(state.processed_order_ids)
        handled: list[str] = []
        fills: list[PaperFill] = []
        rejections: list[OrderRejection] = []

        with localcontext(_accounting_context(state, orders_list, bars_list, fee, slippage)):
            ordered = sorted(orders_list,
                             key=lambda o: (o.submitted_at, o.order_id))
            for order in ordered:
                order_id = order.order_id
                if order_id in processed:
                    rejections.append(OrderRejection(order_id, ALREADY_PROCESSED))
                    continue
                bar = bar_by_instrument.get(order.instrument_id)
                if bar is None:
                    rejections.append(OrderRejection(order_id, NO_BAR))
                    handled.append(order_id)
                    processed.add(order_id)
                    continue
                # Lookahead prevention: fill only at an open strictly after
                # the submission time. The session's high/low/close/volume are
                # never read here.
                if not bar.open_at > order.submitted_at:
                    rejections.append(
                        OrderRejection(order_id, SESSION_NOT_AFTER_SUBMISSION))
                    handled.append(order_id)
                    processed.add(order_id)
                    continue
                if order.side == "buy":
                    raw_fill = bar.open * (_ONE + slippage / _BPS_DENOMINATOR)
                else:
                    raw_fill = bar.open * (_ONE - slippage / _BPS_DENOMINATOR)
                fill_price = raw_fill.quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)
                quantity = order.quantity
                gross_exact = fill_price * quantity
                gross = gross_exact.quantize(_CENT, rounding=ROUND_HALF_UP)
                _require(fill_price.is_finite() and gross.is_finite(), order_id,
                         "execution amounts exceed supported numeric precision")
                _require(fill_price > 0 and gross > 0, order_id,
                         "fill price or gross rounds to zero at the simulator's accounting precision")
                fee_inr = (gross_exact * fee / _BPS_DENOMINATOR).quantize(
                    _CENT, rounding=ROUND_HALF_UP)
                if order.side == "buy":
                    total = gross + fee_inr
                    if total > cash:
                        rejections.append(OrderRejection(order_id, INSUFFICIENT_CASH))
                        handled.append(order_id)
                        processed.add(order_id)
                        continue
                    cash -= total
                    held = qty_by_inst.get(order.instrument_id, 0)
                    if held:
                        new_cost = ((cost_by_inst[order.instrument_id] * held
                                     + total) / (held + quantity))
                    else:
                        new_cost = total / quantity
                    qty_by_inst[order.instrument_id] = held + quantity
                    cost_by_inst[order.instrument_id] = new_cost
                else:
                    held = qty_by_inst.get(order.instrument_id, 0)
                    if quantity > held:
                        rejections.append(OrderRejection(order_id, INSUFFICIENT_SHARES))
                        handled.append(order_id)
                        processed.add(order_id)
                        continue
                    net = gross - fee_inr
                    if net < 0:
                        rejections.append(
                            OrderRejection(order_id, NEGATIVE_NET_PROCEEDS))
                        handled.append(order_id)
                        processed.add(order_id)
                        continue
                    cash += net
                    remaining = held - quantity
                    if remaining == 0:
                        qty_by_inst.pop(order.instrument_id, None)
                        cost_by_inst.pop(order.instrument_id, None)
                    else:
                        qty_by_inst[order.instrument_id] = remaining
                fills.append(PaperFill(
                    order_id=order_id,
                    instrument_id=order.instrument_id,
                    side=order.side,
                    quantity=quantity,
                    price_inr=fill_price,
                    fee_inr=fee_inr,
                    filled_at=bar.open_at,
                ))
                handled.append(order_id)
                processed.add(order_id)

        positions = tuple(
            Position(instrument_id=instrument,
                     quantity=qty_by_inst[instrument],
                     average_cost_inr=cost_by_inst[instrument])
            for instrument in sorted(qty_by_inst)
        )
        new_state = PortfolioState(
            cash_inr=cash,
            positions=positions,
            processed_order_ids=(tuple(state.processed_order_ids)
                                 + tuple(handled)),
        )
        return SessionResult(state=new_state, fills=tuple(fills),
                             rejections=tuple(rejections))
