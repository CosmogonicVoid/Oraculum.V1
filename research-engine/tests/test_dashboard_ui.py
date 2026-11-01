"""UI contracts: whole-universe search, pinned evidence, truthful states and read-only routes."""
from copy import deepcopy
from datetime import timedelta
from html.parser import HTMLParser
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from oraculum.combined_ranking import apply_combined_ranking
from oraculum.contracts import ValidationError, iso
from oraculum.dashboard_view import explore_html, select_assets, stock_html, today_html
from oraculum.forward_paper import ForwardLedger
from oraculum.local_web import make_server
from oraculum.market_research import build_research, save_research
from oraculum.serialization import digest
from oraculum.ui import source_link
from oraculum.workflow_view import equity_chart, forward_html, history_html
from test_combined_forward import actions, fixture, report as paper_report, snapshot, stamp
from test_market_research import CUTOFF, make_tape


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links, self.ids, self.forms, self.active = [], [], [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and "href" in a:
            self.links.append(a["href"])
            if a.get("aria-current") == "page":
                self.active.append(a["href"])
        if tag == "form":
            self.forms.append(a)


def ui_report():
    cal,raw,info,_,_,snaps=make_tape()
    r=build_research(snaps,cal,raw,info,as_of=CUTOFF)
    for a in r["assets"]:
        a["company_name"]="Fictional "+a["symbol"]+" Company"
        a["isin"]="IN0000000001"
        a["adjustment_status"]="no_events_in_traded_tail"
        a["adjustments"]=[]
        a["fundamentals"]={
            "status":"available","basis":"consolidated","industry":"Fixture industry",
            "quarter_end":"2026-06-30",
            "financial_screen":"passes","notes":[],"sources":[],"missing":{},
            "metrics":{name:{"value":value,"source_ids":["fixture-filing"],"available_at":iso(CUTOFF),
                            "formula":"Fictional test calculation","periods":[{"start":"2026-04-01","end":"2026-06-30"}]}
                       for name,value in {"revenue_yoy":.1,"net_margin":.1,"borrowings_to_equity":.5,"roce":.15}.items()}}
        a["fundamentals"]["metrics"].update(annual_pe=None,peer_pe_ratio=None)
    r["fundamental_coverage"]={"statuses":{"available":7},"metrics":{},"pending_documents":0,"downloaded_this_run":0,"failed_this_run":0}
    r["refresh_warnings"]=[]
    r["evidence_sources"]=[]
    r["counts"].update(adjusted_stocks=0,action_blocked=0)
    return apply_combined_ranking(r)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.report=ui_report()

    def test_shortlist_first_has_consistent_nav_and_no_legacy_message(self):
        html=today_html(self.report,now=CUTOFF)
        page=Page(html)
        self.assertEqual(page.active,["/"])
        self.assertEqual(len(page.ids),len(set(page.ids)))
        self.assertLess(html.index("Ranked shortlist"),html.index("Financial coverage is still building"))
        self.assertNotIn("No full-engine runs",html)
        self.assertNotIn("Financial download progress",html)
        self.assertIn("Prices through",html)
        self.assertIn("Report built",html)

    def test_search_covers_stocks_beyond_first_page_and_is_case_insensitive(self):
        base=deepcopy(self.report["assets"][0])
        self.report["assets"]=[]
        for i in range(130):
            a=deepcopy(base);a["symbol"]=f"STOCK{i:03}";a["company_name"]=f"Fixture corporation {i}"
            a["combined"]["rank"]=i+1
            self.report["assets"].append(a)
        selected,total,page,pages=select_assets(self.report,{"q":"Corporation 129"})
        self.assertEqual((total,page,pages),(1,1,1))
        self.assertEqual(selected[0]["symbol"],"STOCK129")
        selected,total,page,pages=select_assets(self.report,{"page":"4"})
        self.assertEqual((len(selected),total,page,pages),(10,130,4,4))

    def test_filters_do_not_mix_incomplete_profiles_with_combined_candidates(self):
        asset=self.report["assets"][0]
        asset["fundamentals"]["status"]="partial"
        asset["combined"].update(rank=None,score=None,candidate=False,highlight=False)
        self.assertNotIn(asset,select_assets(self.report,{"filter":"combined"})[0])
        self.assertIn(asset,select_assets(self.report,{"filter":"partial"})[0])
        self.assertIn(asset,select_assets(self.report,{"filter":"incomplete"})[0])

    def test_filter_and_page_validation(self):
        for query in ({"page":"-1"},{"page":"0"},{"page":"9999999"},{"filter":"<script>"},{"sort":"price"},{"q":"x"*101}):
            with self.subTest(query=query),self.assertRaises(ValidationError):
                select_assets(self.report,query)

    def test_search_form_and_links_pin_the_report_and_escape_input(self):
        html=explore_html(self.report,{"q":'"><script>alert(1)</script>'},now=CUTOFF)
        self.assertNotIn("<script>",html)
        self.assertIn("&lt;script&gt;",html)
        page=Page(html)
        self.assertEqual(page.forms[0]["method"],"get")
        self.assertEqual(page.forms[0]["action"],"/explore")
        self.assertIn(self.report["report_id"],html)
        self.assertIn("No matching stocks",html)

    def test_stock_evidence_is_escaped_and_has_single_header(self):
        a=self.report["assets"][0]
        a["company_name"]="<img src=x onerror=alert(1)>"
        a["warnings"]=["<script>unsafe</script>"]
        html=stock_html(self.report,a,now=CUTOFF)
        self.assertNotIn("<script>",html)
        self.assertNotIn("<img",html)
        self.assertIn("&lt;script&gt;",html)
        self.assertIn("Reporting periods",html)
        self.assertIn("Available to this installation",html)
        self.assertEqual(html.count('id="main"'),1)
        self.assertIn("Score breakdown",html)

    def test_unsafe_evidence_urls_are_not_links(self):
        for uri in ("javascript:alert(1)","data:text/html,test","//example.test","https://[broken"):
            self.assertNotIn("href=",source_link(uri,"Filing"))
        self.assertIn('href="https://example.test/source"',source_link("https://example.test/source","Filing"))

    def test_archived_report_is_labelled_without_claiming_a_new_update_failed(self):
        html=today_html(self.report,{"state":"failed","error":"New run failed"},archived=True,now=CUTOFF)
        self.assertIn("Archived report",html)
        self.assertNotIn("New run failed",html)
        self.assertEqual(Page(html).active,["/research-history"])

    def test_legacy_report_does_not_manufacture_combined_scores(self):
        r=deepcopy(self.report);r.pop("ranking_policy")
        for a in r["assets"]:
            a.pop("combined")
        html=today_html(r,now=CUTOFF)
        self.assertIn("predates combined ranking",html)
        self.assertIn("Explore technical results",html)

    def test_history_version_changes_are_not_called_strategy_changes(self):
        base={"report_id":"a"*64,"session":"2026-10-14","as_of":iso(CUTOFF),"algorithm":"nse-combined-v1",
              "counts":{"combined_eligible":1},"combined_highlights":["NSE:UP"]}
        old=deepcopy(base);old.update(report_id="b"*64,algorithm="nse-price-watchlist-v1")
        html=history_html({"total":2,"items":[base,old],"next_offset":None})
        self.assertIn("Ranking version changed",html)
        self.assertIn("Combined research · v1",html)

    def test_chart_does_not_draw_through_missing_observations(self):
        curve=[{"session":f"2026-10-{i+10}","return":v,"benchmark_return":None}
               for i,v in enumerate((.01,.02,None,.03,.04))]
        html=equity_chart(curve)
        self.assertEqual(html.count("<polyline"),2)
        self.assertNotIn("nan",html)
        self.assertNotIn("<svg",equity_chart(curve[:1]))

    def test_paper_pending_entries_are_separate_from_executed_holdings(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions,cal=fixture();now=stamp(sessions[0]);r=paper_report(sessions[0])
            ledger=ForwardLedger(Path(tmp)/"forward.sqlite3")
            ledger.initialize(r,cal,now=now)
            status=ledger.update(r,cal,[snapshot(sessions[0])],actions(sessions,now),now=now)
            html=forward_html(status)
            self.assertIn("No executed holdings",html)
            self.assertIn("Pending entries",html)
            self.assertIn("Not available yet",html)
            self.assertNotIn('<svg class="chart"',html)
            self.assertEqual(Page(html).active,["/sandbox", "/forward"])


class DashboardHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.server=make_server(self.folder/"runs.sqlite3",self.folder/"paper.sqlite3",port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def get(self,path,headers=None):
        conn=HTTPConnection("127.0.0.1",self.server.server_port,timeout=10)
        try:
            conn.request("GET",path,headers=headers or {})
            r=conn.getresponse()
            return r.status,r.read().decode(),dict(r.getheaders())
        finally:
            conn.close()

    def test_empty_routes_are_read_only_and_stock_not_found_is_404(self):
        for route in ("/","/explore","/system","/forward","/research-history","/history","/advanced"):
            code,html,headers=self.get(route)
            self.assertEqual(code,200,route)
            self.assertIn("Main navigation",html)
            self.assertIn("default-src 'none'",headers["Content-Security-Policy"])
        self.assertEqual(self.get("/stock?symbol=MISSING")[0],404)
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_old_history_bookmark_opens_daily_history_and_manual_area_is_separate(self):
        self.assertIn("Research history",self.get("/history")[1])
        self.assertIn("earlier manual engine",self.get("/advanced")[1])

    def test_live_routes_pin_old_report_and_do_not_touch_data(self):
        old=ui_report();save_research(self.folder,old)
        new=deepcopy(old);new["as_of"]=iso(CUTOFF+timedelta(minutes=1))
        new["report_id"]=digest({k:v for k,v in new.items() if k!="report_id"})
        save_research(self.folder,new)
        # Legacy corrupt databases must not prevent access to the new daily UI.
        (self.folder/"runs.sqlite3").write_bytes(b"old unavailable database")
        (self.folder/"paper.sqlite3").write_bytes(b"old unavailable database")
        before={str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob("*") if p.is_file()}
        for route in ("/","/explore","/system","/history","/forward",
                      "/stock?"+urlencode({"report":old["report_id"],"symbol":old["assets"][0]["symbol"]}),
                      "/explore?"+urlencode({"report":old["report_id"],"q":old["assets"][0]["symbol"]})):
            code,html,_=self.get(route)
            self.assertEqual(code,200,route)
            if "report=" in route:
                self.assertIn("Archived report",html)
                self.assertIn(old["report_id"],html)
        after={str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob("*") if p.is_file()}
        self.assertEqual(before,after)

    def test_invalid_queries_unknown_stock_and_cross_origin_requests_are_rejected(self):
        r=ui_report();save_research(self.folder,r)
        for route in ("/explore?page=-1","/explore?filter=bad","/system?report=../../secret"):
            self.assertEqual(self.get(route)[0],503)
        self.assertEqual(self.get("/stock?symbol=MISSING")[0],404)
        self.assertEqual(self.get("/explore",{"Origin":"https://evil.example"})[0],403)
        self.assertEqual(self.get("/explore",{"Sec-Fetch-Site":"cross-site"})[0],403)


if __name__ == "__main__":
    unittest.main()
