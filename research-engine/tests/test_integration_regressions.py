"""Regression checks from the combined Qwen/Kimi integration review."""
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D, Inexact, ROUND_DOWN, localcontext
from pathlib import Path

from oraculum.contracts import ValidationError
from oraculum.features import BasicPriceFeatureBuilder, mean_turnover, momentum, volume_ratio
from oraculum.interfaces import PortfolioState, Position
from oraculum.paper.simulator import BasicPaperSimulator
from oraculum.pipeline import build_run
from oraculum.providers.csv_provider import build_merged_bundle
from tests import test_kimi_simulator as paper
from tests import test_qwen_csv_provider as csv_tests
from tests import test_qwen_features as feature_tests


class FeatureRegressions(unittest.TestCase):
    def test_unknown_volume_ratio_has_no_evidence(self):
        bars = [feature_tests._bar(i, volume=0) for i in range(21)]
        metrics = BasicPriceFeatureBuilder().build_metrics(bars, as_of=feature_tests.AS_OF)
        self.assertIsNone(metrics["volume_ratio_20d"]["value"])
        self.assertEqual(metrics["volume_ratio_20d"]["source_ids"], [])

    def test_invalid_input_shapes_raise_validation_error(self):
        builder = BasicPriceFeatureBuilder()
        for bad in (None, 12, "100"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                momentum(bad)
        for bad in (None, 12, [None]):
            with self.subTest(bars=bad), self.assertRaises(ValidationError):
                builder.build_metrics(bad, as_of=feature_tests.AS_OF)
        with self.assertRaises(ValidationError):
            builder.build_metrics([], as_of="2026-10-01")

    def test_nonrepresentable_features_do_not_leak_infinity(self):
        for call in (lambda: momentum([1e-300, 1e300], 1),
                     lambda: volume_ratio([1, 10**1000], 1),
                     lambda: BasicPriceFeatureBuilder().build_metrics(
                         [replace(feature_tests._bar(0), close=D("1e1000"), high=D("1e1000"))],
                         as_of=feature_tests.AS_OF)):
            with self.assertRaises(ValidationError):
                call()
        self.assertEqual(mean_turnover([1e308, 1e308], 2), 1e308)

    def test_daily_bar_dates_and_chronology_validated(self):
        bar = feature_tests._bar(0)
        variants = [replace(bar, open_at=bar.close_at),
                    replace(bar, available_at=bar.open_at),
                    replace(bar, session=bar.session + timedelta(days=1)),
                    replace(bar, source_id="")]
        for bad in variants:
            with self.subTest(bar=bad), self.assertRaises(ValidationError):
                BasicPriceFeatureBuilder().build_metrics([bad], as_of=feature_tests.AS_OF)


class CsvRegressions(unittest.TestCase):
    def setUp(self):
        self.fixture = csv_tests.ProviderCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_two_adjusted_vintages_at_cutoff_are_ambiguous(self):
        f = self.fixture
        rows = [csv_tests.bar_row("NSE:TESTA", f.dates[-1], value, version=version)
                for value, version in ((100, "v1"), (200, "v2"))]
        for tape in (rows, list(reversed(rows))):
            with self.assertRaisesRegex(ValidationError, "ambiguous"):
                build_merged_bundle(*f.write_inputs(tape))

    def test_unavailable_new_vintage_cannot_break_existing_window(self):
        f = self.fixture
        rows = [csv_tests.bar_row("NSE:TESTA", d, 100 + i, version="v1")
                for i, d in enumerate(f.dates)]
        first = build_merged_bundle(*f.write_inputs(rows))
        late = csv_tests.bar_row("NSE:TESTA", f.dates[-1], 999, version="v2",
                                 available="2026-10-09T13:00:00Z")
        second = build_merged_bundle(*f.write_inputs(rows + [late]))
        self.assertEqual(first, second)
        self.assertEqual(build_run(first)["run_id"], build_run(second)["run_id"])

    def test_unavailable_middle_session_breaks_history(self):
        f = self.fixture
        rows = [csv_tests.bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(f.dates)]
        rows[18][4] = "2026-10-09T13:00:00Z"
        bundle = build_merged_bundle(*f.write_inputs(rows))
        asset = next(a for a in bundle.assets if a.instrument_id == "NSE:TESTA")
        self.assertEqual(asset.metrics["close_inr"].value, 124)
        self.assertIsNone(asset.metrics["momentum_20d"].value)

    def test_negative_volume_and_early_availability_identify_row(self):
        f = self.fixture
        good = csv_tests.bar_row("NSE:TESTA", f.dates[-1], 100)
        for index, value, message in ((9, "-1", "volume"),
                                      (4, f"{f.dates[-1]}T03:45:00Z", "available_at")):
            row = list(good)
            row[index] = value
            with self.assertRaisesRegex(ValidationError, "row 2.*" + message):
                build_merged_bundle(*f.write_inputs([row]))

    def test_force_cannot_overwrite_input_through_hardlink(self):
        f = self.fixture
        paths = f.write_inputs([csv_tests.bar_row("NSE:TESTA", f.dates[-1], 100)])
        alias = f.folder / "alias.json"
        try:
            alias.hardlink_to(paths[1])
        except OSError as exc:
            self.skipTest(f"Hardlinks unavailable on this filesystem: {exc}")
        before = paths[1].read_bytes()
        code, _, err = f.run_cli("--prices", str(paths[0]), "--base-bundle", str(paths[1]),
                                 "--sessions", str(paths[2]), "--output", str(alias), "--force")
        self.assertEqual(code, 2, err)
        self.assertEqual(paths[1].read_bytes(), before)

    def test_provider_module_starts_without_runtime_warning(self):
        result = subprocess.run([sys.executable, "-W", "error", "-m",
                                 "oraculum.providers.csv_provider", "--help"],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_core_export_cannot_overwrite_an_input_hardlink(self):
        f = self.fixture
        _, base, _ = f.write_inputs([])
        alias = f.folder / "report.json"
        try:
            alias.hardlink_to(base)
        except OSError as exc:
            self.skipTest(f"Hardlinks unavailable on this filesystem: {exc}")
        before = base.read_bytes()
        result = subprocess.run([sys.executable, "-m", "oraculum", "rank", "--input", str(base),
                                 "--no-save", "--output", str(alias), "--force"],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(base.read_bytes(), before)


class PaperRegressions(unittest.TestCase):
    def execute(self, *, state=None, orders=None, bars=None):
        return BasicPaperSimulator().execute_session(
            state if state is not None else PortfolioState(D("1000"), (), ()),
            orders if orders is not None else [paper.make_order()],
            bars if bars is not None else [paper.make_bar()], fee_bps=D(0), slippage_bps=D(0))

    def test_invalid_bar_dates_and_chronology_cannot_fill(self):
        bar = paper.make_bar()
        for bad in (replace(bar, session=bar.open_at),
                    replace(bar, session=bar.session + timedelta(days=1)),
                    replace(bar, close_at=bar.open_at),
                    replace(bar, available_at=bar.open_at),
                    replace(bar, source_id="")):
            with self.subTest(bar=bad), self.assertRaises(ValidationError):
                self.execute(bars=[bad])

    def test_malformed_sequences_and_sides_have_clear_errors(self):
        for kwargs in ({"orders": 1}, {"bars": 1},
                       {"orders": [paper.make_order(side=[])]},
                       {"state": PortfolioState(D(1000), None, ())}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.execute(**kwargs)

    def test_rounding_cannot_create_free_shares(self):
        for price in ("0.00001", "0.0001"):
            with self.subTest(price=price), self.assertRaises(ValidationError):
                self.execute(bars=[paper.make_bar(open_=price)])

    def test_global_decimal_context_cannot_change_accounting(self):
        orders = [paper.make_order(quantity=3)]
        with localcontext() as context:
            context.prec = 5
            context.rounding = ROUND_DOWN
            context.traps[Inexact] = True
            actual = BasicPaperSimulator().execute_session(
                PortfolioState(D(1000), (Position("NSE:ABC", 4, D("100")),), ()),
                orders, [paper.make_bar(open_="100.1234")], fee_bps=D("1.25"), slippage_bps=D("2.5"))
        expected = BasicPaperSimulator().execute_session(
            PortfolioState(D(1000), (Position("NSE:ABC", 4, D("100")),), ()),
            orders, [paper.make_bar(open_="100.1234")], fee_bps=D("1.25"), slippage_bps=D("2.5"))
        self.assertEqual(actual, expected)

    def test_large_cash_balance_still_records_exact_debit(self):
        actual = self.execute(state=PortfolioState(D("1e40"), (), ()))
        self.assertEqual(actual.state.cash_inr, D("9999999999999999999999999999999999999900.00"))

    def test_research_to_next_open_paper_execution(self):
        folder = Path(__file__).resolve().parents[1] / "examples" / "qwen"
        bundle = build_merged_bundle(folder / "prices.csv", folder / "base.json", folder / "sessions.json")
        report = build_run(bundle)
        instrument = report["shortlist"][0]
        self.assertEqual(instrument, "NSE:QW-ALPHA")
        order = paper.make_order(instrument=instrument, submitted=bundle.as_of, run_id=report["run_id"])
        bar = paper.make_bar(instrument=instrument, session=datetime(2026, 10, 12).date(), open_="130")
        result = self.execute(orders=[order], bars=[bar])
        self.assertEqual(result.state.cash_inr, D("870.00"))
        self.assertEqual(result.state.positions[0].instrument_id, instrument)
        self.assertEqual(result.fills[0].filled_at, bar.open_at)
        self.assertGreater(result.fills[0].filled_at, bundle.as_of)
        repeated = self.execute(state=result.state, orders=[order], bars=[bar])
        self.assertEqual(repeated.state, result.state)
        self.assertEqual(repeated.fills, ())


if __name__ == "__main__":
    unittest.main()
