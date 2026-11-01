"""Independent test suite for BasicPaperSimulator (Kimi's Part B).

Covers every required behavior from handoffs/KIMI.md: the two hand-checks,
cash conservation, lookahead prevention across a weekend, accounting and
average-cost rules, duplicate processing, invalid inputs, deterministic
ordering, adjusted-price rejection and input immutability.
"""

import copy
import unittest
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from oraculum.contracts import ValidationError
from oraculum.interfaces import (
    PaperOrder,
    PortfolioState,
    Position,
    PriceBar,
)
from oraculum.paper.simulator import (
    ALREADY_PROCESSED,
    BasicPaperSimulator,
    INSUFFICIENT_CASH,
    INSUFFICIENT_SHARES,
    NO_BAR,
    SESSION_NOT_AFTER_SUBMISSION,
)

IST = timezone(timedelta(hours=5, minutes=30))
D = Decimal
FRI = date(2024, 1, 5)
MON = date(2024, 1, 8)
TUE = date(2024, 1, 9)
WED = date(2024, 1, 10)


def make_bar(instrument="NSE:ABC", session=MON, open_="100", high=None,
             low=None, close=None, volume=1_000_000,
             adjustment_version="raw", open_time=time(9, 15)):
    o = D(str(open_))
    h = o if high is None else D(str(high))
    l = o if low is None else D(str(low))
    c = o if close is None else D(str(close))
    open_at = datetime.combine(session, open_time, IST)
    return PriceBar(
        instrument_id=instrument, session=session, open_at=open_at,
        close_at=datetime.combine(session, time(15, 30), IST),
        available_at=datetime.combine(session, time(15, 35), IST), open=o, high=h, low=l, close=c,
        volume=volume, turnover_inr=D("1000000"), source_id="vendor-x",
        adjustment_version=adjustment_version,
    )


def make_order(order_id="ORD-1", instrument="NSE:ABC", side="buy", quantity=1,
               submitted=None, run_id="run-x"):
    if submitted is None:
        submitted = datetime.combine(FRI, time(9, 0), IST)
    return PaperOrder(order_id=order_id, instrument_id=instrument, side=side,
                      quantity=quantity, submitted_at=submitted,
                      signal_run_id=run_id)


def at(session, hour, minute=0):
    return datetime.combine(session, time(hour, minute), IST)


class SimulatorValidationTests(unittest.TestCase):
    def setUp(self):
        self.sim = BasicPaperSimulator()
        self.state = PortfolioState(D("1000"), (), ())
        self.bars = [make_bar()]
        self.orders = [make_order()]

    def assert_invalid(self, state=None, orders=None, bars=None,
                       fee=D("0"), slip=D("0")):
        with self.assertRaises(ValidationError):
            self.sim.execute_session(
                self.state if state is None else state,
                self.orders if orders is None else orders,
                self.bars if bars is None else bars,
                fee_bps=fee, slippage_bps=slip)

    def test_zero_and_negative_and_bool_quantity_rejected(self):
        for bad in (0, -3, True):
            self.assert_invalid(orders=[make_order(quantity=bad)])

    def test_non_finite_decimals_rejected(self):
        self.assert_invalid(state=PortfolioState(D("NaN"), (), ()))
        self.assert_invalid(state=PortfolioState(D("Infinity"), (), ()))
        self.assert_invalid(bars=[make_bar(open_="Infinity")])
        self.assert_invalid(bars=[make_bar(open_="NaN")])
        self.assert_invalid(fee=D("NaN"))
        self.assert_invalid(slip=D("Infinity"))

    def test_cost_bps_bounds_and_type(self):
        self.assert_invalid(fee=D("1001"))
        self.assert_invalid(fee=D("-0.1"))
        self.assert_invalid(slip=D("1000.1"))
        self.assert_invalid(fee=10)          # floats/ints are not Decimals
        self.assert_invalid(slip=0.001)      # floats/ints are not Decimals
        # Boundary values are legal.
        self.sim.execute_session(self.state, self.orders, self.bars,
                                 fee_bps=D("1000"), slippage_bps=D("1000"))
        self.sim.execute_session(self.state, self.orders, self.bars,
                                 fee_bps=D("0"), slippage_bps=D("0"))

    def test_duplicate_order_ids_rejected(self):
        self.assert_invalid(orders=[make_order("X"), make_order("X")])

    def test_duplicate_bars_rejected(self):
        self.assert_invalid(bars=[make_bar(), make_bar()])

    def test_mixed_sessions_rejected(self):
        self.assert_invalid(bars=[make_bar(session=FRI),
                                  make_bar(session=MON)])

    def test_adjusted_price_bars_rejected(self):
        self.assert_invalid(bars=[make_bar(adjustment_version="split_adjusted")])
        self.assert_invalid(bars=[make_bar(adjustment_version="")])
        # Raw bars are accepted (already exercised elsewhere).

    def test_naive_timestamps_rejected(self):
        naive_order = make_order()
        naive_order = PaperOrder(
            order_id="N1", instrument_id="NSE:ABC", side="buy", quantity=1,
            submitted_at=datetime(2024, 1, 5, 9, 0), signal_run_id="r")
        self.assert_invalid(orders=[naive_order])
        naive_open = datetime.combine(MON, time(9, 15))  # no tzinfo
        bar = PriceBar(
            instrument_id="NSE:ABC", session=MON, open_at=naive_open,
            close_at=at(MON, 15, 30), available_at=naive_open,
            open=D("100"), high=D("100"), low=D("100"), close=D("100"),
            volume=1, turnover_inr=D("1"), source_id="v",
            adjustment_version="raw")
        self.assert_invalid(bars=[bar])

    def test_invalid_ohlc_rejected(self):
        self.assert_invalid(bars=[make_bar(open_="100", high="99")])
        self.assert_invalid(bars=[make_bar(open_="100", low="101")])
        self.assert_invalid(bars=[make_bar(open_="0")])
        self.assert_invalid(bars=[make_bar(open_="-5")])
        self.assert_invalid(bars=[make_bar(open_="100", high="NaN")])

    def test_invalid_state_rejected(self):
        self.assert_invalid(state=PortfolioState(D("-1"), (), ()))
        bad_pos = PortfolioState(D("100"),
                                 (Position("NSE:ABC", 0, D("10")),), ())
        self.assert_invalid(state=bad_pos)
        dup_pos = PortfolioState(D("100"),
                                 (Position("NSE:ABC", 1, D("10")),
                                  Position("NSE:ABC", 2, D("20"))), ())
        self.assert_invalid(state=dup_pos)
        dup_processed = PortfolioState(D("100"), (), ("P", "P"))
        self.assert_invalid(state=dup_processed)

    def test_bool_and_negative_volume_rejected(self):
        self.assert_invalid(bars=[make_bar(volume=True)])
        self.assert_invalid(bars=[make_bar(volume=-1)])

    def test_unrecognized_side_rejected(self):
        self.assert_invalid(orders=[make_order(side="hold")])


class SimulatorHandCheckTests(unittest.TestCase):
    def setUp(self):
        self.sim = BasicPaperSimulator()

    def test_hand_check_zero_fees_and_slippage(self):
        state = PortfolioState(D("1000"), (), ())
        bars = [make_bar(session=MON, open_="100")]
        result = self.sim.execute_session(
            state, [make_order(quantity=3)], bars,
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(result.state.cash_inr, D("700"))
        self.assertEqual(len(result.state.positions), 1)
        pos = result.state.positions[0]
        self.assertEqual(pos.quantity, 3)
        self.assertEqual(pos.average_cost_inr, D("100"))
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].price_inr, D("100"))
        # Sell 2 at 120 in the next session.
        bars2 = [make_bar(session=TUE, open_="120")]
        order2 = make_order(order_id="ORD-2", side="sell", quantity=2,
                            submitted=at(MON, 16, 0))
        result2 = self.sim.execute_session(
            result.state, [order2], bars2,
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(result2.state.cash_inr, D("940"))
        self.assertEqual(len(result2.state.positions), 1)
        pos2 = result2.state.positions[0]
        self.assertEqual(pos2.quantity, 1)
        self.assertEqual(pos2.average_cost_inr, D("100"))

    def test_hand_check_ten_bps_slippage_and_fees(self):
        state = PortfolioState(D("1000"), (), ())
        bars = [make_bar(session=MON, open_="100")]
        result = self.sim.execute_session(
            state, [make_order(quantity=2)], bars,
            fee_bps=D("10"), slippage_bps=D("10"))
        self.assertEqual(result.fills[0].price_inr, D("100.1000"))
        # gross 200.20, fee 0.20, cash 1000 -> 799.60
        self.assertEqual(result.fills[0].fee_inr, D("0.20"))
        self.assertEqual(result.state.cash_inr, D("799.60"))

    def test_cash_conservation_buy_then_sell_with_costs(self):
        state = PortfolioState(D("1000"), (), ())
        r1 = self.sim.execute_session(
            state, [make_order(quantity=4, submitted=at(FRI, 9))],
            [make_bar(session=MON, open_="100")],
            fee_bps=D("10"), slippage_bps=D("10"))
        # buy: fill 100.1000, gross 400.40, fee 0.40 -> cash 599.20
        self.assertEqual(r1.state.cash_inr, D("599.20"))
        r2 = self.sim.execute_session(
            r1.state, [make_order(order_id="S1", side="sell", quantity=4,
                                  submitted=at(MON, 16))],
            [make_bar(session=TUE, open_="120")],
            fee_bps=D("10"), slippage_bps=D("10"))
        # sell: fill 119.8800, gross 479.52, fee 0.48 -> +479.04
        self.assertEqual(r2.state.cash_inr, D("1078.24"))
        self.assertEqual(r2.state.positions, ())

    def test_sell_fee_rounding(self):
        state = PortfolioState(D("1000"),
                               (Position("NSE:ABC", 3, D("90")),), ())
        result = self.sim.execute_session(
            state, [make_order(side="sell", quantity=3,
                               submitted=at(FRI, 9))],
            [make_bar(session=MON, open_="99.99")],
            fee_bps=D("10"), slippage_bps=D("0"))
        self.assertEqual(result.fills[0].price_inr, D("99.9900"))
        self.assertEqual(result.fills[0].fee_inr, D("0.30"))
        self.assertEqual(result.state.cash_inr, D("1299.67"))


class SimulatorExecutionTests(unittest.TestCase):
    def setUp(self):
        self.sim = BasicPaperSimulator()
        self.state = PortfolioState(D("1000"), (), ())

    def test_insufficient_cash_rejects_whole_order_no_partial_fill(self):
        result = self.sim.execute_session(
            self.state, [make_order(quantity=20, submitted=at(FRI, 9))],
            [make_bar(session=MON, open_="100")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(result.fills, ())
        self.assertEqual(len(result.rejections), 1)
        self.assertEqual(result.rejections[0].reason, INSUFFICIENT_CASH)
        self.assertEqual(result.state.cash_inr, D("1000"))
        self.assertEqual(result.state.positions, ())
        # The rejected order is recorded as processed (terminal).
        self.assertEqual(result.state.processed_order_ids, ("ORD-1",))

    def test_overselling_rejected(self):
        state = PortfolioState(D("1000"), (Position("NSE:ABC", 1, D("100")),), ())
        result = self.sim.execute_session(
            state, [make_order(side="sell", quantity=2,
                               submitted=at(FRI, 9))],
            [make_bar(session=MON, open_="100")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(result.fills, ())
        self.assertEqual(result.rejections[0].reason, INSUFFICIENT_SHARES)
        self.assertEqual(result.state.cash_inr, D("1000"))
        self.assertEqual(result.state.positions,
                         (Position("NSE:ABC", 1, D("100")),))

    def test_missing_bar_produces_explicit_rejection(self):
        result = self.sim.execute_session(
            self.state, [make_order(instrument="NSE:XYZ")],
            [make_bar()], fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(result.fills, ())
        self.assertEqual(result.rejections[0].reason, NO_BAR)
        self.assertEqual(result.state.processed_order_ids, ("ORD-1",))

    def test_same_day_lookahead_rejected(self):
        # Submitted at 10:00 after the 09:15 open of the same session.
        result = self.sim.execute_session(
            self.state, [make_order(submitted=at(MON, 10))],
            [make_bar(session=MON, open_="100")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(result.fills, ())
        self.assertEqual(result.rejections[0].reason,
                         SESSION_NOT_AFTER_SUBMISSION)
        self.assertEqual(result.state.cash_inr, D("1000"))

    def test_next_open_after_weekend_uses_session_dates(self):
        order = make_order(submitted=at(FRI, 15, 30))  # after Friday close
        friday = self.sim.execute_session(
            self.state, [order], [make_bar(session=FRI, open_="100")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(friday.fills, ())
        self.assertEqual(friday.rejections[0].reason,
                         SESSION_NOT_AFTER_SUBMISSION)
        # A rejected ID is terminal. Resubmit under a new ID for Monday;
        # no inferred Saturday session is inserted.
        retry = make_order(order_id="MON-RETRY", submitted=at(FRI, 15, 30))
        monday = self.sim.execute_session(
            friday.state, [order, retry], [make_bar(session=MON, open_="101")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(monday.rejections[0].reason, ALREADY_PROCESSED)
        self.assertEqual(monday.fills[0].order_id, "MON-RETRY")
        self.assertEqual(len(monday.fills), 1)
        self.assertEqual(monday.fills[0].filled_at, at(MON, 9, 15))
        self.assertEqual(monday.fills[0].price_inr, D("101"))
        self.assertEqual(monday.fills[0].filled_at.date(), MON)

    def test_repeat_processing_cannot_duplicate_fill(self):
        orders = [make_order(quantity=3, submitted=at(FRI, 9))]
        bars = [make_bar(session=MON, open_="100")]
        first = self.sim.execute_session(self.state, orders, bars,
                                         fee_bps=D("0"), slippage_bps=D("0"))
        second = self.sim.execute_session(first.state, orders, bars,
                                          fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(second.fills, ())
        self.assertEqual(len(second.rejections), 1)
        self.assertEqual(second.rejections[0].reason, ALREADY_PROCESSED)
        self.assertEqual(second.state, first.state)  # nothing changed

    def test_already_processed_id_cannot_change_state(self):
        state = PortfolioState(D("1000"), (), ("ORD-1",))
        result = self.sim.execute_session(
            state, [make_order(quantity=5)], [make_bar()],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(result.fills, ())
        self.assertEqual(result.rejections[0].reason, ALREADY_PROCESSED)
        self.assertEqual(result.state.processed_order_ids, ("ORD-1",))
        self.assertEqual(result.state.cash_inr, D("1000"))

    def test_average_cost_multiple_buys_partial_sale_and_exit(self):
        s1 = self.sim.execute_session(
            self.state, [make_order(quantity=3, submitted=at(FRI, 9))],
            [make_bar(session=MON, open_="100")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(s1.state.positions[0].average_cost_inr, D("100"))
        s2 = self.sim.execute_session(
            s1.state, [make_order(order_id="B2", quantity=2,
                                  submitted=at(MON, 10))],
            [make_bar(session=TUE, open_="110")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(s2.state.positions[0].average_cost_inr, D("104"))
        s3 = self.sim.execute_session(
            s2.state, [make_order(order_id="S1", side="sell", quantity=2,
                                  submitted=at(TUE, 16))],
            [make_bar(session=WED, open_="130")],
            fee_bps=D("0"), slippage_bps=D("0"))
        pos = s3.state.positions[0]
        self.assertEqual((pos.quantity, pos.average_cost_inr), (3, D("104")))
        self.assertEqual(s3.state.cash_inr, D("740"))
        s4 = self.sim.execute_session(
            s3.state, [make_order(order_id="S2", side="sell", quantity=3,
                                  submitted=at(WED, 16))],
            [make_bar(session=date(2024, 1, 11), open_="90")],
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual(s4.state.positions, ())
        self.assertEqual(s4.state.cash_inr, D("1010"))

    def test_average_cost_includes_buy_fees(self):
        s1 = self.sim.execute_session(
            self.state, [make_order(quantity=2, submitted=at(FRI, 9))],
            [make_bar(session=MON, open_="100")],
            fee_bps=D("10"), slippage_bps=D("10"))
        self.assertEqual(s1.state.positions[0].average_cost_inr, D("100.20"))
        s2 = self.sim.execute_session(
            s1.state, [make_order(order_id="B2", quantity=1,
                                  submitted=at(MON, 10))],
            [make_bar(session=TUE, open_="100")],
            fee_bps=D("10"), slippage_bps=D("10"))
        # (2 x 100.20 + 100.20) / 3 = 100.20
        self.assertEqual(s2.state.positions[0].average_cost_inr, D("100.20"))

    def test_session_high_low_close_volume_cannot_improve_fill(self):
        orders = [make_order(quantity=1, submitted=at(FRI, 9))]
        modest = [make_bar(session=MON, open_="100", high="101", low="99",
                           close="100.5", volume=1_000_000)]
        absurd = [make_bar(session=MON, open_="100", high="5000", low="1",
                           close="4000", volume=9_999_999_999)]
        r1 = self.sim.execute_session(self.state, orders, modest,
                                      fee_bps=D("10"), slippage_bps=D("10"))
        r2 = self.sim.execute_state = None  # (see note below)
        r2 = self.sim.execute_session(self.state, orders, absurd,
                                      fee_bps=D("10"), slippage_bps=D("10"))
        self.assertEqual(r1.fills, r2.fills)
        self.assertEqual(r1.fills[0].price_inr, D("100.1000"))

    def test_deterministic_ordering_regardless_of_input_order(self):
        bars = [make_bar(session=MON, open_="100")]
        early = make_order(order_id="B", quantity=1, submitted=at(FRI, 9))
        late = make_order(order_id="A", quantity=1, submitted=at(FRI, 10))
        forward = self.sim.execute_session(
            PortfolioState(D("150"), (), ()), [late, early], bars,
            fee_bps=D("0"), slippage_bps=D("0"))
        backward = self.sim.execute_session(
            PortfolioState(D("150"), (), ()), [early, late], bars,
            fee_bps=D("0"), slippage_bps=D("0"))
        for result in (forward, backward):
            self.assertEqual([f.order_id for f in result.fills], ["B"])
            self.assertEqual(result.rejections[0].order_id, "A")
            self.assertEqual(result.rejections[0].reason, INSUFFICIENT_CASH)
        self.assertEqual(forward.state, backward.state)
        # Tie on submitted_at is broken by order_id.
        first = make_order(order_id="A1", quantity=1, submitted=at(FRI, 9))
        second = make_order(order_id="Z1", quantity=1, submitted=at(FRI, 9))
        tied = self.sim.execute_session(
            PortfolioState(D("150"), (), ()), [second, first], bars,
            fee_bps=D("0"), slippage_bps=D("0"))
        self.assertEqual([f.order_id for f in tied.fills], ["A1"])
        self.assertEqual(tied.rejections[0].order_id, "Z1")

    def test_inputs_are_not_mutated(self):
        state = PortfolioState(D("1000"),
                               (Position("NSE:ABC", 5, D("95")),),
                               ("OLD-1",))
        orders = [make_order(quantity=2, submitted=at(FRI, 9)),
                  make_order(order_id="O2", side="sell", quantity=1,
                             submitted=at(FRI, 9, 30))]
        bars = [make_bar(session=MON, open_="100")]
        snapshot = (copy.deepcopy(state), copy.deepcopy(orders),
                    copy.deepcopy(bars))
        self.sim.execute_session(state, orders, bars,
                                 fee_bps=D("10"), slippage_bps=D("10"))
        self.assertEqual(state, snapshot[0])
        self.assertEqual(orders, snapshot[1])
        self.assertEqual(bars, snapshot[2])


if __name__ == "__main__":
    unittest.main()
