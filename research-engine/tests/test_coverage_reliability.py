"""Operational failures, provenance gaps and read-only coverage contracts."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from http.client import HTTPConnection
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from oraculum.activity import activity_message, heartbeat, observed_status
from oraculum.ai_evaluation import evaluate, fixtures
from oraculum.contracts import ValidationError, iso
from oraculum.coverage import csv_export, freshness, select, snapshot
from oraculum.coverage_view import coverage_html
from oraculum.filing_policy import failure_record, provider_pause, read_attempts
from oraculum.local import main, parser
from oraculum.local_web import make_server
from oraculum.market_research import (
    research_status,
    run_research,
    workflow_lock,
    write_json,
)
from oraculum.research_view import freshness_notice
from oraculum.serialization import load_json
from test_ai_briefs import report, publish, selection, inspector, NOW
import test_data_fundamentals as filing_fixtures
from test_market_research import CUTOFF, make_tape


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.report = report()
        self.asset = self.report["assets"][0]
        self.asset["status"] = "eligible"
        self.asset["fundamentals"].update(status="available", quarter_end="2026-06-30")

    def test_complete_inputs_are_not_a_buy_signal(self):
        original = deepcopy(self.report)
        data = snapshot(self.report)
        self.assertEqual(data["counts"]["complete"], 1)
        self.assertEqual(data["rows"][0]["financial_inputs"], 4)
        self.assertEqual(self.report, original)

    def test_missing_metric_does_not_become_zero(self):
        self.asset["fundamentals"]["metrics"]["roce"] = None
        data = snapshot(self.report)
        self.assertEqual(data["metric_counts"]["roce"], 0)
        self.assertEqual(data["rows"][0]["financial_inputs"], 3)
        self.assertIn("roce", data["rows"][0]["gaps"])

    def test_nonfinite_boolean_unknown_and_future_sources(self):
        base = deepcopy(self.report)
        edits = [
            {"value": True},
            {"value": float("nan")},
            {"source_ids": ["unknown"]},
            {"available_at": "2026-10-20T00:00:00Z"},
            {"periods": [{"end": "2027-01-01"}]},
            {"periods": []},
        ]
        for edit in edits:
            value = deepcopy(base)
            value["assets"][0]["fundamentals"]["metrics"]["roce"].update(edit)
            with self.subTest(edit=edit):
                self.assertIn("roce", snapshot(value)["rows"][0]["gaps"])
        self.asset["fundamentals"]["sources"][0]["received_at"] = "2026-10-20T00:00:00Z"
        self.assertEqual(snapshot(self.report)["counts"]["complete"], 0)

    def test_age_is_at_report_cutoff_and_review_flag_does_not_rescore(self):
        self.asset["fundamentals"]["quarter_end"] = "2025-12-31"
        original = deepcopy(self.asset["combined"])
        row = snapshot(self.report)["rows"][0]
        self.assertIn("older_financials", row["flags"])
        self.assertEqual(row["quarter_age_days"], 290)
        self.assertEqual(original, self.asset["combined"])

    def test_unknown_and_future_quarter_do_not_have_negative_ages(self):
        for value in (None, "bad", "2027-01-01"):
            self.asset["fundamentals"]["quarter_end"] = value
            self.assertIsNone(snapshot(self.report)["rows"][0]["quarter_age_days"])

    def test_categories_keep_unsupported_separate_from_technical_failure(self):
        self.asset["fundamentals"].update(status="unsupported_schema", metrics={})
        self.asset["status"] = "excluded"
        row = snapshot(self.report)["rows"][0]
        self.assertIn("unsupported_schema", row["flags"])
        self.assertIn("technical", row["flags"])
        self.assertIn("incomplete", row["flags"])

    def test_search_filter_and_pagination_are_consistent(self):
        self.report["assets"] = [
            dict(deepcopy(self.asset), symbol=f"FIX{i:03d}") for i in range(85)
        ]
        data = snapshot(self.report)
        first, second, last = (
            select(data),
            select(data, offset=40),
            select(data, offset=80),
        )
        self.assertEqual([len(r["items"]) for r in (first, second, last)], [40, 40, 5])
        self.assertIsNone(last["next_offset"])
        self.assertEqual(select(data, query="fix080")["total"], 1)
        self.assertEqual(select(data, category="incomplete")["total"], 0)

    def test_invalid_queries_fail_explicitly(self):
        for kwargs in (
            {"query": "x" * 81},
            {"category": "made_up"},
            {"offset": -1},
            {"offset": True},
            {"limit": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                select(snapshot(self.report), **kwargs)

    def test_csv_formula_injection_and_html_are_escaped(self):
        self.asset["company_name"] = '=HYPERLINK("bad")<script>alert(1)</script>'
        data = select(snapshot(self.report))
        self.assertIn("'=HYPERLINK", csv_export(data))
        html = coverage_html(data, {"message": "<script>bad</script>"})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_freshness_uses_calendar_sessions_not_elapsed_days(self):
        _, raw, _, _, _, _ = make_tape()
        self.report.update(calendar={"schedule": raw}, last_session="2026-10-16")
        state = freshness(self.report, now=NOW)
        self.assertEqual(state["expected_session"], "2026-10-19")
        self.assertEqual(state["missing_sessions"], 1)
        self.assertEqual(
            freshness(self.report, now=NOW + timedelta(days=50))["state"],
            "calendar_review",
        )

    def test_failed_daily_job_is_not_hidden_by_old_research_status(self):
        from test_dashboard_ui import ui_report
        from oraculum.dashboard_view import today_html
        html = today_html(ui_report(), {"state": "running"}, workflow={"state": "failed", "phase": "research", "error": "history broken"}, now=CUTOFF)
        self.assertIn("Daily workflow failed", html)
        self.assertIn("history broken", html)

    def test_empty_and_legacy_reports(self):
        self.assertIsNone(snapshot(None)["report_id"])
        self.asset.pop("fundamentals")
        self.assertEqual(snapshot(self.report)["counts"]["incomplete"], 1)
        self.assertIn(
            "No saved report", coverage_html(select(snapshot(None)), freshness(None))
        )


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_active_writer_and_stopped_without_status_completion(self):
        with heartbeat(self.folder, clock=lambda: NOW) as active:
            status = {"state": "running", "activity_id": active["id"]}
            self.assertEqual(
                observed_status(self.folder, status, now=NOW)["activity"]["state"],
                "active",
            )
        self.assertEqual(
            observed_status(self.folder, status, now=NOW)["activity"]["state"],
            "stopped",
        )
        self.assertEqual(status, {"state": "running", "activity_id": active["id"]})

    def test_heartbeat_renews_without_reporting_fake_download_progress(self):
        called = threading.Event()
        real = write_json
        count = []

        def writer(path, data):
            real(path, data)
            count.append(data)
            if len(count) > 1:
                called.set()

        with patch("oraculum.market_research.write_json", side_effect=writer):
            with heartbeat(self.folder, interval=0.02, clock=lambda: NOW):
                self.assertTrue(called.wait(2))
        self.assertNotIn("completed_sessions", count[-1])

    def test_stale_clock_mismatch_and_wrong_run_are_not_active(self):
        write_json(
            self.folder / "activity.json",
            {"id": "one", "state": "active", "heartbeat_at": iso(NOW)},
        )
        status = {"state": "running", "activity_id": "one"}
        self.assertEqual(
            observed_status(self.folder, status, now=NOW + timedelta(seconds=91))[
                "activity"
            ]["state"],
            "stale",
        )
        self.assertEqual(
            observed_status(self.folder, status, now=NOW - timedelta(seconds=10))[
                "activity"
            ]["state"],
            "clock_mismatch",
        )
        self.assertEqual(
            observed_status(self.folder, {**status, "activity_id": "two"}, now=NOW)[
                "activity"
            ]["state"],
            "unknown",
        )

    def test_reading_unknown_or_corrupt_telemetry_never_writes(self):
        before = list(self.folder.iterdir())
        self.assertEqual(
            observed_status(self.folder, {"state": "running"}, now=NOW)["activity"][
                "state"
            ],
            "unknown",
        )
        self.assertEqual(before, list(self.folder.iterdir()))
        (self.folder / "activity.json").write_text("broken")
        self.assertEqual(
            observed_status(self.folder, {"state": "running"}, now=NOW)["activity"][
                "state"
            ],
            "unknown",
        )

    def test_telemetry_permission_failure_is_nonfatal(self):
        with patch(
            "oraculum.market_research.write_json", side_effect=PermissionError("locked")
        ):
            with heartbeat(self.folder) as active:
                self.assertTrue(active["id"])

    def test_completed_status_wins_over_old_heartbeat(self):
        value = {"state": "ready", "report_id": "saved"}
        self.assertEqual(observed_status(self.folder, value, now=NOW), value)

    def test_actual_process_termination_releases_lock_and_stales_activity(self):
        script = "from pathlib import Path\nimport time\nfrom oraculum.market_research import workflow_lock,write_json\np=Path(__import__('sys').argv[1])\nwith workflow_lock(p) as a:\n write_json(p/'status.json',{'state':'running','activity_id':a['id']})\n print('ready',flush=True)\n time.sleep(60)\n"
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(self.folder)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            with self.assertRaises(ValidationError):
                with workflow_lock(self.folder):
                    pass
            status = load_json(self.folder / "status.json")
            child.terminate()
            child.wait(timeout=5)
            from datetime import datetime
            from oraculum.contracts import UTC

            seen = observed_status(
                self.folder, status, now=datetime.now(UTC) + timedelta(minutes=2)
            )
            self.assertEqual(seen["activity"]["state"], "stale")
            with workflow_lock(self.folder) as new:
                self.assertNotEqual(new["id"], status["activity_id"])
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()
            child.stderr.close()

    def test_detailed_research_progress_is_visible_and_final_receipt_saved(self):
        _, _, _, _, files, _ = make_tape()
        messages = []

        def progress(message):
            saved = research_status(self.folder)
            if saved:
                messages.append(saved.get("last_message"))

        result = run_research(
            self.folder,
            downloader=lambda session: (files[session], "https://example.test/fixture"),
            clock=lambda: CUTOFF,
            pause=lambda _: None,
            progress=progress,
        )
        self.assertTrue(any("cached" in m or "downloading" in m for m in messages if m))
        self.assertEqual(research_status(self.folder)["report_id"], result["report_id"])
        self.assertEqual(research_status(self.folder)["state"], "ready")

    def test_unknown_activity_does_not_claim_running(self):
        text = activity_message({"state": "running"})
        self.assertIn("unconfirmed", text)
        self.assertNotIn("is active", text)


class FilingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "attempts.json"

    def test_cooldowns_are_classified_and_expire(self):
        for exc, hours in (
            (TimeoutError("timeout"), 1),
            (ValidationError("bad XML"), 168),
            (HTTPError("url", 429, "limit", None, None), 24),
        ):
            value = failure_record(exc, NOW)
            write_json(self.path, {"key": value})
            self.assertIn("key", read_attempts(self.path, NOW + timedelta(minutes=30)))
            self.assertNotIn(
                "key", read_attempts(self.path, NOW + timedelta(hours=hours))
            )

    def test_legacy_attempts_keep_one_day_cooldown(self):
        write_json(self.path, {"old": {"at": iso(NOW), "error": "old failure"}})
        self.assertIn("old", read_attempts(self.path, NOW + timedelta(hours=23)))
        self.assertFalse(read_attempts(self.path, NOW + timedelta(days=1)))

    def test_corrupt_or_future_attempts_fail_without_discarding_file(self):
        for value in ([], {"x": None}, {"x": {"at": iso(NOW + timedelta(days=1))}}):
            write_json(self.path, value)
            before = self.path.read_bytes()
            with self.assertRaises((ValidationError, TypeError)):
                read_attempts(self.path, NOW)
            self.assertEqual(self.path.read_bytes(), before)


class FilingResumeTests(unittest.TestCase):
    setUp = filing_fixtures.BatchTests.setUp
    downloader = filing_fixtures.BatchTests.downloader
    run_batch = filing_fixtures.BatchTests.run_batch

    def test_denial_cooldown_applies_to_subsequent_runs(self):
        def denied(url):
            raise HTTPError(url, 403, "denied", None, None)

        self.run_batch(downloader=denied)
        result = self.run_batch(
            downloader=lambda _: self.fail("Provider cooldown bypassed")
        )
        self.assertEqual(result["fundamental_coverage"]["failed_this_run"], 0)
        self.assertEqual(
            result["fundamental_coverage"]["collection_mode"], "provider_cooldown"
        )
        self.assertTrue(result["fundamental_coverage"]["provider_retry_at"])

    def test_document_failure_does_not_block_other_filings(self):
        def malformed(url):
            self.requested.append(url)
            raise ValidationError("malformed XML")

        self.run_batch(downloader=malformed, max_filings=1)
        bad = self.requested[0]
        result = self.run_batch(max_filings=3)
        self.assertEqual(self.requested.count(bad), 1)
        self.assertEqual(result["fundamental_coverage"]["downloaded_this_run"], 3)
        self.assertEqual(result["fundamental_coverage"]["pending_documents"], 1)


class CoverageHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "data"
        self.server = make_server(
            self.folder / "runs.sqlite3", self.folder / "paper.sqlite3", port=0
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            conn.request("GET", path)
            res = conn.getresponse()
            return res.status, res.read().decode()
        finally:
            conn.close()

    def hashes(self):
        return {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.folder.rglob("*")
            if p.is_file()
        }

    def test_empty_views_create_no_files(self):
        for path in ("/coverage", "/api/coverage", "/coverage.csv"):
            self.assertEqual(self.get(path)[0], 200)
        self.assertFalse(self.folder.exists())

    def test_pinned_exports_search_and_readonly(self):
        value = report()
        publish(self.folder, value)
        before = self.hashes()
        base = "?report=" + value["report_id"]
        for path in ("/coverage", "/api/coverage", "/coverage.csv"):
            status, body = self.get(path + base)
            self.assertEqual(status, 200)
            self.assertIn("FIXTURE", body)
        status, body = self.get("/api/coverage" + base + "&q=unmatched")
        self.assertEqual(json.loads(body)["total"], 0)
        self.assertEqual(before, self.hashes())

    def test_bad_filters_ids_offsets_and_missing_archive(self):
        for suffix in (
            "?filter=bad",
            "?offset=-1",
            "?report=../../x",
            "?q=" + "x" * 81,
        ):
            self.assertEqual(self.get("/coverage" + suffix)[0], 400)
        self.assertEqual(self.get("/coverage?report=" + "a" * 64)[0], 404)

    def test_cli_is_readonly_and_supports_extended_evaluation(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(
                main(["coverage-status", "--data-dir", str(self.folder)]), 0
            )
        self.assertIsNone(json.loads(out.getvalue())["report_id"])
        self.assertFalse(self.folder.exists())
        self.assertTrue(parser().parse_args(["ai-evaluate", "--extended"]).extended)


class ExtendedEvaluationTests(unittest.TestCase):
    def test_eight_distinct_cases_and_isolated_evaluation(self):
        cases = list(fixtures(extended=True))
        self.assertEqual(len({x["name"] for x in cases}), 8)
        by_id = {x["packet"]["packet_id"]: x for x in cases}

        def gen(p, *args, **kwargs):
            raw = selection(p)
            expected = by_id[p["packet_id"]]["expected_tone"]
            events = [f["id"] for f in p["facts"] if f["kind"] == "event"]
            raw["event_tone"] = {
                "label": expected,
                "citations": events if expected != "unclear" else [],
            }
            return {"raw": json.dumps(raw)}

        with tempfile.TemporaryDirectory() as name:
            result = evaluate(
                Path(name),
                model="fixture:local",
                inspector=inspector,
                generator=gen,
                extended=True,
                progress=lambda _: None,
            )
            self.assertEqual(result["passed"], 8)
            self.assertEqual(result["suite"], "extended-v1")
            self.assertFalse((Path(name) / "research").exists())

    def test_wrong_event_tone_fails_extended_case(self):
        with tempfile.TemporaryDirectory() as name:
            result = evaluate(
                Path(name),
                model="fixture:local",
                inspector=inspector,
                generator=lambda p, *a, **k: {"raw": json.dumps(selection(p))},
                extended=True,
                progress=lambda _: None,
            )
            self.assertLess(result["passed"], result["total"])


if __name__ == "__main__":
    unittest.main()
