"""Feed boundaries, identity ambiguity, point-in-time records and local integration."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from xml.sax.saxutils import escape

from oraculum.contracts import UTC, ValidationError, iso
from oraculum.event_sources import (CompanyMatcher, FEEDS, FeedRedirect, MAX_BYTES, feed_url,
    parse_feed, plain, published_time, safe_url)
from oraculum.event_store import EventStore
from oraculum.events_view import news_csv, news_html
from oraculum.local import parser
from oraculum.local_web import make_server
from oraculum.market_events import collect_report_events, event_status, refresh_events, report_events
from oraculum.market_research import save_research
from oraculum.serialization import digest
from test_dashboard_ui import Page, ui_report

NOW = datetime(2026,10,17,18,0,tzinfo=UTC)
ASSETS = [
    {"symbol":"ORCHID","company_name":"Orchid Industries Limited","isin":"IN0000000001"},
    {"symbol":"BANKINDIA","company_name":"Bank of India Limited","isin":"IN0000000002"},
    {"symbol":"STATEBANK","company_name":"State Bank of India Limited","isin":"IN0000000003"},
    {"symbol":"IDEA","company_name":"Fictional Telecom Limited","isin":"IN0000000004"},
]
NSE, BOARD, ET = FEEDS


def rss(title="Orchid Industries reports quarterly results", url="https://economictimes.indiatimes.com/story.cms", published="Sat, 17 Oct 2026 17:00:00 +0000", excerpt="", guid=""):
    return ('<rss version="2.0"><channel><title>Fictional test feed</title><item><title>'+escape(title)+'</title><description>'+escape(excerpt)+'</description><link>'+escape(url)+'</link><guid>'+escape(guid)+'</guid><pubDate>'+escape(published)+'</pubDate></item></channel></rss>').encode()


def announcement(**changes):
    row={"seq_id":"fixture-1", "symbol":"ORCHID", "sm_isin":"IN0000000001", "sm_name":"Orchid Industries Limited", "desc":"Results", "attchmntText":"Fictional quarterly results.", "attchmntFile":"https://nsearchives.nseindia.com/corporate/fictional.pdf", "an_dt":"17-Oct-2026 21:00:00", "exchdisstime":"17-Oct-2026 21:00:01"}
    row.update(changes)
    return json.dumps([row]).encode()


class FeedParsingTests(unittest.TestCase):
    def test_rss_html_is_plain_text_and_time_normalized(self):
        items,counts=parse_feed(rss(title="Orchid <b>Industries</b>",excerpt="<script>BAD</script><p>A &amp; B</p>"),ET)
        self.assertEqual(items[0]["title"],"Orchid Industries")
        self.assertEqual(items[0]["excerpt"],"A & B")
        self.assertEqual(items[0]["published_at"],"2026-10-17T17:00:00Z")
        self.assertEqual(counts["skipped"],0)

    def test_atom_prefers_publication_and_alternate_link(self):
        raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Fictional news</title><published>2026-10-17T17:00:00Z</published><updated>2026-10-18T17:00:00Z</updated><link rel="self" href="https://bad.test"/><link rel="alternate" href="https://economictimes.indiatimes.com/news.cms"/></entry></feed>'
        rows,_=parse_feed(raw,ET)
        self.assertEqual(rows[0]["published_at"],"2026-10-17T17:00:00Z")
        self.assertTrue(rows[0]["url"].endswith("news.cms"))

    def test_official_exchange_dissemination_time_is_used(self):
        row=parse_feed(announcement(),NSE)[0][0]
        self.assertEqual(row["published_at"],"2026-10-17T15:30:01Z")
        self.assertEqual(row["reported_isin"],"IN0000000001")

    def test_missing_and_ambiguous_publication_remain_unknown(self):
        for value in ("", "not a date", "2026-10-17", "2026-10-17T17:00:00"):
            with self.subTest(value=value):
                self.assertIsNone(published_time(value))
        self.assertEqual(published_time("2026-10-17 17:00:00",nse=True),"2026-10-17T11:30:00Z")

    def test_xml_entities_html_error_pages_and_limits_are_rejected(self):
        for raw in (b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss><channel/></rss>', b'<html>Blocked</html>', b'<rss>', b'\x00<rss/>', b'x'*(MAX_BYTES+1)):
            with self.subTest(raw=raw[:30]),self.assertRaises(ValidationError):parse_feed(raw,ET)

    def test_empty_feed_is_valid_but_all_bad_items_are_an_error(self):
        self.assertEqual(parse_feed(b'<rss><channel/></rss>',ET)[1]["accepted"],0)
        with self.assertRaisesRegex(ValidationError,"All feed items"):
            parse_feed(rss(url="javascript:alert(1)"),ET)
        with self.assertRaises(ValidationError):parse_feed(b'{"blocked":true}',NSE)

    def test_source_url_rejects_credentials_ports_local_and_script(self):
        for url in ("http://economictimes.indiatimes.com/a", "https://user@economictimes.indiatimes.com/a", "https://economictimes.indiatimes.com:8443/a", "https://127.0.0.1/a", "javascript:bad", "https://economictimes.indiatimes.com.evil.test/a", "https://economictimes.indiatimes.com/\nx"):
            with self.subTest(url=url),self.assertRaises(ValidationError):safe_url(url,{ET["host"]})

    def test_cross_host_redirect_is_rejected_before_follow(self):
        with self.assertRaises(ValidationError):
            FeedRedirect(ET["host"]).redirect_request(None,None,302,"Found",{},"https://localhost/private")

    def test_tracking_is_removed_without_removing_article_identity(self):
        url=safe_url('https://economictimes.indiatimes.com/story?id=123&utm_source=a#top',{ET["host"]})
        self.assertEqual(url,'https://economictimes.indiatimes.com/story?id=123')

    def test_announcement_window_is_seven_ist_dates(self):
        self.assertIn('from_date=11-10-2026&to_date=17-10-2026',feed_url(NSE,NOW))
        self.assertIn('from_date=12-10-2026&to_date=18-10-2026',feed_url(NSE,NOW+timedelta(hours=1)))

    def test_plain_text_limits_and_malformed_html_are_safe(self):
        self.assertEqual(len(plain('a'*10000,400)),400)
        self.assertNotIn('<',plain('<b>Hello</b>'))


class MatchingTests(unittest.TestCase):
    def setUp(self):self.matcher=CompanyMatcher(ASSETS)

    def news(self,title):return parse_feed(rss(title=title),ET)[0][0]

    def test_exchange_symbol_and_isin_must_agree(self):
        good=parse_feed(announcement(),NSE)[0][0]
        self.assertEqual(self.matcher.match(good)[0][0]["method"],"exchange_symbol_and_isin")
        bad=parse_feed(announcement(sm_isin="IN9999999999"),NSE)[0][0]
        self.assertEqual(self.matcher.match(bad),([],"identity_conflict"))

    def test_unknown_old_symbol_can_join_unique_isin(self):
        old=parse_feed(announcement(symbol="OLDORCHID"),NSE)[0][0]
        matches,state=self.matcher.match(old)
        self.assertEqual(matches[0]["symbol"],"ORCHID")
        self.assertEqual(matches[0]["method"],"exchange_isin")

    def test_missing_exchange_isin_does_not_fall_back_to_name_guess(self):
        self.assertEqual(self.matcher.match(parse_feed(announcement(sm_isin=None),NSE)[0][0])[1],"unverified_exchange_identity")

    def test_longest_company_name_does_not_match_substring_company(self):
        matches,_=self.matcher.match(self.news("State Bank of India announces results"))
        self.assertEqual([m["symbol"] for m in matches],["STATEBANK"])

    def test_bare_common_ticker_is_not_assigned(self):
        self.assertEqual(self.matcher.match(self.news("An IDEA for the market rally")),([],"unmatched"))
        self.assertEqual(self.matcher.match(self.news("NSE:IDEA releases results"))[0][0]["symbol"],"IDEA")

    def test_multicompany_news_and_word_boundaries(self):
        self.assertEqual(len(self.matcher.match(self.news("Orchid Industries and Bank of India results"))[0]),2)
        self.assertEqual(self.matcher.match(self.news("SuperOrchid Industries release"))[1],"unmatched")

    def test_ambiguous_names_are_not_assigned(self):
        matcher=CompanyMatcher([*ASSETS,{"symbol":"OTHER","company_name":"Orchid Industries Limited","isin":"IN9999999999"}])
        self.assertEqual(matcher.match(self.news("Orchid Industries results")),([],"unmatched"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.store=EventStore(self.folder/'events.sqlite3')

    def put(self,raw=None,when=NOW,feed=ET,assets=ASSETS):
        return self.store.ingest(raw or rss(),feed,feed_url(feed,when),assets,received_at=when)

    def test_read_only_empty_store_does_not_create_files(self):
        self.assertEqual(self.store.query(as_of=NOW)["total"],0)
        self.assertEqual(self.store.states(),{})
        self.assertFalse(self.store.path.exists())

    def test_repeat_and_tracking_duplicates_produce_one_event(self):
        self.put();self.put(rss(url='https://economictimes.indiatimes.com/story.cms?utm_medium=x',guid='changed'),when=NOW+timedelta(hours=1))
        self.assertEqual(self.store.query(as_of=NOW+timedelta(hours=2))["total"],1)
        self.assertEqual(self.store.audit(),{"receipts":2,"revisions":1})

    def test_revisions_preserve_original_cutoff_and_first_receipt(self):
        self.put();cursor=self.store.cursor()
        self.put(rss(title='Orchid Industries corrects results'),when=NOW+timedelta(hours=1))
        first=self.store.query(as_of=NOW)["items"][0]
        revised=self.store.query(as_of=NOW+timedelta(hours=2))["items"][0]
        self.assertNotEqual(first["title"],revised["title"])
        self.assertEqual(first["first_seen_at"],revised["first_seen_at"])
        self.assertEqual(self.store.query(as_of=NOW+timedelta(hours=2),cursor=cursor)["items"][0]["title"],first["title"])

    def test_backfilled_article_cannot_appear_before_actual_receipt(self):
        self.put(rss(published='Fri, 16 Oct 2026 10:00:00 +0000'))
        self.assertEqual(self.store.query(as_of=NOW-timedelta(microseconds=1))["total"],0)
        self.assertEqual(self.store.query(as_of=NOW)["total"],1)

    def test_fractional_second_cutoffs_are_exact(self):
        t=NOW+timedelta(microseconds=1);self.put(when=t)
        self.assertEqual(self.store.query(as_of=NOW)["total"],0)
        self.assertEqual(self.store.query(as_of=t)["total"],1)

    def test_missing_dates_remain_visible_and_future_dates_wait(self):
        self.put(rss(published=''))
        unknown=self.store.query(as_of=NOW)["items"][0]
        self.assertIsNone(unknown["published_at"])
        self.assertEqual(unknown["timing"],"publication_unknown")
        self.put(rss(url='https://economictimes.indiatimes.com/future.cms',published='Sun, 18 Oct 2026 10:00:00 +0000'))
        self.assertEqual(self.store.query(as_of=NOW)["total"],1)

    def test_identity_filter_rejects_reused_symbol(self):
        self.put()
        self.assertEqual(self.store.query(as_of=NOW,symbol='ORCHID',isin='IN9999999999')["total"],0)
        self.assertEqual(self.store.query(as_of=NOW,symbol='ORCHID',isin='IN0000000001')["total"],1)

    def test_changed_match_does_not_leak_old_revision(self):
        self.put();self.put(rss(title='Market overview'),when=NOW+timedelta(hours=1))
        self.assertEqual(self.store.query(as_of=NOW+timedelta(hours=2),symbol='ORCHID')["total"],0)
        self.assertEqual(self.store.query(as_of=NOW,symbol='ORCHID')["total"],1)

    def test_store_is_append_only_and_payload_tampering_detected(self):
        self.put()
        with closing(sqlite3.connect(self.store.path)) as db, db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM events')
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE receipts SET sha256="bad"')
            db.execute('DROP TRIGGER events_no_update');db.execute('UPDATE events SET checksum="bad"')
        with self.assertRaisesRegex(ValidationError,'integrity'):self.store.query(as_of=NOW)

    def test_backwards_system_clock_rejected_atomically(self):
        self.put()
        with self.assertRaisesRegex(ValidationError,'backwards'):self.put(when=NOW-timedelta(seconds=1))
        self.assertEqual(self.store.audit()["receipts"],1)

    def test_pagination_filters_search_and_query_validation(self):
        self.put();self.put(rss(title='Other news',url='https://economictimes.indiatimes.com/other.cms'))
        page=self.store.query(as_of=NOW,limit=1)
        self.assertEqual(page['next_offset'],1)
        self.assertEqual(self.store.query(as_of=NOW,q='orchid')['total'],1)
        self.assertEqual(self.store.query(as_of=NOW,match='unmatched')['total'],1)
        for kw in ({'offset':-1},{'kind':'bogus'},{'limit':101},{'q':'a'*201}):
            with self.assertRaises(ValidationError):self.store.query(as_of=NOW,**kw)

    def test_offline_and_success_cache_never_fetch(self):
        with patch('oraculum.market_events.download_feed',side_effect=AssertionError('network')):
            self.assertEqual(refresh_events(self.folder,ASSETS,offline=True,clock=lambda:NOW,progress=lambda _:None)['mode'],'offline')
        self.assertFalse(self.store.path.exists())
        refresh_events(self.folder,ASSETS,feeds=(ET,),clock=lambda:NOW,downloader=lambda _:rss(),progress=lambda _:None)
        with patch('oraculum.market_events.download_feed',side_effect=AssertionError('network')):
            refresh_events(self.folder,ASSETS,feeds=(ET,),clock=lambda:NOW+timedelta(hours=1),progress=lambda _:None)
        self.assertEqual(self.store.audit()['receipts'],1)

    def test_denied_provider_cools_down_and_keeps_cached_news(self):
        self.put()
        def denied(_):raise HTTPError('https://economictimes.indiatimes.com',429,'rate limited',{'Retry-After':'172800'},None)
        refresh_events(self.folder,ASSETS,feeds=(ET,),clock=lambda:NOW,downloader=denied,progress=lambda _:None)
        state=self.store.states()[ET['id']]
        self.assertEqual(state['state'],'failed')
        self.assertEqual(state['next_attempt_at'],iso(NOW+timedelta(days=2)))
        self.assertEqual(self.store.query(as_of=NOW)['total'],1)
        with patch('oraculum.market_events.download_feed',side_effect=AssertionError('network')):
            refresh_events(self.folder,ASSETS,feeds=(ET,),clock=lambda:NOW+timedelta(hours=3),progress=lambda _:None)

    def test_one_source_failure_does_not_block_the_other(self):
        def get(url):
            if 'corporate-announcements' in url:raise TimeoutError('fixture timeout')
            return rss()
        result=refresh_events(self.folder,ASSETS,feeds=(NSE,ET),clock=lambda:NOW,downloader=get,progress=lambda _:None)
        self.assertEqual(self.store.states()[NSE['id']]['state'],'failed')
        self.assertEqual(self.store.states()[ET['id']]['state'],'ready')

    def test_bad_news_database_is_nonfatal_for_report_collection(self):
        self.store.path.write_bytes(b'corrupt')
        result=collect_report_events(self.folder,{'assets':ASSETS},offline=True,clock=lambda:NOW,progress=lambda _:None)
        self.assertEqual(result['state'],'unavailable')

    def test_snapshot_rejects_different_event_database(self):
        self.put()
        cov=collect_report_events(self.folder,{'assets':ASSETS},offline=True,clock=lambda:NOW,progress=lambda _:None)
        report={'as_of':iso(NOW),'event_coverage':cov}
        self.assertEqual(report_events(self.folder,report)['total'],1)
        self.store.path.unlink();self.put()
        self.assertIn('unavailable',report_events(self.folder,report)['notice'])

    def test_csv_neutralizes_formula_and_html_escapes_untrusted_text(self):
        self.put(rss(title='=1+1',excerpt='&lt;script&gt;malicious&lt;/script&gt;'))
        result=self.store.query(as_of=NOW)
        self.assertIn("'=1+1",news_csv(result))
        html=news_html(result,event_status(self.folder,now=NOW),{})
        self.assertNotIn('<script>',html)
        self.assertIn('economictimes.indiatimes.com/story.cms',html)
        self.assertEqual(Page(html).active,['/research', '/news'])


class HTTPEventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.server=make_server(self.folder/'runs.sqlite3',self.folder/'paper.sqlite3',port=0)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def get(self,path):
        conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            conn.request('GET',path);r=conn.getresponse();return r.status,r.read().decode()
        finally:conn.close()

    def test_empty_news_pages_are_read_only(self):
        for path in ('/news','/api/news','/news.csv','/system'):
            with self.subTest(path=path):self.assertEqual(self.get(path)[0],200)
        self.assertEqual(list(self.folder.glob('*.sqlite3')),[])

    def test_news_routes_and_archive_stock_snapshot(self):
        report=ui_report();a=report['assets'][0]
        a.update(ASSETS[0]);report['as_of']=iso(NOW)
        store=EventStore(self.folder/'events.sqlite3')
        store.ingest(rss(),ET,feed_url(ET,NOW),report['assets'],received_at=NOW)
        report['event_coverage']=collect_report_events(self.folder,report,offline=True,clock=lambda:NOW,progress=lambda _:None)
        report['report_id']=digest({k:v for k,v in report.items() if k!='report_id'});save_research(self.folder,report)
        store.ingest(rss(title='Orchid Industries correction'),ET,feed_url(ET,NOW),report['assets'],received_at=NOW+timedelta(seconds=1))
        code,body=self.get('/api/news?report='+report['report_id'])
        self.assertEqual(code,200);self.assertNotIn('correction',body)
        code,body=self.get('/stock?symbol=ORCHID&report='+report['report_id'])
        self.assertEqual(code,200);self.assertIn('quarterly results',body);self.assertNotIn('correction',body)
        self.assertIn('revision_checksum',self.get('/news.csv')[1])

    def test_bad_filters_do_not_leak_sql_or_create_files(self):
        for path in ('/news?offset=-1','/news?kind=invalid','/news?report=../../file','/api/news?offset=999999999999'):
            with self.subTest(path=path):self.assertEqual(self.get(path)[0],503)
        self.assertFalse((self.folder/'events.sqlite3').exists())

    def test_cli_news_commands_are_available(self):
        self.assertTrue(parser().parse_args(['news-refresh','--offline']).offline)
        self.assertTrue(parser().parse_args(['news-status','--audit']).audit)


class WorkflowEventIntegrationTests(unittest.TestCase):
    def test_report_capture_preserves_scores_and_paper_policy(self):
        from oraculum.market_research import run_research
        from test_market_research import make_tape, CUTOFF
        cal,raw,info,_,files,snaps=make_tape()
        # The fixture downloader returns the deterministic final price files.
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            baseline=run_research(base,downloader=lambda d:(files[d],'https://example.test/prices'),clock=lambda:CUTOFF,pause=lambda _:None,progress=lambda _:None)
            with patch('oraculum.market_events.refresh_events',return_value={'sources':[], 'cursor':0,'store_identity':None,'mode':'offline'}):
                report=run_research(base,downloader=lambda d:(files[d],'https://example.test/prices'),clock=lambda:CUTOFF,pause=lambda _:None,progress=lambda _:None,collect_news=True)
            self.assertEqual(report['assets'],baseline['assets'])
            self.assertEqual(report['counts'],baseline['counts'])
            self.assertFalse(report['event_coverage']['scored'])
            self.assertIn('event_coverage',report)
            self.assertEqual(report['report_id'],digest({k:v for k,v in report.items() if k!='report_id'}))
            self.assertEqual(json.loads((base/'research'/(report['report_id']+'.json')).read_text()),report)

    def test_news_collection_failure_does_not_prevent_report_publication(self):
        from oraculum.market_research import run_research
        from test_market_research import make_tape, CUTOFF
        _,_,_,_,files,_=make_tape()
        with tempfile.TemporaryDirectory() as temp:
            with patch('oraculum.market_events.refresh_events',side_effect=sqlite3.DatabaseError('damaged optional news store')):
                report=run_research(Path(temp),downloader=lambda d:(files[d],'https://example.test/prices'),clock=lambda:CUTOFF,pause=lambda _:None,progress=lambda _:None,collect_news=True)
            self.assertEqual(report['event_coverage']['state'],'unavailable')
            self.assertTrue((Path(temp)/'research'/(report['report_id']+'.json')).exists())

    def test_duplicate_ingest_from_threads_does_not_duplicate_records(self):
        with tempfile.TemporaryDirectory() as temp:
            store=EventStore(Path(temp)/'events.sqlite3')
            store.ingest(rss(),ET,feed_url(ET,NOW),ASSETS,received_at=NOW)
            errors=[]
            def job():
                try:store.ingest(rss(),ET,feed_url(ET,NOW),ASSETS,received_at=NOW)
                except Exception as exc:errors.append(exc)
            threads=[threading.Thread(target=job) for _ in range(4)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertFalse(errors)
            self.assertEqual(store.audit(),{'receipts':5,'revisions':1})
