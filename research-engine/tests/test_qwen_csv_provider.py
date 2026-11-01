# tests/test_qwen_csv_provider.py
"""Tests for the supplied-data CSV adapter and CsvResearchProvider."""
import csv
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from oraculum.contracts import ValidationError, parse_bundle
from oraculum.pipeline import build_run
from oraculum.providers.csv_provider import (
    CSV_HEADER, CsvResearchProvider, build_merged_bundle, main,
)
from oraculum.serialization import load_json

UTC = timezone.utc
EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "qwen"


def weekdays_ending(end: date, count: int) -> list[date]:
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def calendar_payload(dates):
    return {"sessions": [
        {"session": d.isoformat(),
         "open_at": f"{d.isoformat()}T03:45:00Z",
         "close_at": f"{d.isoformat()}T10:00:00Z"}
        for d in dates
    ]}


def price_source(sid="prices-a", available="2026-10-09T10:05:00Z"):
    return {"id": sid, "kind": "prices", "title": "Synthetic test prices",
            "uri": f"fixture://qwen/{sid}", "published_at": available,
            "available_at": available, "content_sha256": None}


def fundamentals_source(sid="fundamentals-f", available="2026-08-12T04:30:00Z"):
    return {"id": sid, "kind": "fundamentals", "title": "Synthetic test fundamentals",
            "uri": f"fixture://qwen/{sid}", "published_at": available,
            "available_at": available, "content_sha256": None}


def base_payload(as_of="2026-10-09T12:00:00Z", last_session="2026-10-09",
                 session_close_at="2026-10-09T10:00:00Z", sources=None, assets=None,
                 dataset_id="qw-test-v1", mode="synthetic"):
    return {"schema_version": 1, "dataset_id": dataset_id, "mode": mode, "as_of": as_of,
            "last_session": last_session, "session_close_at": session_close_at,
            "sources": sources or [], "assets": assets or []}


def asset_payload(symbol, sector="industrials", session="2026-10-09", metrics=None):
    return {"symbol": symbol, "exchange": "NSE", "sector": sector,
            "session": session, "metrics": metrics or {}}


def fundamental_metric(value=0.26, sid="fundamentals-f"):
    return {"value": value, "observed_at": "2026-06-30T10:00:00Z",
            "available_at": "2026-08-12T04:30:00Z", "source_ids": [sid]}


def bar_row(instrument, session, close, *, volume=1000, source="prices-a", version="v1",
            available=None, open_=None, high=None, low=None, turnover=None):
    c = Decimal(str(close))
    o = Decimal(str(open_)) if open_ is not None else c
    h = Decimal(str(high)) if high is not None else c + Decimal("0.5")
    low = Decimal(str(low)) if low is not None else c - Decimal("0.5")
    t = str(turnover) if turnover is not None else str(c * volume)
    s = session.isoformat() if isinstance(session, date) else str(session)
    return [instrument, s, f"{s}T03:45:00Z", f"{s}T10:00:00Z", available or f"{s}T10:05:00Z",
            str(o), str(h), str(low), str(c), str(volume), t, source, version]


class ProviderCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="oraculum qwen ")
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.dates = weekdays_ending(date(2026, 10, 9), 25)
        self.calendar_dates = self.dates + [date(2026, 10, 12)]

    def default_base(self, assets=None, sources=None):
        return base_payload(
            sources=sources if sources is not None else [price_source()],
            assets=assets if assets is not None else [
                asset_payload("TESTA"), asset_payload("TESTB", sector="consumer"),
            ],
        )

    def write_inputs(self, rows, base=None, calendar_dates=None):
        prices = self.folder / "prices.csv"
        with prices.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(CSV_HEADER)
            writer.writerows(rows)
        sessions = self.folder / "sessions.json"
        sessions.write_text(json.dumps(calendar_payload(calendar_dates or self.calendar_dates)),
                            encoding="utf-8")
        base_path = self.folder / "base.json"
        base_path.write_text(json.dumps(base or self.default_base()), encoding="utf-8")
        return prices, base_path, sessions

    def run_cli(self, *argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_daily_metrics_computed_and_base_preserved(self):
        rows = [bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates[:21])]
        base = self.default_base(
            assets=[asset_payload("TESTA", metrics={"roce": fundamental_metric()}),
                    asset_payload("TESTB", sector="consumer")],
            sources=[price_source(), fundamentals_source()],
        )
        prices, base_path, sessions = self.write_inputs(rows, base=base)
        bundle = build_merged_bundle(prices, base_path, sessions)
        self.assertEqual(bundle.dataset_id, "qw-test-v1")
        self.assertEqual(bundle.mode, "synthetic")
        assets = {a.instrument_id: a for a in bundle.assets}
        self.assertIn("NSE:TESTB", assets)  # not silently dropped
        alpha = assets["NSE:TESTA"]
        self.assertEqual(alpha.session, self.dates[20])
        self.assertAlmostEqual(alpha.metrics["momentum_20d"].value, 120 / 100 - 1)
        self.assertEqual(alpha.metrics["turnover_20d_inr"].value, 110500.0)
        self.assertIsNone(alpha.metrics["trend_50d"].value)
        self.assertEqual(alpha.metrics["roce"].value, 0.26)
        self.assertEqual(alpha.metrics["roce"].source_ids, ("fundamentals-f",))
        self.assertEqual(parse_bundle(bundle.to_dict()), bundle)

    def test_latest_session_observed_equals_session_close(self):
        rows = [bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates)]
        prices, base_path, sessions = self.write_inputs(rows)
        bundle = build_merged_bundle(prices, base_path, sessions)
        alpha = next(a for a in bundle.assets if a.instrument_id == "NSE:TESTA")
        self.assertEqual(alpha.session, bundle.last_session)
        self.assertEqual(alpha.metrics["close_inr"].observed_at, bundle.session_close_at)

    def test_stale_asset_session_remains_stale(self):
        rows = [bar_row("NSE:TESTB", d, 200) for d in self.dates[:4]]
        prices, base_path, sessions = self.write_inputs(rows)
        bundle = build_merged_bundle(prices, base_path, sessions)
        beta = next(a for a in bundle.assets if a.instrument_id == "NSE:TESTB")
        self.assertEqual(beta.session, self.dates[3])
        self.assertLess(beta.session, bundle.last_session)
        self.assertEqual(beta.metrics["close_inr"].value, 200.0)
        self.assertIsNone(beta.metrics["momentum_20d"].value)

    def test_session_gap_breaks_window(self):
        rows = [bar_row("NSE:TESTA", d, 100 + k) for k, d in enumerate(self.dates) if k != 18]
        prices, base_path, sessions = self.write_inputs(rows)
        bundle = build_merged_bundle(prices, base_path, sessions)
        alpha = next(a for a in bundle.assets if a.instrument_id == "NSE:TESTA")
        self.assertEqual(alpha.metrics["close_inr"].value, 124.0)
        self.assertIsNone(alpha.metrics["momentum_20d"].value)   # suffix is only 6 sessions
        self.assertIsNone(alpha.metrics["turnover_20d_inr"].value)

    def test_future_bars_and_late_filings_do_not_change_results(self):
        base_rows = ([bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates)]
                     + [bar_row("NSE:TESTB", d, 200) for d in self.dates[:4]])
        extras = [
            bar_row("NSE:TESTA", date(2026, 10, 12), 500),  # future session, not closed by as_of
            bar_row("NSE:TESTB", self.dates[4], 999, available="2026-10-09T12:30:00Z"),  # late filing
        ]
        first = build_merged_bundle(*self.write_inputs(base_rows))
        second = build_merged_bundle(*self.write_inputs(base_rows + extras))
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_undeclared_instrument_rejected(self):
        prices, base_path, sessions = self.write_inputs([bar_row("NSE:GHOST", self.dates[0], 100)])
        with self.assertRaisesRegex(ValidationError, "row 2.*not declared"):
            build_merged_bundle(prices, base_path, sessions)

    def test_undeclared_source_rejected(self):
        rows = [bar_row("NSE:TESTA", self.dates[0], 100, source="ghost")]
        prices, base_path, sessions = self.write_inputs(rows)
        with self.assertRaisesRegex(ValidationError, "row 2.*source ghost"):
            build_merged_bundle(prices, base_path, sessions)

    def test_invalid_rows_rejected_with_row_numbers(self):
        good = bar_row("NSE:TESTA", self.dates[0], 100)
        bad_rows = {
            "geometry": bar_row("NSE:TESTA", self.dates[0], 100, high="90.00"),
            "negative volume": bar_row("NSE:TESTA", self.dates[0], 100, volume=-5),
            "zero close": bar_row("NSE:TESTA", self.dates[0], 0),
            "non-numeric close": good[:8] + ["abc"] + good[9:],
            "fractional volume": good[:9] + ["1.5"] + good[10:],
            "unknown session": bar_row("NSE:TESTA", date(2026, 10, 10), 100),
        }
        for label, bad in bad_rows.items():
            with self.subTest(label=label):
                prices, base_path, sessions = self.write_inputs([good, bad])
                with self.assertRaisesRegex(ValidationError, "row 3"):
                    build_merged_bundle(prices, base_path, sessions)

    def test_naive_timestamp_in_row_rejected(self):
        row = bar_row("NSE:TESTA", self.dates[0], 100)
        row[4] = f"{self.dates[0].isoformat()}T10:05:00"  # no timezone
        prices, base_path, sessions = self.write_inputs([row])
        with self.assertRaisesRegex(ValidationError, "timezone"):
            build_merged_bundle(prices, base_path, sessions)

    def test_bar_times_must_match_calendar(self):
        row = bar_row("NSE:TESTA", self.dates[0], 100)
        row[3] = f"{self.dates[0].isoformat()}T10:30:00Z"
        prices, base_path, sessions = self.write_inputs([row])
        with self.assertRaisesRegex(ValidationError, "calendar"):
            build_merged_bundle(prices, base_path, sessions)

    def test_duplicate_bar_rejected(self):
        row = bar_row("NSE:TESTA", self.dates[0], 100)
        prices, base_path, sessions = self.write_inputs([row, row])
        with self.assertRaisesRegex(ValidationError, "duplicate bar"):
            build_merged_bundle(prices, base_path, sessions)

    def test_adjustment_version_change_breaks_window_and_raw_coexists(self):
        rows = ([bar_row("NSE:TESTA", d, 100 + k, version="v1")
                 for k, d in enumerate(self.dates[:13])]
                + [bar_row("NSE:TESTA", d, 100 + k, version="v2")
                   for k, d in enumerate(self.dates[13:], start=13)]
                + [bar_row("NSE:TESTA", self.dates[-1], 999, version="raw")])  # raw execution copy
        prices, base_path, sessions = self.write_inputs(rows)
        bundle = build_merged_bundle(prices, base_path, sessions)
        alpha = next(a for a in bundle.assets if a.instrument_id == "NSE:TESTA")
        self.assertEqual(alpha.metrics["close_inr"].value, 124.0)  # unique adjusted vintage wins
        self.assertIsNone(alpha.metrics["momentum_20d"].value)

        rows_adjusted_last = list(reversed(rows))
        prices2, base2, sessions2 = self.write_inputs(rows_adjusted_last)
        bundle2 = build_merged_bundle(prices2, base2, sessions2)
        alpha2 = next(a for a in bundle2.assets if a.instrument_id == "NSE:TESTA")
        self.assertEqual(bundle.to_dict(), bundle2.to_dict())
        self.assertEqual(alpha2.metrics["close_inr"].value, 124.0)
        self.assertIsNone(alpha2.metrics["momentum_20d"].value)  # 12-session v2 suffix < 21

    def test_base_calendar_agreement_enforced(self):
        rows = [bar_row("NSE:TESTA", self.dates[0], 100)]
        wrong_last = self.default_base()
        wrong_last["last_session"] = "2026-10-08"
        wrong_last["session_close_at"] = "2026-10-08T10:00:00Z"
        for asset in wrong_last["assets"]:
            asset["session"] = "2026-10-08"
        prices, base_path, sessions = self.write_inputs(rows, base=wrong_last)
        with self.assertRaisesRegex(ValidationError, "most recent session"):
            build_merged_bundle(prices, base_path, sessions)

        wrong_close = self.default_base()
        wrong_close["session_close_at"] = "2026-10-09T10:30:00Z"
        prices, base_path, sessions = self.write_inputs(rows, base=wrong_close)
        with self.assertRaises(ValidationError):
            build_merged_bundle(prices, base_path, sessions)

    def test_sessions_file_validation(self):
        rows = [bar_row("NSE:TESTA", self.dates[0], 100)]
        d0, d1 = self.dates[0], self.dates[1]

        def write_sessions(payload):
            sessions = self.folder / "sessions.json"
            sessions.write_text(json.dumps(payload), encoding="utf-8")
            return sessions

        base = self.default_base()
        prices = self.folder / "prices.csv"
        with prices.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(CSV_HEADER)
            writer.writerows(rows)
        base_path = self.folder / "base.json"
        base_path.write_text(json.dumps(base), encoding="utf-8")

        entry = lambda d: {"session": d.isoformat(), "open_at": f"{d.isoformat()}T03:45:00Z",
                           "close_at": f"{d.isoformat()}T10:00:00Z"}
        cases = {
            "unordered": {"sessions": [entry(d1), entry(d0)]},
            "duplicate": {"sessions": [entry(d0), entry(d0)]},
            "open not before close": {"sessions": [
                {"session": d0.isoformat(), "open_at": f"{d0.isoformat()}T10:00:00Z",
                 "close_at": f"{d0.isoformat()}T10:00:00Z"}]},
            "india date mismatch": {"sessions": [
                {"session": d0.isoformat(), "open_at": f"{d0.isoformat()}T03:45:00Z",
                 "close_at": f"{d0.isoformat()}T18:30:00Z"}]},
            "unknown field": {"sessions": [dict(entry(d0), extra=1)]},
            "naive timestamp": {"sessions": [
                {"session": d0.isoformat(), "open_at": f"{d0.isoformat()}T03:45:00",
                 "close_at": f"{d0.isoformat()}T10:00:00Z"}]},
            "empty": {"sessions": []},
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                sessions = write_sessions(payload)
                with self.assertRaises(ValidationError):
                    build_merged_bundle(prices, base_path, sessions)

    def test_source_availability_propagates_to_metrics(self):
        rows = [bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates)]
        base = self.default_base(sources=[price_source(available="2026-10-09T11:00:00Z")])
        prices, base_path, sessions = self.write_inputs(rows, base=base)
        bundle = build_merged_bundle(prices, base_path, sessions)
        alpha = next(a for a in bundle.assets if a.instrument_id == "NSE:TESTA")
        expected = datetime(2026, 10, 9, 11, 0, tzinfo=UTC)
        self.assertEqual(alpha.metrics["momentum_20d"].available_at, expected)
        self.assertEqual(alpha.metrics["close_inr"].available_at, expected)

    def test_reversed_rows_give_same_bundle(self):
        rows = ([bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates)]
                + [bar_row("NSE:TESTB", d, 200) for d in self.dates[:4]])
        first = build_merged_bundle(*self.write_inputs(rows))
        second = build_merged_bundle(*self.write_inputs(list(reversed(rows))))
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_base_daily_metrics_are_replaced_not_mixed(self):
        rows = [bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates)]
        base = self.default_base(assets=[asset_payload("TESTA", metrics={
            "close_inr": {"value": 1.0, "observed_at": "2026-10-09T10:00:00Z",
                          "available_at": "2026-10-09T10:05:00Z", "source_ids": ["prices-a"]},
        }), asset_payload("TESTB", sector="consumer")])
        prices, base_path, sessions = self.write_inputs(rows, base=base)
        bundle = build_merged_bundle(prices, base_path, sessions)
        alpha = next(a for a in bundle.assets if a.instrument_id == "NSE:TESTA")
        self.assertEqual(alpha.metrics["close_inr"].value, 124.0)

    def test_cli_writes_validated_output_and_protects_files(self):
        rows = [bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates)]
        prices, base_path, sessions = self.write_inputs(rows)
        before = prices.read_bytes()
        output = self.folder / "bundle.json"
        code, out, err = self.run_cli(
            "--prices", str(prices), "--base-bundle", str(base_path),
            "--sessions", str(sessions), "--output", str(output))
        self.assertEqual(code, 0, err)
        self.assertEqual(prices.read_bytes(), before)  # input never overwritten
        parse_bundle(load_json(output))

        code, _, err = self.run_cli("--prices", str(prices), "--base-bundle", str(base_path),
                                    "--sessions", str(sessions), "--output", str(output))
        self.assertEqual(code, 2)
        self.assertIn("--force", err)
        code, _, err = self.run_cli("--prices", str(prices), "--base-bundle", str(base_path),
                                    "--sessions", str(sessions), "--output", str(output), "--force")
        self.assertEqual(code, 0, err)

        code, _, err = self.run_cli("--prices", str(prices), "--base-bundle", str(base_path),
                                    "--sessions", str(sessions), "--output", str(prices))
        self.assertEqual(code, 2)

        nested = self.folder / "sub" / "bundle.json"
        code, _, err = self.run_cli("--prices", str(prices), "--base-bundle", str(base_path),
                                    "--sessions", str(sessions), "--output", str(nested))
        self.assertEqual(code, 0, err)
        self.assertTrue(nested.exists())

    def test_provider_checks_requested_cutoff_and_session(self):
        rows = [bar_row("NSE:TESTA", d, 100 + i) for i, d in enumerate(self.dates)]
        prices, base_path, sessions = self.write_inputs(rows)
        provider = CsvResearchProvider(prices, base_path, sessions)
        bundle = provider.load_bundle(as_of=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
                                      last_session=date(2026, 10, 9))
        self.assertEqual(bundle.dataset_id, "qw-test-v1")
        with self.assertRaisesRegex(ValidationError, "as_of"):
            provider.load_bundle(as_of=datetime(2026, 10, 9, 13, 0, tzinfo=UTC),
                                 last_session=date(2026, 10, 9))
        with self.assertRaisesRegex(ValidationError, "last_session"):
            provider.load_bundle(as_of=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
                                 last_session=date(2026, 10, 8))


@unittest.skipUnless((EXAMPLES / "prices.csv").exists(), "examples/qwen fixtures not present")
class FixtureBundleTests(unittest.TestCase):
    def test_fixture_merges_validates_and_ranks(self):
        bundle = build_merged_bundle(EXAMPLES / "prices.csv", EXAMPLES / "base.json",
                                     EXAMPLES / "sessions.json")
        self.assertEqual(bundle.dataset_id, "oraculum-qwen-fixture-v1")
        assets = {a.instrument_id: a for a in bundle.assets}

        alpha = assets["NSE:QW-ALPHA"]
        self.assertEqual(alpha.session, date(2026, 10, 9))
        self.assertEqual(alpha.metrics["close_inr"].value, 127.0)
        self.assertAlmostEqual(alpha.metrics["momentum_20d"].value, 127.0 / 117.0 - 1.0)
        self.assertAlmostEqual(alpha.metrics["trend_50d"].value, 127.0 / 114.75 - 1.0)
        self.assertAlmostEqual(alpha.metrics["volume_ratio_20d"].value, 1.8)
        self.assertEqual(alpha.metrics["turnover_20d_inr"].value, 12_733_000.0)
        self.assertLess(alpha.metrics["volatility_20d_annualized"].value, 0.01)

        beta = assets["NSE:QW-BETA"]
        self.assertEqual(beta.session, date(2026, 10, 8))
        self.assertEqual(beta.metrics["close_inr"].value, 200.0)
        self.assertIsNone(beta.metrics["momentum_20d"].value)
        self.assertEqual(beta.metrics["debt_to_equity"].value, 0.5)

        gamma = assets["NSE:QW-GAMMA"]
        self.assertEqual(gamma.session, date(2026, 10, 9))
        self.assertEqual(gamma.metrics["close_inr"].value, 300.0)
        self.assertIsNone(gamma.metrics["turnover_20d_inr"].value)

        report = build_run(bundle)
        self.assertEqual(report["counts"], {"candidate": 1, "watch": 0, "excluded": 2})
        by_id = {d["instrument_id"]: d for d in report["decisions"]}
        self.assertEqual(by_id["NSE:QW-ALPHA"]["status"], "candidate")
        self.assertAlmostEqual(by_id["NSE:QW-ALPHA"]["score"], 72.9103, places=2)
        self.assertEqual(by_id["NSE:QW-BETA"]["status"], "excluded")
        self.assertEqual(by_id["NSE:QW-GAMMA"]["status"], "excluded")


if __name__ == "__main__":
    unittest.main()
