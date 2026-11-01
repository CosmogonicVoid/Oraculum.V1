# tests/test_qwen_features.py
"""Tests for oraculum.features: pure numerical functions and the point-in-time builder."""
import math
import statistics
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from oraculum.contracts import DAILY_METRICS, ValidationError, iso
from oraculum.features import (
    BasicPriceFeatureBuilder, annualized_volatility, mean_turnover, momentum, trend, volume_ratio,
)
from oraculum.interfaces import PriceBar

UTC = timezone.utc
AS_OF = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class NumericFunctionTests(unittest.TestCase):
    def test_hand_checked_examples(self):
        self.assertAlmostEqual(momentum([100, 110, 121], 2), 0.21)
        self.assertAlmostEqual(trend([100, 110, 120], 3), 120 / 110 - 1)
        self.assertAlmostEqual(volume_ratio([100, 200, 300], 2), 2.0)
        self.assertAlmostEqual(annualized_volatility([100, 110, 121], 2), 0.0)
        self.assertAlmostEqual(mean_turnover([100, 200, 300], 2), 250.0)

    def test_default_windows(self):
        self.assertAlmostEqual(momentum([100.0] * 20 + [110.0]), 0.10)
        self.assertAlmostEqual(trend([100.0] * 50), 0.0)
        self.assertAlmostEqual(volume_ratio([1000] * 20 + [1500]), 1.5)
        self.assertAlmostEqual(annualized_volatility([100.0] * 21), 0.0)
        self.assertAlmostEqual(mean_turnover([10.0] * 20), 10.0)

    def test_insufficient_history_returns_none(self):
        self.assertIsNone(momentum([100, 110], 2))
        self.assertIsNone(momentum([], 20))
        self.assertIsNone(trend([100.0] * 49, 50))
        self.assertIsNone(volume_ratio([100] * 20, 20))
        self.assertIsNone(annualized_volatility([100, 110], 20))
        self.assertIsNone(mean_turnover([1.0] * 19, 20))

    def test_exact_minimum_history_is_usable(self):
        self.assertAlmostEqual(momentum([100, 90, 108], 2), 0.08)
        self.assertAlmostEqual(volume_ratio([10, 20, 30], 2), 2.0)
        self.assertAlmostEqual(annualized_volatility([100, 100, 100], 2), 0.0)
        self.assertAlmostEqual(mean_turnover([5.0], 1), 5.0)

    def test_zero_denominator_volume_ratio_is_none(self):
        self.assertIsNone(volume_ratio([0, 0, 100], 2))
        self.assertAlmostEqual(volume_ratio([5, 0, 0], 2), 0.0)

    def test_constant_prices_have_zero_volatility(self):
        self.assertEqual(annualized_volatility([42.0] * 21, 20), 0.0)

    def test_volatility_matches_sample_standard_deviation(self):
        closes = [100.0, 90.0, 100.0]
        returns = [closes[i] / closes[i - 1] - 1.0 for i in (1, 2)]
        expected = statistics.stdev(returns) * math.sqrt(252)
        self.assertAlmostEqual(annualized_volatility(closes, 2), expected)

    def test_malformed_series_rejected(self):
        cases = [
            lambda: momentum([100, True, 121], 2),
            lambda: momentum([100, float("nan"), 121], 2),
            lambda: momentum([100, math.inf, 121], 2),
            lambda: momentum([100, 0, 121], 2),
            lambda: momentum([100, -5, 121], 2),
            lambda: momentum(["100", "110", "121"], 2),
            lambda: volume_ratio([100, -1, 300], 2),
            lambda: volume_ratio([100, True, 300], 2),
            lambda: volume_ratio([100, 2.5, 300], 2),
            lambda: mean_turnover([100, -0.5, 300], 2),
            lambda: mean_turnover([100, math.nan, 300], 2),
            lambda: trend([100, float("inf"), 120], 3),
        ]
        for case in cases:
            with self.assertRaises(ValidationError):
                case()

    def test_window_arguments_strictly_validated(self):
        for bad in (0, -1, 2.0, 2.5, True, "20", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    momentum([100.0] * 30, bad)
                with self.assertRaises(ValidationError):
                    trend([100.0] * 60, bad)
                with self.assertRaises(ValidationError):
                    volume_ratio([1] * 30, bad)
                with self.assertRaises(ValidationError):
                    mean_turnover([1.0] * 30, bad)
                with self.assertRaises(ValidationError):
                    annualized_volatility([100.0] * 30, bad)
        with self.assertRaises(ValidationError):
            annualized_volatility([100.0, 101.0, 102.0], 1)  # periods must be >= 2

    def test_inputs_are_not_mutated(self):
        closes = [100.0, 105.0, 111.0]
        snapshot = list(closes)
        momentum(closes, 2)
        trend(closes, 3)
        annualized_volatility(closes, 2)
        self.assertEqual(closes, snapshot)

    def test_tuples_are_accepted(self):
        self.assertAlmostEqual(momentum((100, 110, 121), 2), 0.21)


def _bar(index, close="100.00", *, instrument="NSE:TEST", version="v1", source="src",
         volume=1000, turnover=None, available=None, close_at=None,
         open_=None, high=None, low=None):
    session = date(2026, 9, 1) + timedelta(days=index)
    close_d = Decimal(close)
    open_d = Decimal(open_) if open_ is not None else close_d
    high_d = Decimal(high) if high is not None else close_d + Decimal("0.50")
    low_d = Decimal(low) if low is not None else close_d - Decimal("0.50")
    turnover_d = Decimal(turnover) if turnover is not None else close_d * volume
    default_close_at = datetime(session.year, session.month, session.day, 10, 0, tzinfo=UTC)
    return PriceBar(
        instrument_id=instrument, session=session,
        open_at=datetime(session.year, session.month, session.day, 3, 45, tzinfo=UTC),
        close_at=close_at if close_at is not None else default_close_at,
        available_at=available if available is not None else default_close_at.replace(minute=5),
        open=open_d, high=high_d, low=low_d, close=close_d,
        volume=volume, turnover_inr=turnover_d, source_id=source, adjustment_version=version,
    )


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = BasicPriceFeatureBuilder()

    def test_no_eligible_bars_returns_empty_dict(self):
        self.assertEqual(self.builder.build_metrics([], as_of=AS_OF), {})
        future = _bar(0, available=datetime(2026, 10, 2, 0, 0, tzinfo=UTC))
        self.assertEqual(self.builder.build_metrics([future], as_of=AS_OF), {})
        unclosed = _bar(0, close_at=datetime(2026, 10, 2, 0, 0, tzinfo=UTC),
                        available=datetime(2026, 10, 2, 0, 5, tzinfo=UTC))
        self.assertEqual(self.builder.build_metrics([unclosed], as_of=AS_OF), {})

    def test_naive_as_of_rejected(self):
        with self.assertRaisesRegex(ValidationError, "timezone"):
            self.builder.build_metrics([], as_of=datetime(2026, 10, 1, 12, 0))

    def test_point_in_time_cutoff_is_respected(self):
        bars = [_bar(i) for i in range(5)]
        late = _bar(5, available=datetime(2026, 10, 1, 13, 0, tzinfo=UTC))
        with_late = self.builder.build_metrics(bars + [late], as_of=AS_OF)
        without = self.builder.build_metrics(bars, as_of=AS_OF)
        self.assertEqual(with_late, without)

    def test_sufficient_history_produces_all_six_metrics(self):
        bars = [_bar(i, close=str(100 + i)) for i in range(21)]
        result = self.builder.build_metrics(bars, as_of=AS_OF)
        self.assertEqual(set(result), set(DAILY_METRICS))
        self.assertEqual(result["close_inr"]["value"], 120.0)
        self.assertAlmostEqual(result["momentum_20d"]["value"], 120 / 100 - 1)
        self.assertAlmostEqual(result["volume_ratio_20d"]["value"], 1.0)
        self.assertIsNone(result["trend_50d"]["value"])
        self.assertEqual(result["trend_50d"]["source_ids"], [])
        self.assertEqual(result["close_inr"]["observed_at"], result["trend_50d"]["observed_at"])
        self.assertEqual(result["close_inr"]["observed_at"], iso(bars[-1].close_at))

    def test_source_ids_cover_every_bar_used(self):
        bars = [_bar(i, source=f"src-{i:02d}") for i in range(21)]
        result = self.builder.build_metrics(bars, as_of=AS_OF)
        self.assertEqual(result["momentum_20d"]["source_ids"], [f"src-{i:02d}" for i in range(21)])
        self.assertEqual(result["close_inr"]["source_ids"], ["src-20"])

    def test_available_at_is_latest_dependency_availability(self):
        bars = [_bar(i) for i in range(21)]
        result = self.builder.build_metrics(bars, as_of=AS_OF)
        self.assertEqual(result["close_inr"]["available_at"], iso(bars[-1].available_at))
        self.assertEqual(result["momentum_20d"]["available_at"], iso(bars[-1].available_at))

    def test_unsorted_input_is_sorted_and_duplicates_rejected(self):
        bars = [_bar(i, close=str(100 + i)) for i in range(3)]
        result = self.builder.build_metrics([bars[2], bars[0], bars[1]], as_of=AS_OF)
        self.assertEqual(result["close_inr"]["value"], 102.0)
        with self.assertRaisesRegex(ValidationError, "duplicate"):
            self.builder.build_metrics([bars[0], bars[0]], as_of=AS_OF)

    def test_mixed_instruments_rejected(self):
        bars = [_bar(0), _bar(1, instrument="NSE:OTHER")]
        with self.assertRaisesRegex(ValidationError, "one instrument"):
            self.builder.build_metrics(bars, as_of=AS_OF)

    def test_mixed_adjustment_versions_rejected(self):
        bars = [_bar(0), _bar(1, version="v2")]
        with self.assertRaisesRegex(ValidationError, "adjustment_version"):
            self.builder.build_metrics(bars, as_of=AS_OF)

    def test_naive_bar_timestamps_rejected(self):
        naive = PriceBar(
            "NSE:TEST", date(2026, 9, 1),
            datetime(2026, 9, 1, 3, 45, tzinfo=UTC), datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 1, 10, 5),  # naive availability
            Decimal("100"), Decimal("100.5"), Decimal("99.5"), Decimal("100"),
            1000, Decimal("100000"), "src", "v1",
        )
        with self.assertRaisesRegex(ValidationError, "timezone"):
            self.builder.build_metrics([naive], as_of=AS_OF)

    def test_ohlc_geometry_enforced(self):
        for kwargs in ({"high": "99.00"}, {"low": "101.00"}, {"open_": "102.00"}, {"close": "0"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.builder.build_metrics([_bar(0, **kwargs)], as_of=AS_OF)

    def test_volume_and_turnover_checks(self):
        with self.assertRaises(ValidationError):
            self.builder.build_metrics([_bar(0, volume=-1)], as_of=AS_OF)
        with self.assertRaises(ValidationError):
            self.builder.build_metrics([_bar(0, volume=True)], as_of=AS_OF)
        with self.assertRaises(ValidationError):
            self.builder.build_metrics([_bar(0, turnover="-5")], as_of=AS_OF)

    def test_appending_future_bars_does_not_change_history(self):
        base = [_bar(i, close=str(100 + i)) for i in range(21)]
        first = self.builder.build_metrics(base, as_of=AS_OF)
        future = [_bar(21 + j, close=str(200 + j), available=datetime(2026, 10, 5, 0, 0, tzinfo=UTC))
                  for j in range(3)]
        second = self.builder.build_metrics(base + future, as_of=AS_OF)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
