"""Evidence integrity, constrained model output, local transport and app integration."""

from contextlib import closing, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from oraculum.ai_contract import (
    assemble,
    choices,
    model_schema,
    strict_json,
    validate_selection,
)
from oraculum.ai_evaluation import evaluate, fixtures
from oraculum.ai_evidence import build_packet, prompt_packet
from oraculum.ai_runtime import MAX_RESPONSE, generate, model_name, preflight, request
from oraculum.ai_store import BriefStore
from oraculum.contracts import ValidationError
from oraculum.daily_workflow import run_daily
from oraculum.local import main, parser
from oraculum.local_web import make_server
from oraculum.market_research import write_json
from oraculum.research_briefs import (
    cache_key,
    configure,
    disable,
    load_config,
    read_brief,
    run_briefs,
    status,
)
from oraculum.serialization import digest

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
CUTOFF = "2026-10-17T12:00:00Z"
MODEL = {
    "name": "fixture:local",
    "digest": "b" * 64,
    "runtime_version": "test",
    "size_bytes": 100,
}


def seal(value):
    value.pop("report_id", None)
    value["report_id"] = digest(value)
    return value


def report():
    source = {
        "source_id": "price-1",
        "kind": "price",
        "uri": "https://example.test/prices",
        "sha256": "a" * 64,
        "received_at": CUTOFF,
    }
    filing = {**source, "source_id": "filing-1", "kind": "financial"}
    metric = {
        "value": 0.2,
        "source_ids": ["filing-1"],
        "available_at": CUTOFF,
        "periods": [{"start": "2026-04-01", "end": "2026-06-30"}],
        "formula": "Fictional calculation",
    }
    asset = {
        "symbol": "FIXTURE",
        "company_name": "Fictional Company",
        "isin": "IN0000000001",
        "rank": 1,
        "metrics": {
            "close_inr": 100,
            "momentum_20d": 0.12,
            "trend_50d": 0.08,
            "volume_ratio_20d": 1.2,
            "volatility_20d_annualized": 0.3,
            "drawdown_50d": -0.2,
        },
        "combined": {"rank": 1, "score": 75, "highlight": True},
        "fundamentals": {
            "basis": "consolidated",
            "sources": [filing],
            "metrics": {
                k: deepcopy(metric)
                for k in ("revenue_yoy", "net_margin", "borrowings_to_equity", "roce")
            },
        },
    }
    return seal(
        {
            "report_schema": "oraculum-integrated-research-v2",
            "algorithm": "fixture",
            "as_of": CUTOFF,
            "last_session": "2026-10-16",
            "sources": [source],
            "evidence_sources": [],
            "assets": [asset],
        }
    )


def publish(folder, value):
    write_json(folder / "research" / (value["report_id"] + ".json"), value)
    write_json(folder / "research/latest.json", {"report_id": value["report_id"]})


def no_events(*args, **kwargs):
    return {"items": [], "total": 0}


def packet():
    return build_packet(Path("unused"), report(), "FIXTURE", events_reader=no_events)


def selection(p):
    allowed = choices(p)
    pairs = (
        [{"support": allowed["supports"][0], "caution": allowed["counterpoints"][0]}]
        if not p["must_abstain"] and allowed["supports"] and allowed["counterpoints"]
        else []
    )
    return {
        "summary": [p["facts"][0]["id"]],
        "supports": [],
        "risks": [],
        "tensions": pairs,
        "questions": [],
        "event_tone": {"label": "unclear", "citations": []},
        "abstain": p["must_abstain"],
    }


def inspector(*args, **kwargs):
    return deepcopy(MODEL)


def generator(p, *args, **kwargs):
    return {
        "raw": json.dumps(selection(p)),
        "prompt_sha256": "c" * 64,
        "stats": {"eval_count": 30},
    }


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "uncreated"
        self.report = report()

    def build(self, reader=no_events):
        return build_packet(self.folder, self.report, "FIXTURE", events_reader=reader)

    def test_packets_preserve_report_and_need_no_io(self):
        before = deepcopy(self.report)
        p = self.build()
        self.assertEqual(
            p["coverage"], {"technical_metrics": 6, "financial_metrics": 4, "events": 0}
        )
        self.assertEqual(self.report, before)
        self.assertFalse(self.folder.exists())
        self.assertEqual(len(p["sources"]), 2)

    def test_tampering_and_unknown_stock_rejected(self):
        self.report["algorithm"] = "changed"
        with self.assertRaises(ValidationError):
            self.build()
        seal(self.report)
        with self.assertRaises(ValidationError):
            build_packet(self.folder, self.report, "OTHER")

    def test_one_late_price_source_invalidates_derived_technicals(self):
        self.report["sources"].append(
            {
                **self.report["sources"][0],
                "source_id": "late",
                "received_at": "2026-10-18T12:00:00Z",
            }
        )
        seal(self.report)
        self.assertEqual(self.build()["coverage"]["technical_metrics"], 0)

    def test_missing_prices_and_future_action_receipts_block_metrics(self):
        for change in ("missing", "late_action"):
            self.report = report()
            if change == "missing":
                self.report["sources"] = []
            else:
                self.report["evidence_sources"] = [
                    {
                        **self.report["sources"][0],
                        "kind": "actions",
                        "source_id": "action",
                        "received_at": "2026-10-18T12:00:00Z",
                    }
                ]
            seal(self.report)
            with self.subTest(change=change):
                self.assertEqual(self.build()["coverage"]["technical_metrics"], 0)

    def test_financial_dates_sources_and_boolean_values_are_checked(self):
        for key, value in (
            ("available_at", "2026-10-19T12:00:00Z"),
            ("source_ids", ["missing"]),
            ("periods", [{"end": "2026-12-31"}]),
            ("value", True),
        ):
            self.report = report()
            self.report["assets"][0]["fundamentals"]["metrics"]["roce"][key] = value
            seal(self.report)
            with self.subTest(key=key):
                self.assertEqual(self.build()["coverage"]["financial_metrics"], 3)

    def test_missing_coverage_requires_abstention_and_is_not_neutral(self):
        self.report["sources"] = []
        self.report["assets"][0]["fundamentals"] = {}
        seal(self.report)
        p = self.build()
        self.assertTrue(p["must_abstain"])
        self.assertTrue(
            any(
                "not neutral" in f["text"]
                for f in p["facts"]
                if f["id"] in p["required_cautions"]
            )
        )

    def event(self):
        return {
            "revision_id": "d" * 64,
            "revision_checksum": "e" * 64,
            "title": "Routine fictional board meeting announced",
            "excerpt": "No results included",
            "source_name": "Fictional",
            "url": "https://example.test/event",
            "received_at": CUTOFF,
            "published_at": CUTOFF,
            "receipt": {"received_at": CUTOFF, "sha256": "f" * 64},
            "match_state": "matched",
            "matches": [
                {"symbol": "FIXTURE", "isin": "IN0000000001", "method": "name"}
            ],
        }

    def test_tentative_news_and_receipts_are_retained(self):
        event = self.event()
        p = self.build(
            lambda *a, **k: (
                {"items": [event], "total": 1} if k["kind"] == "news" else no_events()
            )
        )
        fact = next(f for f in p["facts"] if f["kind"] == "event")
        self.assertTrue(fact["tentative"])
        self.assertIn("not independently verified", fact["text"])
        self.assertTrue(any(s.get("receipt") for s in p["sources"]))

    def test_identity_conflicts_and_later_events_are_excluded(self):
        changes = [
            lambda e: e.update(match_state="conflict"),
            lambda e: e["matches"][0].update(isin="OTHER"),
            lambda e: e.update(published_at=None),
            lambda e: e.update(published_at="2026-10-19T12:00:00Z"),
            lambda e: e.update(received_at="2026-10-19T12:00:00Z"),
            lambda e: e["receipt"].update(received_at="2026-10-19T12:00:00Z"),
        ]
        for change in changes:
            event = self.event()
            change(event)
            p = self.build(
                lambda *a, **k: (
                    {"items": [event], "total": 1}
                    if k["kind"] == "announcement"
                    else no_events()
                )
            )
            with self.subTest(event=event):
                self.assertEqual(p["coverage"]["events"], 0)

    def test_omitted_events_and_cache_failures_are_disclosed(self):
        p = self.build(
            lambda *a, **k: {"items": [], "total": 10, "notice": "cache unavailable"}
        )
        text = " ".join(f["text"] for f in p["facts"])
        self.assertIn("omitted", text)
        self.assertIn("cache unavailable", text)

    def test_prompt_excludes_source_urls_and_hashes(self):
        text = str(prompt_packet(self.build()))
        self.assertNotIn("https://", text)
        self.assertNotIn("sha256", text)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.p = packet()
        self.raw = selection(self.p)

    def reject(self):
        with self.assertRaises(ValidationError):
            validate_selection(self.raw, self.p)

    def test_assembly_copies_exact_source_and_preserves_input(self):
        before = deepcopy(self.p)
        brief = assemble(self.raw, self.p)
        self.assertIn(brief["summary"][0]["text"], self.p["facts"][0]["text"])
        self.assertEqual(before, self.p)

    def test_arbitrary_prose_cannot_enter_the_contract(self):
        self.raw["summary"] = ["Guaranteed profits from a fabricated number"]
        self.reject()
        self.raw = selection(self.p)
        self.raw["prediction"] = "buy"
        self.reject()

    def test_unknown_duplicate_and_wrong_type_references_rejected(self):
        for refs in (["E999"], ["E01", "E01"], [1], "E01", [{"id": "E01"}]):
            self.raw["summary"] = refs
            with self.subTest(refs=refs):
                self.reject()

    def test_empty_summary_and_excess_claims_rejected(self):
        self.raw["summary"] = []
        self.reject()
        self.raw["summary"] = [f["id"] for f in self.p["facts"][:3]]
        self.reject()

    def test_support_risk_and_question_roles_are_enforced(self):
        for key in ("supports", "risks", "questions"):
            self.raw = selection(self.p)
            self.raw[key] = ["E01"]
            with self.subTest(key=key):
                self.reject()

    def test_comparison_needs_support_then_caution(self):
        allowed = choices(self.p)
        self.raw["tensions"] = [
            {"support": allowed["supports"][0], "caution": allowed["counterpoints"][0]}
        ]
        validate_selection(self.raw, self.p)
        self.raw["tensions"][0] = {
            "support": allowed["counterpoints"][0],
            "caution": allowed["supports"][0],
        }
        self.reject()
        self.raw["tensions"] = [[allowed["supports"][0]]]
        self.reject()

    def test_balanced_evidence_cannot_silently_skip_comparison(self):
        self.raw["tensions"] = []
        self.reject()
        self.raw["abstain"] = True
        validate_selection(self.raw, self.p)
        schema = model_schema(self.p)
        self.assertEqual(schema["properties"]["tensions"]["minItems"], 1)
        sparse = next(fixtures())["packet"]
        self.assertEqual(model_schema(sparse)["properties"]["tensions"]["maxItems"], 0)

    def test_tone_cannot_use_prices_or_uncited_direction(self):
        self.raw["event_tone"] = {"label": "positive", "citations": ["E01"]}
        self.reject()
        self.raw["event_tone"]["citations"] = []
        self.reject()

    def test_abstention_is_boolean_and_enforced(self):
        self.raw["abstain"] = 1
        self.reject()
        self.p = next(fixtures())["packet"]
        self.raw = selection(self.p)
        validate_selection(self.raw, self.p)
        self.raw["abstain"] = False
        self.reject()

    def test_abstention_cannot_retain_favorable_claims(self):
        self.raw["abstain"] = True
        self.raw["supports"] = [choices(self.p)["supports"][0]]
        self.reject()

    def test_schema_restricts_missing_event_tone_and_support_choices(self):
        properties = model_schema(self.p)["properties"]
        self.assertEqual(
            properties["event_tone"]["properties"]["label"]["enum"], ["unclear"]
        )
        self.assertEqual(
            properties["event_tone"]["properties"]["citations"]["maxItems"], 0
        )
        self.assertEqual(
            properties["supports"]["items"]["enum"], choices(self.p)["supports"]
        )

    def test_duplicate_json_nonfinite_and_oversized_output_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', "```json\n{}\n```"):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                strict_json(raw)
        with self.assertRaises(ValidationError):
            validate_selection("x" * 16001, self.p)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.report = report()

    def config(self, **kwargs):
        return configure(
            self.folder, model=MODEL["name"], inspector=inspector, **kwargs
        )

    def run_batch(self, **kwargs):
        return run_briefs(
            self.folder,
            self.report,
            **(
                {
                    "clock": lambda: NOW,
                    "progress": lambda _: None,
                    "inspector": inspector,
                    "generator": generator,
                }
                | kwargs
            ),
        )

    def test_unconfigured_and_empty_audit_are_read_only(self):
        runtime = Mock(side_effect=AssertionError("must not run"))
        self.assertEqual(self.run_batch(inspector=runtime)["state"], "not_configured")
        self.assertEqual(
            status(self.folder, audit=True)["audit"],
            {"ok": True, "packets": 0, "records": 0},
        )
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_bad_configuration_does_not_call_runtime(self):
        runtime = Mock()
        for kwargs in (
            {"limit": 0},
            {"limit": True},
            {"timeout": 601},
            {"budget": 1},
            {"port": 80},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                configure(self.folder, inspector=runtime, **kwargs)
        runtime.assert_not_called()

    def test_missing_weights_do_not_enable_generation(self):
        with self.assertRaises(ValidationError):
            configure(
                self.folder, inspector=Mock(side_effect=ValidationError("missing"))
            )
        self.assertIsNone(load_config(self.folder))

    def test_accepted_receipts_preserve_model_and_separate_generation_time(self):
        self.config()
        before = deepcopy(self.report)
        self.assertEqual(self.run_batch()["accepted"], 1)
        bundle = read_brief(self.folder, self.report, "FIXTURE")
        self.assertEqual(bundle["attempt"]["model"]["digest"], MODEL["digest"])
        self.assertTrue(bundle["current_configuration"])
        self.assertNotEqual(bundle["attempt"]["generated_at"], self.report["as_of"])
        self.assertEqual(before, self.report)
        self.assertEqual(
            BriefStore(self.folder).audit(), {"ok": True, "packets": 1, "records": 2}
        )

    def test_cache_works_without_runtime_and_has_no_duplicate_attempts(self):
        self.config()
        self.run_batch()
        runtime = Mock(side_effect=AssertionError("offline"))
        self.assertEqual(
            self.run_batch(inspector=runtime, generator=runtime)["cached"], 1
        )
        runtime.assert_not_called()
        self.assertEqual(BriefStore(self.folder).audit()["records"], 2)

    def test_rejected_output_is_retained_and_requires_explicit_retry(self):
        self.config()
        bad = Mock(return_value={"raw": '{"forecast":"invalid"}'})
        self.assertEqual(self.run_batch(generator=bad)["rejected"], 1)
        self.run_batch(generator=bad)
        self.assertEqual(bad.call_count, 1)
        item = BriefStore(self.folder).latest(symbol="FIXTURE")
        self.assertNotIn("brief", item)
        self.assertIn("forecast", item["raw_output"])
        self.assertEqual(self.run_batch(retry=True)["accepted"], 1)
        self.assertEqual(BriefStore(self.folder).audit()["records"], 4)

    def test_missing_runtime_preserves_evidence_and_report(self):
        self.config()
        publish(self.folder, self.report)
        before = (
            self.folder / "research" / (self.report["report_id"] + ".json")
        ).read_bytes()
        self.assertEqual(
            self.run_batch(inspector=Mock(side_effect=ValidationError("offline")))[
                "state"
            ],
            "unavailable",
        )
        self.assertTrue(
            read_brief(self.folder, self.report, "FIXTURE")["packet"]["facts"]
        )
        self.assertEqual(
            before,
            (
                self.folder / "research" / (self.report["report_id"] + ".json")
            ).read_bytes(),
        )

    def test_generation_failure_and_changed_model_are_not_accepted(self):
        self.config()
        self.assertEqual(
            self.run_batch(generator=Mock(side_effect=ValidationError("timeout")))[
                "failed"
            ],
            1,
        )
        check = Mock(side_effect=[MODEL, {**MODEL, "digest": "d" * 64}])
        self.assertEqual(self.run_batch(inspector=check, retry=True)["rejected"], 1)

    def test_future_report_is_rejected_before_model_call(self):
        self.config()
        self.report["as_of"] = "2026-10-20T12:00:00Z"
        seal(self.report)
        with self.assertRaises(ValidationError):
            self.run_batch()

    def test_disable_preserves_saved_brief(self):
        self.config()
        self.run_batch()
        disable(self.folder)
        self.assertEqual(self.run_batch()["state"], "disabled")
        self.assertEqual(
            read_brief(self.folder, self.report, "FIXTURE")["attempt"]["state"],
            "accepted",
        )

    def test_new_report_and_model_have_distinct_cache_identity(self):
        self.config()
        self.run_batch()
        configure(self.folder, inspector=lambda *a, **k: {**MODEL, "digest": "d" * 64})
        self.assertFalse(
            read_brief(self.folder, self.report, "FIXTURE")["current_configuration"]
        )
        self.report["algorithm"] = "new"
        seal(self.report)
        self.assertIsNone(read_brief(self.folder, self.report, "FIXTURE")["attempt"])

    def test_saved_packet_survives_loss_of_event_cache(self):
        self.config()
        self.run_batch()
        with patch(
            "oraculum.research_briefs.build_packet",
            side_effect=AssertionError("use saved packet"),
        ):
            self.assertTrue(read_brief(self.folder, self.report, "FIXTURE")["attempt"])

    def test_immutable_records_and_corruption_fallback(self):
        self.config()
        self.run_batch()
        with closing(sqlite3.connect(BriefStore(self.folder).path)) as conn, conn:
            for sql in (
                "DELETE FROM packets",
                "UPDATE packets SET payload='bad'",
                "DELETE FROM records",
                "UPDATE records SET sha='bad'",
            ):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql)
            conn.execute("DROP TRIGGER records_no_update")
            conn.execute("UPDATE records SET sha='bad' WHERE phase='finish'")
        with self.assertRaises(ValidationError):
            BriefStore(self.folder).audit()
        bundle = read_brief(self.folder, self.report, "FIXTURE")
        self.assertIsNone(bundle["attempt"])
        self.assertIn("integrity", bundle["error"])

    def test_unmatched_finish_and_modified_narrative_are_rejected(self):
        self.config()
        self.run_batch()
        store = BriefStore(self.folder)
        item = store.latest(symbol="FIXTURE")
        item["attempt_id"] = "new"
        with self.assertRaises(ValidationError):
            store.record(item)
        item["brief"]["summary"][0]["text"] = "invented"
        with self.assertRaises(ValidationError):
            store.record(item)

    def test_interruption_retains_start_and_resume_is_safe(self):
        self.config()
        with self.assertRaises(KeyboardInterrupt):
            self.run_batch(generator=Mock(side_effect=KeyboardInterrupt()))
        self.assertEqual(status(self.folder)["last_batch"]["state"], "interrupted")
        self.assertEqual(BriefStore(self.folder).audit()["records"], 1)
        self.assertEqual(self.run_batch()["accepted"], 1)

    def test_budget_and_consecutive_errors_leave_pending_work(self):
        self.config(budget=60)
        result = self.run_batch(monotonic=Mock(side_effect=[0, 60, 60]))
        self.assertEqual((result["state"], result["pending"]), ("partial", 1))
        for i in range(2):
            asset = deepcopy(self.report["assets"][0])
            asset["symbol"] = f"OTHER{i}"
            self.report["assets"].append(asset)
        seal(self.report)
        result = self.run_batch(generator=Mock(side_effect=ValidationError("timeout")))
        self.assertEqual((result["failed"], result["pending"]), (2, 1))

    def test_unknown_symbol_and_invalid_limit_fail_cleanly(self):
        self.config()
        for kwargs in (
            {"symbol": "OTHER"},
            {"limit": True},
            {"limit": 21},
            {"limit": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.run_batch(**kwargs)

    def test_ai_failure_happens_after_paper_and_does_not_fail_daily(self):
        order = []

        def research(*a, **k):
            order.append("research")
            publish(self.folder, self.report)
            return self.report

        def paper(*a, **k):
            order.append("paper")
            return {"state": {"strategy": {"positions": {}, "pending": []}}}

        def ai(*a, **k):
            order.append("ai")
            self.assertTrue((self.folder / "automation/paper-latest.json").is_file())
            raise ValidationError("model offline")

        result = run_daily(
            self.folder,
            research_runner=research,
            paper_runner=paper,
            ai_runner=ai,
            clock=lambda: NOW,
            progress=lambda _: None,
        )
        self.assertEqual(order, ["research", "paper", "ai"])
        self.assertEqual(result["status"]["state"], "ready")
        self.assertEqual(result["status"]["ai_state"], "unavailable")

    def test_paper_failure_never_starts_ai(self):
        ai = Mock()
        with self.assertRaises(ValidationError):
            run_daily(
                self.folder,
                research_runner=lambda *a, **k: self.report,
                paper_runner=Mock(side_effect=ValidationError("paper")),
                ai_runner=ai,
                clock=lambda: NOW,
                progress=lambda _: None,
            )
        ai.assert_not_called()

    def test_fictional_evaluation_does_not_create_market_records(self):
        def gen(p, *a, **k):
            raw = selection(p)
            if any("cancelled" in f["text"] for f in p["facts"]):
                raw["tensions"] = [{"support": "E01", "caution": "E02"}]
                raw["event_tone"] = {"label": "negative", "citations": ["E03"]}
            return {"raw": json.dumps(raw)}

        self.config()
        result = evaluate(
            self.folder, inspector=inspector, generator=gen, progress=lambda _: None
        )
        self.assertEqual(result["passed"], 3)
        self.assertTrue(status(self.folder)["evaluation_current"])
        self.assertFalse((self.folder / "research").exists())
        self.assertFalse(BriefStore(self.folder).path.exists())

    def test_cli_defaults_and_status_are_read_only(self):
        args = parser().parse_args(["ai-configure"])
        self.assertEqual((args.limit, args.timeout, args.budget), (3, 600, 1800))
        with redirect_stdout(io.StringIO()) as out:
            code = main(["ai-status", "--audit", "--data-dir", str(self.folder)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["state"], "not_configured")
        self.assertEqual(list(self.folder.iterdir()), [])


def metadata(method, path, data=None, **kwargs):
    if path == "/api/tags":
        return {
            "models": [{"name": MODEL["name"], "digest": MODEL["digest"], "size": 100}]
        }
    if path == "/api/show":
        return {"model_info": {"parameters": 100}}
    return {"version": "test"}


class RuntimeTests(unittest.TestCase):
    def test_local_metadata_pins_digest_and_runtime(self):
        value = preflight(MODEL["name"], transport=metadata)
        self.assertEqual(value["digest"], MODEL["digest"])
        self.assertEqual(value["runtime_version"], "test")

    def test_cloud_names_urls_and_changed_digest_are_rejected(self):
        for name in (
            "model:cloud",
            "https://remote/model",
            "../model",
            "model@remote",
            None,
            "a:b:c",
        ):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                model_name(name)
        self.assertEqual(model_name("fixture"), "fixture:latest")
        with self.assertRaises(ValidationError):
            preflight(MODEL["name"], expected_digest="d" * 64, transport=metadata)

    def test_remote_alias_and_missing_weights_are_rejected(self):
        for info in (
            {"model_info": {}},
            {"model_info": {"x": 1}, "remote_host": "remote"},
        ):

            def transport(method, path, data=None, **kwargs):
                return (
                    info
                    if path == "/api/show"
                    else metadata(method, path, data, **kwargs)
                )

            with self.subTest(info=info), self.assertRaises(ValidationError):
                preflight(MODEL["name"], transport=transport)
        with self.assertRaises(ValidationError):
            preflight("missing:local", transport=metadata)

    def test_ports_paths_and_timeouts_are_bounded(self):
        for kwargs in ({"port": 80}, {"port": True}, {"timeout": 0}, {"timeout": 601}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                request("GET", "/api/tags", **kwargs)
        with self.assertRaises(ValidationError):
            request("POST", "/api/pull")

    def test_generation_uses_selection_schema_without_tools(self):
        transport = Mock(
            return_value={
                "model": MODEL["name"],
                "done": True,
                "done_reason": "stop",
                "message": {"content": "{}"},
            }
        )
        generate(packet(), {"port": 12345, "timeout": 90}, MODEL, transport=transport)
        args, kwargs = transport.call_args
        self.assertEqual(args[:2], ("POST", "/api/chat"))
        self.assertEqual(
            args[2]["format"]["properties"]["summary"]["items"]["type"], "string"
        )
        self.assertNotIn("tools", args[2])
        self.assertFalse(args[2]["think"])

    def test_truncated_remote_and_wrong_model_output_rejected(self):
        base = {
            "model": MODEL["name"],
            "done": True,
            "done_reason": "stop",
            "message": {"content": "{}"},
        }
        for change in (
            {"done": False},
            {"done_reason": "length"},
            {"remote_model": "cloud"},
            {"model": "other:local"},
            {"message": {"content": "{}", "tool_calls": [{}]}},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                generate(
                    packet(),
                    {"port": 12345, "timeout": 90},
                    MODEL,
                    transport=Mock(return_value=base | change),
                )


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.report = report()
        self.server = make_server(
            self.folder / "runs.sqlite3", self.folder / "paper.sqlite3", port=0
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, method="GET", headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read().decode()
        finally:
            conn.close()

    def test_empty_briefs_and_status_do_not_create_files(self):
        self.assertEqual(self.get("/briefs")[0], 200)
        self.assertEqual(self.get("/api/ai-status")[0], 200)
        self.assertEqual(self.get("/brief?symbol=FIXTURE")[0], 404)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_pinned_pages_and_exports_never_generate_or_mutate_files(self):
        publish(self.folder, self.report)
        before = {
            p.relative_to(self.folder): p.read_bytes()
            for p in self.folder.rglob("*")
            if p.is_file()
        }
        query = urlencode({"report": self.report["report_id"], "symbol": "FIXTURE"})
        with patch(
            "oraculum.ai_runtime.request",
            side_effect=AssertionError("GET must not invoke model"),
        ):
            for path in ("/briefs", "/brief", "/api/brief", "/brief.md"):
                code, body = self.get(path + "?" + query)
                with self.subTest(path=path):
                    self.assertEqual(code, 200)
                    self.assertIn(self.report["report_id"], body)
        after = {
            p.relative_to(self.folder): p.read_bytes()
            for p in self.folder.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_unknown_symbol_bad_report_and_missing_archive_fail_cleanly(self):
        publish(self.folder, self.report)
        for path, expected in (
            ("/brief?symbol=OTHER", 404),
            ("/briefs?report=../bad", 400),
            ("/briefs?report=" + "f" * 64, 404),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], expected)

    def test_post_and_cross_site_requests_are_refused(self):
        self.assertEqual(self.get("/briefs", method="POST")[0], 501)
        self.assertEqual(self.get("/briefs", headers={"Host": "example.test"})[0], 403)
        self.assertEqual(
            self.get("/briefs", headers={"Sec-Fetch-Site": "cross-site"})[0], 403
        )

    def test_accepted_draft_is_labelled_and_source_html_escaped(self):
        self.report["assets"][0]["company_name"] = "<img src=x onerror=alert(1)>"
        self.report["assets"][0]["warnings"] = ["<script>alert('source')</script>"]
        seal(self.report)
        publish(self.folder, self.report)
        configure(self.folder, inspector=inspector)
        run_briefs(
            self.folder,
            self.report,
            inspector=inspector,
            generator=generator,
            clock=lambda: NOW,
            progress=lambda _: None,
        )
        code, body = self.get("/brief?symbol=FIXTURE")
        self.assertEqual(code, 200)
        self.assertIn("AI-selected evidence · review required", body)
        self.assertNotIn("<script>", body)
        self.assertNotIn("<img", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertEqual(body.count("<h1>"), 1)
        self.assertIn("Model digest:", self.get("/brief.md?symbol=FIXTURE")[1])

    def test_rejected_raw_output_is_withheld_from_narrative(self):
        publish(self.folder, self.report)
        configure(self.folder, inspector=inspector)
        bad = Mock(return_value={"raw": '{"claim":"UNSUPPORTED_SECRET"}'})
        run_briefs(
            self.folder,
            self.report,
            inspector=inspector,
            generator=bad,
            clock=lambda: NOW,
            progress=lambda _: None,
        )
        self.assertNotIn("UNSUPPORTED_SECRET", self.get("/brief?symbol=FIXTURE")[1])
        self.assertIn("UNSUPPORTED_SECRET", self.get("/api/brief?symbol=FIXTURE")[1])

    def test_search_escapes_query_and_matches_company_case_insensitively(self):
        publish(self.folder, self.report)
        self.assertIn("FIXTURE", self.get("/briefs?q=fictional")[1])
        body = self.get("/briefs?" + urlencode({"q": "<script>bad</script>"}))[1]
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)


class TransportHTTPTests(unittest.TestCase):
    def server(self, body=b"{}", code=200, drip=False):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                try:
                    self.send_response(code)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Location", "https://example.test")
                    self.end_headers()
                    if drip:
                        for byte in body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(0.025)
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_proxy_environment_is_ignored(self):
        port = self.server(b'{"version":"local"}')
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://127.0.0.1:1",
                "HTTPS_PROXY": "http://127.0.0.1:1",
                "ALL_PROXY": "http://127.0.0.1:1",
            },
        ):
            self.assertEqual(
                request("GET", "/api/version", port=port)["version"], "local"
            )

    def test_redirect_bad_json_and_oversized_response_rejected(self):
        for body, code in (
            (b"{}", 302),
            (b'{"x":1,"x":2}', 200),
            (b"[]", 200),
            (b" " * (MAX_RESPONSE + 2), 200),
        ):
            port = self.server(body, code)
            with self.subTest(code=code), self.assertRaises(ValidationError):
                request("GET", "/api/version", port=port)

    def test_wallclock_deadline_stops_drip_response(self):
        port = self.server(b'{"version":"' + b"x" * 80 + b'"}', drip=True)
        started = time.monotonic()
        with self.assertRaises(ValidationError):
            request("GET", "/api/version", port=port, timeout=0.15)
        self.assertLess(time.monotonic() - started, 1)
