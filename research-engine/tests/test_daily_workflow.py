"""Archive recovery, daily orchestration, read-only HTTP and scheduler integration."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oraculum.contracts import ValidationError
from oraculum.daily_workflow import run_daily
from oraculum.forward_paper import ForwardLedger
from oraculum.local import main, parser
from oraculum.local_schedule import schedule
from oraculum.local_web import make_server
from oraculum.market_research import build_research, read_research, save_research, write_json
from oraculum.research_history import ResearchHistory
from oraculum.serialization import digest, load_json
from tests.test_combined_forward import actions, fixture, report, snapshot, stamp
from tests.test_market_research import CUTOFF, make_tape


class HistoryAndDailyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        calendar,raw,info,_,_,snaps=make_tape()
        cls.r=build_research(snaps,calendar,raw,info,as_of=CUTOFF)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def runner(self,*args,**kwargs):
        save_research(self.folder,self.r)
        return self.r

    def test_saved_reports_are_indexed_once_and_old_reports_recover(self):
        save_research(self.folder,self.r);save_research(self.folder,self.r)
        history=ResearchHistory(self.folder)
        self.assertEqual(history.list()["total"],1)
        another=deepcopy(self.r);another["as_of"]="2026-10-14T21:00:00Z"
        another["report_id"]=digest({k:v for k,v in another.items() if k!="report_id"})
        write_json(self.folder/"research"/(another["report_id"]+".json"),another)
        self.assertEqual(history.recover(),1)
        self.assertEqual(history.recover(),0)
        first=history.list(limit=1)
        self.assertEqual(first["items"][0]["report_id"],another["report_id"])
        self.assertEqual(first["next_offset"],1)
        self.assertEqual(history.list(limit=1,offset=1)["items"][0]["report_id"],self.r["report_id"])

    def test_history_read_is_read_only_and_tampered_report_cannot_be_archived(self):
        history=ResearchHistory(self.folder)
        self.assertEqual(history.list()["total"],0)
        self.assertFalse(history.path.exists())
        r=deepcopy(self.r);r["algorithm"]="changed"
        with self.assertRaises(ValidationError):history.add(r)
        self.assertFalse(history.path.exists())

    def test_history_has_immutable_records(self):
        save_research(self.folder,self.r)
        with closing(sqlite3.connect(self.folder/"research-history.sqlite3")) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):conn.execute("DELETE FROM reports")

    def test_history_orders_fractional_seconds_chronologically(self):
        one=deepcopy(self.r);one["as_of"]="2026-10-14T20:00:00Z"
        two=deepcopy(self.r);two["as_of"]="2026-10-14T20:00:00.000001Z"
        history=ResearchHistory(self.folder)
        for r in (one,two):
            r["report_id"]=digest({k:v for k,v in r.items() if k!="report_id"})
            history.add(r)
        self.assertEqual(history.list()["items"][0]["report_id"],two["report_id"])

    def test_paper_failure_preserves_published_research_and_reports_phase(self):
        def fail(*a,**k):raise ValidationError("unsupported share action")
        with self.assertRaises(ValidationError):
            run_daily(self.folder,research_runner=self.runner,paper_runner=fail,clock=lambda:CUTOFF,progress=lambda _:None)
        self.assertEqual(read_research(self.folder)["report_id"],self.r["report_id"])
        status=load_json(self.folder/"automation/status.json")
        self.assertEqual(status["state"],"failed");self.assertEqual(status["phase"],"paper")
        self.assertEqual(status["report_id"],self.r["report_id"])
        self.assertIn("unsupported share action",(self.folder/"automation/daily.log").read_text())

    def test_research_failure_never_invokes_paper(self):
        def fail(*a,**k):raise ValidationError("missing market session")
        with patch("oraculum.daily_workflow.advance_paper") as paper:
            with self.assertRaises(ValidationError):
                run_daily(self.folder,research_runner=fail,clock=lambda:CUTOFF,progress=lambda _:None)
            paper.assert_not_called()
        self.assertFalse((self.folder/"forward.sqlite3").exists())

    def test_research_only_leaves_paper_uninitialized(self):
        r=run_daily(self.folder,research_runner=self.runner,paper=False,clock=lambda:CUTOFF,progress=lambda _:None)
        self.assertIsNone(r["paper"])
        self.assertFalse((self.folder/"forward.sqlite3").exists())
        self.assertEqual(r["status"]["state"],"ready")

    def test_rerun_recovers_after_paper_failure(self):
        def fail(*a,**k):raise ValidationError("first attempt")
        with self.assertRaises(ValidationError):
            run_daily(self.folder,research_runner=self.runner,paper_runner=fail,clock=lambda:CUTOFF,progress=lambda _:None)
        state={"initialized":True,"state":{"strategy":{"positions":{},"pending":[]}}}
        result=run_daily(self.folder,research_runner=self.runner,paper_runner=lambda *a,**k:state,
                         clock=lambda:CUTOFF+timedelta(seconds=1),progress=lambda _:None)
        self.assertEqual(result["status"]["state"],"ready")
        self.assertEqual(ResearchHistory(self.folder).list()["total"],1)

    def test_history_integrity_checked_on_read(self):
        save_research(self.folder,self.r)
        with closing(sqlite3.connect(self.folder/"research-history.sqlite3")) as conn, conn:
            conn.execute("DROP TRIGGER reports_no_update")
            conn.execute("UPDATE reports SET payload_sha='bad'")
        with self.assertRaisesRegex(ValidationError,"integrity"):ResearchHistory(self.folder).list()


class HTTPAndScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.server=make_server(self.folder/"runs.sqlite3",self.folder/"paper.sqlite3",port=0)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def get(self,path):
        conn=HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        try:
            conn.request("GET",path)
            response=conn.getresponse()
            return response.status,response.read().decode()
        finally:conn.close()

    def test_new_pages_on_empty_install_do_not_create_databases(self):
        for path in ("/research-history","/api/research-history","/forward","/api/forward","/forward.csv","/api/automation"):
            with self.subTest(path=path):self.assertEqual(self.get(path)[0],200)
        self.assertEqual(list(self.folder.glob("*.sqlite3")),[])

    def test_paper_http_equity_and_csv_match_persistent_records(self):
        sessions,cal=fixture();now=stamp(sessions[0]);r=report(sessions[0])
        ledger=ForwardLedger(self.folder/"forward.sqlite3")
        ledger.initialize(r,cal,now=now)
        ledger.update(r,cal,[snapshot(sessions[0])],actions(sessions,now),now=now)
        now=stamp(sessions[1])
        ledger.update(report(sessions[1]),cal,[snapshot(sessions[1])],actions(sessions,now),now=now)
        code,body=self.get("/api/forward")
        self.assertEqual(code,200)
        self.assertEqual(json.loads(body),ledger.status())
        self.assertIn("99961.98",self.get("/forward.csv")[1])
        self.assertIn("Forward paper evaluation",self.get("/forward")[1])

    def test_workflow_error_is_escaped_in_viewer(self):
        write_json(self.folder/"automation/status.json",{"state":"failed","phase":"paper","error":"<script>alert(1)</script>"})
        html=self.get("/forward")[1]
        self.assertNotIn("<script>",html);self.assertIn("&lt;script&gt;",html)

    def test_invalid_history_offset_is_rejected(self):
        self.assertEqual(self.get("/api/research-history?offset=-5")[0],503)

    def test_cli_preserves_legacy_commands_and_exposes_new_workflow(self):
        self.assertEqual(parser().parse_args(["daily"]).command,"daily")
        args=parser().parse_args(["auto-daily","--no-paper","--max-filings","12"])
        self.assertTrue(args.no_paper);self.assertEqual(args.max_filings,12)
        self.assertEqual(parser().parse_args(["schedule-install"]).command,"schedule-install")

    def test_scheduler_is_current_user_without_elevation_or_password(self):
        from oraculum import local_schedule
        result=SimpleNamespace(returncode=0,stdout='{"installed":true}',stderr="")
        with patch.object(local_schedule,"os",SimpleNamespace(name="nt",environ={})), patch.object(local_schedule.subprocess,"run",return_value=result) as run:
            self.assertTrue(schedule("install",project=self.folder)["installed"])
        args,kwargs=run.call_args
        self.assertEqual(args[0][0],"powershell.exe")
        script=args[0][-1]
        self.assertIn("-LogonType Interactive -RunLevel Limited",script)
        self.assertIn("-MultipleInstances IgnoreNew",script)
        self.assertNotIn("ExecutionPolicy",script)
        self.assertNotIn("-Password",script)
        self.assertEqual(kwargs["env"]["ORACULUM_TASK_ROOT"],str(self.folder.resolve()))

    def test_scheduler_errors_are_returned_without_claiming_installation(self):
        from oraculum import local_schedule
        result=SimpleNamespace(returncode=1,stdout="",stderr="Access denied")
        with patch.object(local_schedule,"os",SimpleNamespace(name="nt",environ={})), patch.object(local_schedule.subprocess,"run",return_value=result):
            with self.assertRaisesRegex(ValidationError,"Access denied"):schedule("install",project=self.folder)
