"""Local operating workflow regressions; no external network or model required."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from oraculum.contracts import IST, UTC, ValidationError, iso
from oraculum.demo import make_demo_bundle
from oraculum.interfaces import PriceBar
from oraculum.local import main, persisted_demo
from oraculum.local_ai import analyze_document, validate_draft
from oraculum.local_data import MarketStore, parse_bhavcopy, scan_local
from oraculum.local_web import make_server, report_html
from oraculum.paper.ledger import PaperLedger
from oraculum.pipeline import build_run
from oraculum.repository import RunRepository


def bhavcopy(session, *, price=100, symbol="ABC", turnover=None):
    return ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TtlTrfVal,SsnId\n"
            f"{session},{session},CM,NSE,STK,{symbol},EQ,{price},{price + 2},{price - 2},{price},1000000,"
            f"{turnover if turnover is not None else price * 1000000},F1\n").encode()


def entry(session):
    return {"open_at": datetime.combine(session, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15),
            "close_at": datetime.combine(session, datetime.min.time(), tzinfo=IST).replace(hour=15, minute=30)}


class MarketWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = MarketStore(self.path / "market.sqlite3")
        self.session = date(2026, 10, 13)
        self.received = datetime(2026, 10, 13, 18, tzinfo=IST)

    def test_zip_csv_equivalence_and_bad_archive(self):
        raw = bhavcopy(self.session)
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as archive:
            archive.writestr("../../ignored-name.csv", raw)
        self.assertEqual(parse_bhavcopy(raw, self.session), parse_bhavcopy(zipped.getvalue(), self.session))
        self.assertFalse((self.path / "ignored-name.csv").exists())
        with zipfile.ZipFile(zipped, "a") as archive:
            archive.writestr("extra.csv", raw)
        with self.assertRaises(ValidationError):
            parse_bhavcopy(zipped.getvalue(), self.session)

    def test_wrong_day_units_and_geometry_rejected(self):
        for raw in (bhavcopy(date(2026, 10, 12)), bhavcopy(self.session, turnover=1000),
                    bhavcopy(self.session).replace(b",100,102,98,100,", b",110,102,98,100,")):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                parse_bhavcopy(raw, self.session)

    def test_duplicate_and_unsupported_symbols(self):
        raw = bhavcopy(self.session)
        with self.assertRaisesRegex(ValidationError, "Duplicate"):
            parse_bhavcopy(raw + raw.splitlines(keepends=True)[1], self.session)
        extra = bhavcopy(self.session, symbol="M&M").splitlines(keepends=True)[1]
        result = parse_bhavcopy(raw + extra, self.session)
        self.assertEqual(result["skipped"], {"unsupported_symbol": 1})
        self.assertEqual(len(result["rows"]), 1)

    def test_receipt_is_idempotent_and_revision_rejected(self):
        raw = bhavcopy(self.session)
        a = self.store.ingest(raw, self.session, "https://example.test/data", received_at=self.received)
        b = self.store.ingest(raw, self.session, "file:///copy.csv", received_at=self.received + timedelta(days=1))
        self.assertEqual(a, b)
        with self.assertRaisesRegex(ValidationError, "different snapshot"):
            self.store.ingest(bhavcopy(self.session, price=101), self.session, "file:///revision.csv", received_at=self.received)
        self.assertEqual(len(self.store.snapshots()), 1)

    def _inputs(self, sessions):
        cal = {"coverage_start": str(sessions[0]), "coverage_end": str(sessions[-1]),
               "source_uri": "file:///test-explicit-calendar.json", "sessions": [
                   {"session": str(s), **{k: iso(v) for k, v in entry(s).items()}} for s in sessions]}
        (self.path / "calendar.json").write_text(json.dumps(cal))
        (self.path / "watchlist.json").write_text(json.dumps({"dataset_id": "test-import", "assets": [
            {"symbol": "ABC", "sector": "industrials"}]}))

    def _scan(self, cutoff):
        return scan_local(self.store, self.path / "watchlist.json", self.path / "calendar.json", as_of=cutoff)

    def test_scan_rejects_unreceived_and_does_not_impute_fundamentals(self):
        self._inputs([self.session])
        self.store.ingest(bhavcopy(self.session), self.session, "file:///prices.csv", received_at=self.received)
        with self.assertRaisesRegex(ValidationError, "Missing received"):
            self._scan(self.received - timedelta(minutes=1))
        report = self._scan(self.received)
        self.assertTrue(report["abstained"])
        self.assertEqual(report["counts"]["excluded"], 1)
        self.assertNotIn("debt_to_equity", report["input"]["assets"][0]["metrics"])
        self.assertEqual(report["input"]["sources"][0]["available_at"], iso(self.received))
        with self.assertRaisesRegex(ValidationError, "coverage"):
            self._scan(self.received + timedelta(days=1))

    def test_calendar_gap_breaks_features(self):
        # These dates are an explicit test calendar, not a claim about the NSE calendar.
        sessions = [date(2026, 7, 1) + timedelta(days=i) for i in range(55)]
        self._inputs(sessions)
        cutoff = entry(sessions[-1])["close_at"] + timedelta(hours=2)
        for index, session in enumerate(sessions):
            if index == 48:
                continue
            self.store.ingest(bhavcopy(session, price=100 + index), session, "file:///test.csv", received_at=cutoff)
        report = self._scan(cutoff)
        metrics = report["input"]["assets"][0]["metrics"]
        self.assertIsNone(metrics["momentum_20d"]["value"])
        self.assertIsNone(metrics["trend_50d"]["value"])
        self.assertEqual(metrics["close_inr"]["value"], 154)

    def test_snapshot_received_before_close_fails_scan(self):
        self._inputs([self.session])
        self.store.ingest(bhavcopy(self.session), self.session, "file:///x.csv",
                          received_at=entry(self.session)["open_at"])
        with self.assertRaisesRegex(ValidationError, "before.*close"):
            self._scan(self.received)

    def test_sql_updates_blocked_and_integrity_verified(self):
        self.store.ingest(bhavcopy(self.session), self.session, "file:///x.csv", received_at=self.received)
        with closing(sqlite3.connect(self.store.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE market_snapshots SET payload='{}'")
            conn.execute("DROP TRIGGER market_no_update")
            conn.execute("UPDATE market_snapshots SET payload='{}'")
        with self.assertRaisesRegex(ValidationError, "integrity"):
            self.store.snapshots()


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.report = build_run(make_demo_bundle(), generated_at=datetime(2026, 10, 9, 13, tzinfo=UTC))
        self.repo = RunRepository(self.folder / "runs.sqlite3")
        self.repo.save(self.report)
        self.created = datetime(2026, 10, 9, 14, tzinfo=UTC)
        self.ledger = PaperLedger(self.folder / "paper.sqlite3")
        self.ledger.initialize(Decimal("10000.00"), "synthetic", now=self.created)
        self.session = date(2026, 10, 12)
        self.calendar = {s: entry(s) for s in (date(2026, 10, 9), self.session, date(2026, 10, 13))}
        self.bar = PriceBar("NSE:SIM-ASTER", self.session, **entry(self.session),
            available_at=entry(self.session)["close_at"] + timedelta(hours=1),
            open=Decimal("100"), high=Decimal("102"), low=Decimal("98"), close=Decimal("101"),
            volume=1000000, turnover_inr=Decimal("100000000"), source_id="test", adjustment_version="raw")

    def order(self, **kwargs):
        defaults = dict(order_id="one", instrument_id="NSE:SIM-ASTER", side="buy", quantity=3,
                        run_id=self.report["run_id"], now=self.created + timedelta(minutes=1))
        defaults.update(kwargs)
        return self.ledger.submit(self.repo, **defaults)

    def settle(self, **kwargs):
        defaults = dict(session=self.session, bars=[self.bar], calendar=self.calendar, now=self.bar.available_at)
        defaults.update(kwargs)
        return self.ledger.settle(**defaults)

    def test_persistent_fill_and_idempotent_restart(self):
        order = self.order()
        self.assertEqual(order, self.order(now=self.created + timedelta(minutes=2)))
        result = self.settle()
        restarted = PaperLedger(self.ledger.path)
        self.assertEqual(restarted.status()["state"]["cash_inr"], "9699.40")
        self.assertEqual(len(restarted.status()["pending"]), 0)
        self.assertEqual(result, self.settle())
        self.assertEqual(restarted.status()["event_count"], 3)
        extended = self.calendar | {date(2026, 10, 14): entry(date(2026, 10, 14))}
        self.assertEqual(result, self.settle(calendar=extended))

    def test_order_collision_and_signal_time(self):
        self.order()
        with self.assertRaisesRegex(ValidationError, "different details"):
            self.order(quantity=4)
        with self.assertRaisesRegex(ValidationError, "precede"):
            self.order(order_id="early", now=self.created - timedelta(days=1))
        with self.assertRaisesRegex(ValidationError, "shortlist"):
            self.order(order_id="not-candidate", instrument_id="NSE:SIM-CEDAR")

    def test_missing_bar_is_terminal_and_no_cash_changes(self):
        self.order()
        result = self.settle(bars=[])
        self.assertEqual(result["result"]["rejections"][0]["reason"], "no_bar")
        self.assertEqual(self.ledger.status()["state"]["cash_inr"], "10000.00")
        self.assertFalse(self.ledger.status()["pending"])

    def test_future_and_adjusted_bars_rollback(self):
        self.order()
        before = self.ledger.status()
        for bar in (replace(self.bar, adjustment_version="adjusted"),
                    replace(self.bar, available_at=self.bar.available_at + timedelta(days=1))):
            with self.subTest(bar=bar), self.assertRaises(ValidationError):
                self.settle(bars=[bar])
        self.assertEqual(before, self.ledger.status())

    def test_no_choosing_later_execution_session(self):
        self.order()
        later = date(2026, 10, 13)
        later_bar = replace(self.bar, session=later, **entry(later),
                            available_at=entry(later)["close_at"] + timedelta(hours=1))
        with self.assertRaisesRegex(ValidationError, "requires settlement"):
            self.settle(session=later, bars=[later_bar], now=later_bar.available_at)
        self.assertEqual(self.ledger.status()["event_count"], 2)

    def test_same_open_order_waits_for_next_session(self):
        self.order(now=self.bar.open_at)
        result = self.settle()
        self.assertEqual(result["result"]["fills"], [])
        self.assertEqual(len(self.ledger.status()["pending"]), 1)

    def test_concurrent_settlement_exactly_once(self):
        self.order()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.settle(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.ledger.status()["event_count"], 3)

    def test_changed_session_input_rejected(self):
        self.order()
        self.settle()
        with self.assertRaisesRegex(ValidationError, "different inputs"):
            self.settle(fee_bps=Decimal("20"))

    def test_mode_separation_and_integrity(self):
        imported = PaperLedger(self.folder / "imported.sqlite3")
        imported.initialize(Decimal("1000"), "imported", now=self.created)
        with self.assertRaisesRegex(ValidationError, "separate paper ledgers"):
            imported.submit(self.repo, order_id="x", instrument_id="NSE:SIM-ASTER", side="buy", quantity=1,
                            run_id=self.report["run_id"], now=self.created)
        with closing(sqlite3.connect(self.ledger.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM paper_events")
            conn.execute("DROP TRIGGER paper_no_update")
            conn.execute("UPDATE paper_events SET event_sha='bad' WHERE seq=1")
        with self.assertRaisesRegex(ValidationError, "integrity"):
            self.ledger.status()


class ViewerAndAITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_persistent_demo_replay(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            first = persisted_demo(self.folder)
            second = persisted_demo(self.folder)
        self.assertEqual(first, second)
        self.assertEqual(first["result"]["state"]["cash_inr"], "9609.22")

    def test_viewer_routes_hosts_and_no_files(self):
        report = build_run(make_demo_bundle())
        RunRepository(self.folder / "runs.sqlite3").save(report)
        server = make_server(self.folder / "runs.sqlite3", self.folder / "missing.sqlite3", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, status in (("/", 200), ("/api/runs", 200), ("/api/run/" + report["run_id"], 200),
                                 ("/run/" + report["run_id"], 200), ("/../../README.md", 404)):
                with self.subTest(path=path):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request("GET", path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, status)
                    response.read()
                    connection.close()
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/", headers={"Host": "untrusted.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()
            self.assertFalse((self.folder / "missing.sqlite3").exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_html_escapes_source_and_reasons(self):
        report = build_run(make_demo_bundle())
        report["input"]["sources"][0]["title"] = "<script>alert(1)</script>"
        rendered = report_html(report)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("FICTIONAL DEMONSTRATION", rendered)

    def draft(self):
        return {"summary": "Revenue increased.", "sentiment": 0.2, "abstain": False,
                "evidence": [{"quote": "Revenue grew 5%.", "interpretation": "Positive reported growth."}],
                "uncertainties": ["One document is not a complete assessment."]}

    def test_ai_invented_quotes_and_bad_sentiment_rejected(self):
        doc = "Revenue grew 5%. Costs also increased."
        self.assertEqual(validate_draft(self.draft(), doc)["sentiment"], 0.2)
        for change in (dict(sentiment=True), dict(sentiment=2), dict(evidence=[]), dict(abstain=True),
                       dict(evidence=[{"quote": "Revenue doubled.", "interpretation": "Growth"}])):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_draft(self.draft() | change, doc)

    def test_ai_cloud_blocked_before_generation(self):
        with patch("oraculum.local_ai._post", return_value={"remote_host": "https://cloud.example"}) as post:
            with self.assertRaisesRegex(ValidationError, "cloud/remote"):
                analyze_document("Revenue grew 5%.", model="aliased-model", instrument_id="NSE:ABC",
                                 source_uri="https://example.test/filing", kind="announcement")
            self.assertEqual(post.call_count, 1)
        with patch("oraculum.local_ai._post") as post:
            with self.assertRaises(ValidationError):
                analyze_document("x", model="any-cloud", instrument_id="NSE:ABC",
                                 source_uri="https://example.test", kind="news")
            post.assert_not_called()

    def test_ai_success_is_advisory_and_hashes_document(self):
        answers = [{"model_info": {"general.architecture": "test"}},
                   {"done": True, "response": json.dumps(self.draft())}]
        with patch("oraculum.local_ai._post", side_effect=answers):
            result = analyze_document("Revenue grew 5%.", model="test:local", instrument_id="NSE:ABC",
                                      source_uri="https://example.test", kind="news")
        self.assertFalse(result["affects_ranking"])
        self.assertEqual(result["status"], "unreviewed_draft")
        self.assertEqual(len(result["source_sha256"]), 64)

    def test_cli_init_preserves_existing_and_errors_are_friendly(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main(["init", "--data-dir", str(self.folder)]), 0)
            path = self.folder / "watchlist.json"
            path.write_text("user edits")
            self.assertEqual(main(["init", "--data-dir", str(self.folder)]), 0)
            self.assertEqual(path.read_text(), "user edits")
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(main(["scan", "--data-dir", str(self.folder)]), 2)
        self.assertIn("Oraculum local error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
