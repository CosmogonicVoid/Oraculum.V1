"""Automatic workflow regressions. Fixtures are synthetic; no network required."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from oraculum.contracts import IST, UTC, ValidationError, iso
from oraculum.local import main
from oraculum.local_data import MarketStore, parse_bhavcopy
from oraculum.local_web import make_server
from oraculum.market_calendar import research_calendar, closed_window
from oraculum.market_research import (
    build_research, read_research, report_csv, research_status, run_research,
    save_research, technical_score, workflow_lock, write_json,
)
from oraculum.research_view import freshness_notice, research_html
from oraculum.serialization import digest

CUTOFF = datetime(2026, 10, 14, 20, tzinfo=UTC)


def make_tape():
    calendar, raw, info = research_calendar(CUTOFF)
    sessions = closed_window(calendar, CUTOFF)
    files, snapshots = {}, []
    for i, session in enumerate(sessions):
        lines = ["TradDt,BizDt,Sgmt,Src,FinInstrmTp,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TtlTrfVal,SsnId"]
        values = {"UP": 100+i, "DOWN": 200-i, "FLAT": 100, "LOW": 100,
                  "JUMP": 120 if i == 59 else 100, "GAPPED": 100+i}
        if i == 55:
            del values["GAPPED"]
        if i >= 40:
            values["NEW"] = 100+i
        for symbol, price in values.items():
            volume = 1000 if symbol == "LOW" else 3_000_000 if symbol == "UP" and i == 59 else 1_000_000
            lines.append(f"{session},{session},CM,NSE,STK,{symbol},EQ,{price},{price+1},{price-1},{price},{volume},{price*volume},F1")
        content = ("\n".join(lines)+"\n").encode()
        files[session] = content
        snapshots.append({"session": str(session), "received_at": iso(CUTOFF), "uri": "https://example.test/fixture.csv",
                          "sha256": "0"*64, "source_id": "fixture-"+str(session), **parse_bhavcopy(content, session)})
    return calendar, raw, info, sessions, files, snapshots


class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar, cls.raw, cls.info, cls.sessions, cls.files, cls.snaps = make_tape()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def report(self, snapshots=None):
        return build_research(self.snaps if snapshots is None else snapshots,
                              self.calendar, self.raw, self.info, as_of=CUTOFF)

    def run_fixture(self, **kwargs):
        return run_research(self.folder, downloader=lambda session: (self.files[session], "https://example.test/fixture.csv"),
                            clock=lambda: CUTOFF, pause=lambda delay: None, progress=lambda message: None, **kwargs)

    def test_calendar_excludes_exchange_holidays_and_weekends(self):
        self.assertNotIn(date(2026, 9, 14), self.calendar)
        self.assertNotIn(date(2026, 10, 2), self.calendar)
        self.assertNotIn(date(2026, 10, 20), self.calendar)
        self.assertNotIn(date(2026, 10, 10), self.calendar)
        self.assertEqual(self.sessions[0], date(2026, 7, 21))
        self.assertEqual(self.sessions[-1], date(2026, 10, 14))

    def test_before_close_uses_previous_session_and_holiday_uses_friday(self):
        before = datetime(2026, 10, 14, 15, 29, tzinfo=IST)
        self.assertEqual(closed_window(self.calendar, before)[-1], date(2026, 10, 13))
        holiday = datetime(2026, 9, 14, 18, tzinfo=IST)
        self.assertEqual(closed_window(self.calendar, holiday, 50)[-1], date(2026, 9, 11))

    def test_eod_cutoff_includes_closing_auction_and_post_close(self):
        for hour, minute in ((15, 31), (15, 35), (15, 59)):
            cutoff = datetime(2026, 10, 14, hour, minute, tzinfo=IST)
            self.assertEqual(closed_window(self.calendar, cutoff)[-1], date(2026, 10, 13))
        cutoff = datetime(2026, 10, 14, 16, 0, tzinfo=IST)
        self.assertEqual(closed_window(self.calendar, cutoff)[-1], date(2026, 10, 14))

    def test_calendar_expires_before_unknown_special_hours(self):
        for cutoff in (datetime(2026, 11, 8, tzinfo=IST), datetime(2027, 1, 1, tzinfo=IST)):
            with self.subTest(cutoff=cutoff), self.assertRaisesRegex(ValidationError, "calendar"):
                research_calendar(cutoff)
        with self.assertRaisesRegex(ValidationError, "60 completed"):
            closed_window(self.calendar, datetime(2026, 7, 3, 18, tzinfo=IST))

    def test_real_metrics_rank_only_qualified_and_no_fake_fundamentals(self):
        report = self.report()
        assets = {a["symbol"]: a for a in report["assets"]}
        self.assertEqual(report["counts"]["scanned"], 7)
        self.assertEqual(report["counts"]["eligible"], 3)
        self.assertEqual(report["highlights"], ["NSE:UP"])
        self.assertEqual(assets["UP"]["rank"], 1)
        self.assertAlmostEqual(assets["UP"]["metrics"]["momentum_20d"], 159/139-1)
        self.assertAlmostEqual(assets["UP"]["metrics"]["trend_50d"], 159/134.5-1)
        self.assertEqual(assets["UP"]["metrics"]["volume_ratio_20d"], 3)
        self.assertEqual(assets["FLAT"]["score"], 50)
        self.assertLess(assets["DOWN"]["score"], 50)
        self.assertEqual(report["coverage"]["fundamentals"], "not_assessed")
        self.assertNotIn("debt_to_equity", assets["UP"]["metrics"])
        self.assertNotIn("shortlist", report)

    def test_liquidity_gap_and_exact_twenty_percent_move_excluded(self):
        assets = {a["symbol"]: a for a in self.report()["assets"]}
        self.assertEqual(assets["NEW"]["consecutive_sessions"], 20)
        self.assertEqual(assets["GAPPED"]["consecutive_sessions"], 4)
        for symbol in ("NEW", "GAPPED", "LOW", "JUMP"):
            self.assertIsNone(assets[symbol]["rank"])
            self.assertIsNone(assets[symbol]["score"])
            self.assertTrue(assets[symbol]["blockers"])
        self.assertIn("20% or larger", assets["JUMP"]["blockers"][0])

    def test_missing_entire_session_prevents_any_ranking(self):
        with self.assertRaisesRegex(ValidationError, "Missing scheduled"):
            self.report(self.snaps[:30] + self.snaps[31:])

    def test_future_receipt_and_duplicate_session_rejected(self):
        future = deepcopy(self.snaps)
        future[0]["received_at"] = iso(CUTOFF + timedelta(seconds=1))
        with self.assertRaisesRegex(ValidationError, "not been received"):
            self.report(future)
        with self.assertRaisesRegex(ValidationError, "Duplicate"):
            self.report(self.snaps + [self.snaps[-1]])

    def test_old_window_cannot_be_passed_as_current(self):
        with self.assertRaisesRegex(ValidationError, "latest completed"):
            build_research(self.snaps[:-1], self.calendar, self.raw, self.info,
                           as_of=CUTOFF, window=self.sessions[:-1])

    def test_algorithm_volume_confirms_negative_direction_and_score_is_bounded(self):
        metrics = {"momentum_20d": -.2, "trend_50d": -.15, "volume_ratio_20d": 3,
                   "volatility_20d_annualized": .8}
        score, components = technical_score(metrics)
        self.assertEqual(score, 0)
        self.assertEqual(components["volume_confirmation"], -10)
        metrics.update(momentum_20d=.2, trend_50d=.15, volatility_20d_annualized=.2)
        self.assertEqual(technical_score(metrics)[0], 100)

    def test_no_positive_setups_is_valid_abstention(self):
        snaps = deepcopy(self.snaps)
        for snapshot in snaps:
            snapshot["rows"] = [r for r in snapshot["rows"] if r["symbol"] in ("FLAT", "DOWN")]
        report = self.report(snaps)
        self.assertEqual(report["highlights"], [])
        self.assertEqual(report["counts"]["eligible"], 2)

    def test_cache_resume_and_no_second_network_request(self):
        first = self.run_fixture()
        report = run_research(self.folder, offline=True, clock=lambda: CUTOFF,
                              downloader=lambda session: self.fail("Unexpected network"), progress=lambda message: None)
        self.assertEqual(first["report_id"], report["report_id"])
        self.assertEqual(research_status(self.folder)["downloaded_sessions"], 0)
        self.assertEqual(read_research(self.folder)["report_id"], report["report_id"])
        self.assertFalse((self.folder/"paper.sqlite3").exists())
        self.assertFalse((self.folder/"runs.sqlite3").exists())

    def test_failure_keeps_cache_reports_failure_then_resumes(self):
        requested = []
        def interrupted(session):
            requested.append(session)
            if len(requested) == 3:
                raise ValidationError("Simulated unavailable exchange file")
            return self.files[session], "https://example.test/fixture.csv"
        with self.assertRaisesRegex(ValidationError, "Simulated"):
            run_research(self.folder, downloader=interrupted, clock=lambda: CUTOFF,
                         pause=lambda delay: None, progress=lambda message: None)
        self.assertEqual(len(MarketStore(self.folder/"market.sqlite3").snapshots()), 2)
        self.assertIsNone(read_research(self.folder))
        self.assertEqual(research_status(self.folder)["state"], "failed")
        self.run_fixture()
        self.assertEqual(research_status(self.folder)["downloaded_sessions"], 58)

    def test_failed_refresh_preserves_last_report_and_displays_staleness(self):
        first = self.run_fixture()
        next_day = CUTOFF + timedelta(days=1)
        with self.assertRaisesRegex(ValidationError, "Offline cache is missing"):
            run_research(self.folder, offline=True, clock=lambda: next_day, progress=lambda message: None)
        self.assertEqual(read_research(self.folder)["report_id"], first["report_id"])
        message = freshness_notice(first, research_status(self.folder), now=next_day)
        self.assertIn("OLDER REPORT", message)
        self.assertIn("LATEST UPDATE FAILED", message)

    def test_transient_timeout_recovers_in_same_command(self):
        calls = []
        def download(session):
            calls.append(session)
            if len(calls) == 1:
                try:
                    raise URLError(TimeoutError("fixture timeout"))
                except URLError as cause:
                    raise ValidationError("Network unavailable") from cause
            return self.files[session], "https://example.test/fixture.csv"
        report = run_research(self.folder, downloader=download, clock=lambda: CUTOFF,
                              pause=lambda delay: None, progress=lambda message: None)
        self.assertEqual(len(calls), 61)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(report["counts"]["scanned"], 7)

    def test_http_access_denial_is_not_retried(self):
        calls = []
        def denied(session):
            calls.append(session)
            raise HTTPError("https://example.test/fixture.csv", 403, "Denied", {}, None)
        with self.assertRaisesRegex(ValidationError, "403"):
            run_research(self.folder, downloader=denied, clock=lambda: CUTOFF,
                         pause=lambda delay: None, progress=lambda message: None)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(read_research(self.folder))

    def test_locked_progress_file_does_not_abort_complete_research(self):
        from oraculum.market_research import write_json as actual_write
        def write(path, value):
            if Path(path).name == "status.json":
                raise PermissionError("fixture locked progress")
            return actual_write(path, value)
        with patch("oraculum.market_research.write_json", side_effect=write):
            report = self.run_fixture()
        self.assertEqual(read_research(self.folder)["report_id"], report["report_id"])

    def test_locked_progress_does_not_hide_actual_download_error(self):
        def download(session):
            raise ValidationError("Actual source failure")
        with patch("oraculum.market_research.write_json", side_effect=PermissionError("progress locked")):
            with self.assertRaisesRegex(ValidationError, "Actual source failure"):
                run_research(self.folder, downloader=download, clock=lambda: CUTOFF, progress=lambda message: None)

    def test_locked_report_pointer_keeps_previous_publication(self):
        from oraculum.market_research import atomic_text as actual_write
        first = self.run_fixture()
        def write(path, text):
            if Path(path).name == "latest.json":
                raise PermissionError("fixture locked publication")
            return actual_write(path, text)
        with patch("oraculum.market_research.atomic_text", side_effect=write):
            with self.assertRaisesRegex(PermissionError, "locked publication"):
                run_research(self.folder, offline=True, clock=lambda: CUTOFF+timedelta(seconds=1), progress=lambda message: None)
        self.assertEqual(read_research(self.folder)["report_id"], first["report_id"])

    def test_lock_excludes_overlapping_runs_and_releases(self):
        with workflow_lock(self.folder):
            with self.assertRaisesRegex(ValidationError, "Another research"):
                with workflow_lock(self.folder):
                    self.fail("Lock was bypassed")
        with workflow_lock(self.folder):
            pass

    def test_corrupt_saved_report_is_detected_and_path_traversal_rejected(self):
        report = self.report()
        path = save_research(self.folder, report)
        changed = deepcopy(report)
        changed["assets"][0]["score"] = 99
        write_json(path, changed)
        with self.assertRaisesRegex(ValidationError, "integrity"):
            read_research(self.folder)
        with self.assertRaisesRegex(ValidationError, "Invalid research report"):
            read_research(self.folder, "../../secret")

    def test_csv_reports_all_stocks_and_html_escapes_untrusted_text(self):
        report = self.report()
        self.assertEqual(len(report_csv(report).splitlines()), 8)
        report["assets"][0]["reasons"] = ["<script>alert(1)</script>"]
        # Reasons moved from the landing page into the stock evidence view.
        from oraculum.dashboard_view import stock_html
        page = stock_html(report, report["assets"][0], now=CUTOFF)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Financial evidence", page)

    def test_cli_uses_automatic_workflow_without_init(self):
        with patch("oraculum.market_research.run_research") as run:
            self.assertEqual(main(["research", "--data-dir", str(self.folder), "--offline"]), 0)
        self.assertTrue(run.call_args.kwargs["offline"])
        self.assertFalse((self.folder/"watchlist.json").exists())

    def test_viewer_home_csv_json_and_read_only_routes(self):
        report = self.report()
        save_research(self.folder, report)
        server = make_server(self.folder/"runs.sqlite3", self.folder/"paper.sqlite3", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, mime, expected in (("/", "text/html", "Market overview".encode()),
                    ("/api/research/latest", "application/json", report["report_id"].encode()),
                    (f"/research/{report['report_id']}.csv", "text/csv", b"NSE:UP"),
                    ("/history", "text/html", b"Research history")):
                conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    conn.request("GET", path)
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIn(mime, response.getheader("Content-Type"))
                    self.assertIn(expected, response.read())
                finally:
                    conn.close()
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                conn.request("POST", "/api/research/latest")
                self.assertEqual(conn.getresponse().status, 501)
            finally:
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
