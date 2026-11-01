"""Real cache fixtures (synthetic prices), confirmed manual trades and HTTP boundaries."""
from copy import deepcopy
from datetime import datetime
from html.parser import HTMLParser
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
from test_market_research import make_tape, CUTOFF
from test_dashboard_ui import ui_report
from oraculum.contracts import ValidationError
from oraculum.local_data import MarketStore
from oraculum.market_research import build_research, save_research
from oraculum import stock_chart, demo_trading as demo
from oraculum.local_web import make_server

class ChartTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        cal,raw,info,sessions,files,_=make_tape()
        cache=MarketStore(self.folder/'market.sqlite3')
        snaps=[cache.ingest(files[s],s,'https://example.test/data',received_at=CUTOFF) for s in sessions]
        self.report=build_research(snaps,cal,raw,info,as_of=CUTOFF)
    def asset(self,symbol):return next(a for a in self.report['assets'] if a['symbol']==symbol)
    def test_exact_prices_volume_and_moving_averages(self):
        data=stock_chart.series(self.folder,self.report,self.asset('UP'));rows=data['rows']
        self.assertEqual(float(rows[-1]['close']),159);self.assertEqual(rows[-1]['volume'],3000000)
        self.assertEqual(rows[-1]['ma20'],149.5);self.assertEqual(rows[-1]['ma50'],134.5)
        self.assertIsNone(rows[18]['ma20']);self.assertIsNone(rows[48]['ma50'])
    def test_gap_breaks_average_and_chart_line(self):
        data=stock_chart.series(self.folder,self.report,self.asset('GAPPED'))
        self.assertEqual(data['missing'],1);self.assertIsNone(data['rows'][-1]['ma20'])
        self.assertNotIn('close',data['rows'][55])
        html=stock_chart.panel(data,self.report,self.asset('GAPPED'),kind='line')
        self.assertIn('Missing sessions',html)
        self.assertGreaterEqual(html.count('<polyline'),2)
    def test_receipt_mismatch_rejected(self):
        self.report['sources'][0]['sha256']='a'*64
        with self.assertRaises(ValidationError):stock_chart.series(self.folder,self.report,self.asset('UP'))
    def test_missing_cache_is_empty_not_fabricated(self):
        result=stock_chart.series(self.folder/'absent',self.report,self.asset('UP'))
        self.assertEqual(result['rows'],[]);self.assertFalse((self.folder/'absent').exists())
    def test_controls_preserve_report_and_limit_rows(self):
        data=stock_chart.series(self.folder,self.report,self.asset('UP'))
        html=stock_chart.panel(data,self.report,self.asset('UP'),period='20')
        self.assertIn('20 observations in 20 saved sessions',html)
        self.assertIn('report='+self.report['report_id'],html)
        self.assertIn('Raw prices are not split/dividend adjusted',html)
        with self.assertRaises(ValidationError):stock_chart.panel(data,self.report,self.asset('UP'),period='bad')

class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.report=ui_report();self.symbol=self.report['assets'][0]['symbol'];self.report['assets'][0]['metrics']['close_inr']=100
    def q(self,side='buy',qty='10'):
        return demo.quote(self.report,self.symbol,side,qty,demo.state(self.folder)['revision'])
    def test_read_does_not_create_account(self):
        self.assertEqual(demo.state(self.folder)['cash'],10000000);self.assertEqual(list(self.folder.iterdir()),[])
    def test_buy_sell_and_realized_cost_basis(self):
        demo.execute(self.folder,self.q(),self.report)
        self.assertEqual(demo.state(self.folder)['cash'],9900000)
        self.report['assets'][0]['metrics']['close_inr']=120
        demo.execute(self.folder,self.q('sell','4'),self.report)
        account=demo.state(self.folder)
        self.assertEqual(account['realized'],8000);self.assertEqual(account['positions'][self.symbol],{'quantity':6,'basis':60000})
        demo.execute(self.folder,self.q('sell','6'),self.report)
        self.assertEqual(demo.state(self.folder)['positions'],{})
        self.assertEqual(demo.state(self.folder)['realized'],20000)
    def test_insufficient_cash_and_short_selling_rejected(self):
        for q in (self.q('buy','1001'),self.q('sell','1')):
            with self.assertRaises(ValidationError):demo.execute(self.folder,q,self.report)
        self.assertFalse((self.folder/'manual_demo.sqlite3').exists())
    def test_duplicate_confirmation_is_idempotent(self):
        q=self.q();self.assertTrue(demo.execute(self.folder,q,self.report));self.assertFalse(demo.execute(self.folder,q,self.report))
        self.assertEqual(len(demo.state(self.folder)['trades']),1)
    def test_concurrent_stale_preview_rejected(self):
        a,b=self.q(),self.q();demo.execute(self.folder,a,self.report)
        with self.assertRaises(ValidationError):demo.execute(self.folder,b,self.report)
    def test_changed_report_price_rejected(self):
        q=self.q();self.report['assets'][0]['metrics']['close_inr']=101
        with self.assertRaises(ValidationError):demo.execute(self.folder,q,self.report)
    def test_signature_tampering_and_expiration(self):
        q=self.q();token=demo.sign(q,b'secret');self.assertEqual(demo.verify(token,b'secret'),q)
        with self.assertRaises(ValidationError):demo.verify(token+'a',b'secret')
        q['expires']=0
        with self.assertRaises(ValidationError):demo.verify(demo.sign(q,b'secret'),b'secret')
    def test_invalid_quantity_and_zero_price(self):
        for value in ('0','-1','1.5','1000001','abc'):
            with self.assertRaises(ValidationError):self.q(qty=value)
        for value in (0,-1,'NaN','0.001'):
            with self.assertRaises(ValidationError):demo.paise(value)
    def test_separate_file_preserves_strategy_and_model_settings(self):
        for name in ('forward.sqlite3','ai-settings.json'):(self.folder/name).write_bytes(b'untouched')
        demo.execute(self.folder,self.q(),self.report)
        for name in ('forward.sqlite3','ai-settings.json'):self.assertEqual((self.folder/name).read_bytes(),b'untouched')

class Inputs(HTMLParser):
    def __init__(self,body):super().__init__();self.values={};self.feed(body)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='input' and a.get('type')=='hidden':self.values[a['name']]=a.get('value','')

class HTTPDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.report=ui_report();save_research(self.folder,self.report)
        self.server=make_server(self.folder/'runs.sqlite3',self.folder/'paper.sqlite3',port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,fields=None,headers=None):
        c=HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        h={'Origin':f'http://127.0.0.1:{self.server.server_port}','Content-Type':'application/x-www-form-urlencoded'}
        if headers:h.update(headers)
        try:
            c.request('POST' if fields is not None else 'GET',path,urlencode(fields) if fields is not None else None,h)
            res=c.getresponse();return res.status,res.read().decode()
        finally:c.close()
    def test_preview_confirm_and_duplicate_refresh(self):
        status,body=self.request('/sandbox');self.assertEqual(status,200)
        csrf=Inputs(body).values['csrf'];self.assertFalse((self.folder/'manual_demo.sqlite3').exists())
        fields={'csrf':csrf,'symbol':self.report['assets'][0]['symbol'],'side':'buy','quantity':'1'}
        status,body=self.request('/sandbox/preview',fields);self.assertEqual(status,200)
        self.assertFalse((self.folder/'manual_demo.sqlite3').exists())
        confirmation=Inputs(body).values
        self.assertEqual(self.request('/sandbox/confirm',{'csrf':csrf,'quote':confirmation['quote']})[0],303)
        self.assertEqual(self.request('/sandbox/confirm',{'csrf':csrf,'quote':confirmation['quote']})[0],303)
        self.assertEqual(len(demo.state(self.folder)['trades']),1)
    def test_cross_origin_and_bad_token_rejected(self):
        self.assertEqual(self.request('/sandbox/preview',{'csrf':'bad'})[0],403)
        self.assertEqual(self.request('/sandbox/preview',{}, {'Origin':'https://evil.test'})[0],403)
        self.assertEqual(self.request('/sandbox/preview',{}, {'Host':'evil.test'})[0],403)
        self.assertFalse((self.folder/'manual_demo.sqlite3').exists())
    def test_get_cannot_trade_and_unknown_posts_remain_disabled(self):
        self.assertEqual(self.request('/sandbox/confirm')[0],404)
        self.assertEqual(self.request('/api/research/latest',{})[0],501)
