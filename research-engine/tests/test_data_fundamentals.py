"""Synthetic economic/availability invariants; no external network in the suite."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

from oraculum.contracts import IST, UTC, ValidationError, iso, timestamp
from oraculum.corporate_actions import (action_terms, adjusted_series, linked_tail,
                                       parse_actions, rename_chain, symbol_at)
from oraculum.financials import (EPS, METRICS, attach_peer_comparisons, filing_plan, parse_xbrl,
                                profile_from_filings, validate_filing)
from oraculum.integrated_research import build_adjusted, integrate
from oraculum.local_data import MarketStore, parse_bhavcopy
from oraculum.market_research import read_research, report_csv, run_research, save_research
from oraculum.nse_evidence import EvidenceStore, ExchangeRedirect, parse_catalogue, source_url
from oraculum.research_view import research_html
from oraculum.serialization import digest
from tests.test_market_research import CUTOFF, make_tape

URL = 'https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_'
ISIN = 'IN0000000001'


def financial_xml(symbol='UP', end='2026-09-30', start='2026-07-01', basis='Consolidated',
                  revenue=1200, profit=120, assets=1200, liabilities=300, annual=False):
    fiscal_year = int(end[:4]) if end[5:] <= '03-31' else int(end[:4])+1
    fiscal_start = f'{fiscal_year-1}-04-01'
    facts = {'RevenueFromOperations':revenue, 'ProfitLossForPeriod':profit,
             'ProfitBeforeTax':200, 'FinanceCosts':20, EPS:10}
    def fact(tag, value, ctx='q', unit='INR'):
        return f'<i:{tag} contextRef="{ctx}" unitRef="{unit}" decimals="-7">{value}</i:{tag}>'
    ident = {'Symbol':symbol,'ISIN':ISIN,'NatureOfReportStandaloneConsolidated':basis,
             'DateOfStartOfFinancialYear':fiscal_start,'DateOfEndOfFinancialYear':f'{fiscal_year}-03-31',
             'DateOfStartOfReportingPeriod':start,'DateOfEndOfReportingPeriod':end}
    contexts = f'<x:context id="q"><x:entity><x:identifier scheme="test">1</x:identifier></x:entity><x:period><x:startDate>{start}</x:startDate><x:endDate>{end}</x:endDate></x:period></x:context>'
    contexts += f'<x:context id="b"><x:entity><x:identifier scheme="test">1</x:identifier></x:entity><x:period><x:instant>{end}</x:instant></x:period></x:context>'
    xml = f'''<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance" xmlns:i="http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt" xmlns:c="http://www.xbrl.org/2003/iso4217" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{contexts}
    <x:unit id="INR"><x:measure>c:INR</x:measure></x:unit><x:unit id="EPS"><x:divide><x:unitNumerator><x:measure>c:INR</x:measure></x:unitNumerator><x:unitDenominator><x:measure>x:shares</x:measure></x:unitDenominator></x:divide></x:unit>'''
    xml += ''.join(f'<i:{k} contextRef="q">{v}</i:{k}>' for k,v in ident.items())
    xml += ''.join(fact(k,v,unit='EPS' if k==EPS else 'INR') for k,v in facts.items())
    xml += ''.join(fact(k,v,ctx='b') for k,v in {'Assets':assets,'CurrentLiabilities':liabilities,'Equity':600,'BorrowingsCurrent':100,'BorrowingsNoncurrent':200}.items())
    if annual:
        xml += f'<x:context id="a"><x:entity><x:identifier scheme="test">1</x:identifier></x:entity><x:period><x:startDate>{fiscal_start}</x:startDate><x:endDate>{end}</x:endDate></x:period></x:context>'
        xml += ''.join(fact(k,v,ctx='a',unit='EPS' if k==EPS else 'INR') for k,v in facts.items())
    return (xml+'</x:xbrl>').encode()


def evidence(kind, data, key='test', stamp=CUTOFF):
    return {'kind':kind, 'data':data, 'source_id':kind+'-'+digest(data), 'received_at':iso(stamp),
            'sha256':'a'*64, 'uri':'https://nsearchives.nseindia.com/test/'+key}


def record(end, symbol='UP', basis='consolidated', stamp=None):
    published=stamp or datetime.combine(date.fromisoformat(end)+timedelta(days=10),datetime.min.time(),UTC)
    return {'symbol':symbol,'basis':basis,'period_end':end,'url':URL+symbol+'_'+end+'.xml','published_at':iso(published)}


def profile_fixture():
    specs=[('quarter','2026-09-30','2026-07-01',1200,1200,300,False),
           ('year_ago_quarter','2025-09-30','2025-07-01',1000,1000,200,False),
           ('annual','2026-03-31','2026-01-01',4000,1200,300,True),
           ('prior_annual','2025-03-31','2025-01-01',3000,1000,200,True)]
    records={}; available={}
    for role,end,start,revenue,assets,liabilities,annual in specs:
        records[role]=record(end)
        available[role]=evidence('filing',parse_xbrl(financial_xml(end=end,start=start,revenue=revenue,assets=assets,liabilities=liabilities,annual=annual)),key=role)
    plan={'status':'pending','basis':'consolidated','period_end':'2026-09-30','records':records,'notes':[]}
    return plan,available


class ActionTests(unittest.TestCase):
    def tail(self,prices=(100,100,50,51),volumes=(100,100,200,200),symbol='UP'):
        days=[date(2026,10,5)+timedelta(days=i) for i in range(len(prices))]
        return [(d,{'symbol':symbol,'close':str(p),'volume':v,'isin':ISIN}) for d,p,v in zip(days,prices,volumes)],days

    def event(self,subject,ex='2026-10-07',symbol='UP'):
        return {'symbol':symbol,'ex_date':ex,'subject':subject,**action_terms(subject)}

    def test_split_removes_mechanical_jump_and_inversely_adjusts_volume(self):
        tail,days=self.tail()
        saved=deepcopy(tail)
        prices,volumes,blocked,applied=adjusted_series('UP',tail,days,[self.event('Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share')],[])
        self.assertEqual(prices,[Decimal(50),Decimal(50),Decimal(50),Decimal(51)])
        self.assertEqual(volumes,[Decimal(200)]*4)
        self.assertFalse(blocked);self.assertEqual(tail,saved);self.assertEqual(len(applied),1)

    def test_fractional_bonus_volume_is_not_rounded(self):
        tail,days=self.tail(volumes=(101,101,200,200))
        _,volumes,blocked,_=adjusted_series('UP',tail,days,[self.event('Bonus 2:5')],[])
        self.assertEqual(volumes[0],Decimal('141.4'));self.assertFalse(blocked)

    def test_cash_dividend_changes_price_but_not_volume(self):
        tail,days=self.tail(prices=(100,100,97,98))
        p,v,b,_=adjusted_series('UP',tail,days,[self.event('Dividend - Rs 1 Per Share/Special Dividend - 2 Per Share')],[])
        self.assertEqual(p[0],97);self.assertEqual(v[0],100);self.assertFalse(b)

    def test_rights_and_mixed_share_events_block(self):
        tail,days=self.tail()
        for events in ([self.event('Rights 1:2')],[self.event('Bonus 1:1'),self.event('Dividend - Rs 2 Per Share')]):
            with self.subTest(events=events):
                self.assertTrue(adjusted_series('UP',tail,days,events,[])[2])

    def test_dividend_at_least_price_is_blocked(self):
        tail,days=self.tail()
        self.assertTrue(adjusted_series('UP',tail,days,[self.event('Dividend - Rs 100 Per Share')],[])[2])

    def test_future_action_does_not_adjust_past_prices(self):
        tail,days=self.tail()
        p,_,_,a=adjusted_series('UP',tail,days,[self.event('Bonus 1:1',ex='2026-10-09')],[])
        self.assertEqual(p[0],100);self.assertEqual(a,[])

    def test_bad_ratio_and_malformed_feed_fail_closed(self):
        for subject in ('Bonus 0:1','Bonus 1:0','Split From Rs 1.2.3 Per Share To Rs 2 Per Share'):
            self.assertEqual(action_terms(subject)['kind'],'unsupported')
        with self.assertRaises(ValidationError):parse_actions(b'<html>error</html>',date(2026,1,1),date(2026,12,31))
        with self.assertRaises(ValidationError):parse_actions(json.dumps([{'symbol':'UP','series':'EQ','exDate':'01-Jan-2025','subject':'Bonus 1:1'}]).encode(),date(2026,1,1),date(2026,12,31))

    def test_dated_rename_and_isin_change_controls(self):
        tail,days=self.tail()
        changes=[{'old':'OLD','new':'UP','effective':'2026-10-07'}]
        maps={d:{('OLD' if d<days[2] else 'UP'):{**r,'symbol':'OLD' if d<days[2] else 'UP'}} for d,r in tail}
        linked,blocked,warnings=linked_tail('UP',maps,days,changes,[])
        self.assertEqual(len(linked),4);self.assertFalse(blocked);self.assertTrue(warnings)
        maps[days[0]]['OLD']['isin']='IN0000000002'
        self.assertTrue(linked_tail('UP',maps,days,changes,[])[1])
        self.assertEqual(symbol_at('UP',days[0],days[-1],changes),'OLD')

    def test_rename_same_day_old_action_symbol_is_recognized(self):
        tail,days=self.tail()
        tail[0][1]['symbol']=tail[1][1]['symbol']='OLD'
        p,_,b,_=adjusted_series('UP',tail,days,[self.event('Bonus 1:1',symbol='OLD')],[{'old':'OLD','new':'UP','effective':'2026-10-07'}])
        self.assertEqual(p[0],50);self.assertFalse(b)

    def test_conflicting_rename_is_rejected(self):
        rows=[{'old':'A','new':'UP','effective':'2026-01-01'},{'old':'B','new':'UP','effective':'2026-01-01'}]
        with self.assertRaises(ValidationError):rename_chain('UP',date(2026,10,14),{'UP':rows})


class FilingTests(unittest.TestCase):
    def compute(self,plan=None,available=None,**kwargs):
        p,a=profile_fixture()
        args={'close':150,'today':CUTOFF.date(),'symbol':'UP','actions':[],'action_start':date(2025,1,1),'aliases':{'UP'}}|kwargs
        return profile_from_filings(plan or p,a if available is None else available,**args)

    def test_decimals_attribute_is_precision_not_scale(self):
        parsed=parse_xbrl(financial_xml())
        q=next(p for p in parsed['periods'] if p['kind']=='duration')
        self.assertEqual(q['facts']['RevenueFromOperations'],'1200')

    def test_nil_missing_and_real_zero_remain_distinct(self):
        raw=financial_xml().replace(b'<i:BorrowingsCurrent contextRef="b" unitRef="INR" decimals="-7">100</i:BorrowingsCurrent>',b'<i:BorrowingsCurrent contextRef="b" unitRef="INR" xsi:nil="true"/>').replace(b'>200</i:BorrowingsNoncurrent>',b'>0</i:BorrowingsNoncurrent>')
        bs=next(p for p in parse_xbrl(raw)['periods'] if p['kind']=='instant')
        self.assertNotIn('BorrowingsCurrent',bs['facts']);self.assertEqual(bs['facts']['BorrowingsNoncurrent'],'0')

    def test_wrong_units_and_nonfinite_facts_rejected(self):
        for raw in (financial_xml().replace(b'c:INR',b'c:USD'),financial_xml().replace(b'>1200</i:RevenueFromOperations>',b'>NaN</i:RevenueFromOperations>')):
            with self.assertRaises(ValidationError):parse_xbrl(raw)

    def test_entity_declarations_html_and_utf16_are_rejected(self):
        for raw in (b'<!DOCTYPE x [<!ENTITY a "test">]>'+financial_xml(),b'<html>error</html>',financial_xml().decode().encode('utf-16')):
            with self.assertRaises(ValidationError):parse_xbrl(raw)

    def test_conflicting_duplicate_totals_rejected(self):
        raw=financial_xml().replace(b'</x:xbrl>',b'<i:RevenueFromOperations contextRef="q" unitRef="INR">99</i:RevenueFromOperations></x:xbrl>')
        with self.assertRaisesRegex(ValidationError,'Conflicting'):parse_xbrl(raw)

    def test_segment_context_is_ignored(self):
        raw=financial_xml().replace(b'</x:xbrl>',b'<x:context id="seg"><x:entity><x:identifier scheme="test">1</x:identifier><x:segment><i:Other>segment</i:Other></x:segment></x:entity><x:period><x:startDate>2026-07-01</x:startDate><x:endDate>2026-09-30</x:endDate></x:period></x:context><i:RevenueFromOperations contextRef="seg" unitRef="INR">999</i:RevenueFromOperations></x:xbrl>')
        q=next(p for p in parse_xbrl(raw)['periods'] if p['kind']=='duration')
        self.assertEqual(q['facts']['RevenueFromOperations'],'1200')

    def test_symbol_basis_period_and_isin_must_match(self):
        data=parse_xbrl(financial_xml());r=record('2026-09-30')
        for changed,isin in ((r|{'symbol':'OTHER'},ISIN),(r|{'basis':'standalone'},ISIN),(r|{'period_end':'2026-06-30'},ISIN),(r,'IN0000000002')):
            with self.assertRaises(ValidationError):validate_filing(data,changed,isin)

    def test_yoy_margin_debt_roce_and_annual_pe_arithmetic(self):
        p=self.compute();m=p['metrics']
        self.assertAlmostEqual(m['revenue_yoy']['value'],.2)
        self.assertAlmostEqual(m['net_margin']['value'],.1)
        self.assertEqual(m['borrowings_to_equity']['value'],.5)
        self.assertAlmostEqual(m['roce']['value'],220/850)
        self.assertEqual(m['annual_pe']['value'],15)
        self.assertEqual(p['financial_screen'],'passes')

    def test_missing_opening_balance_does_not_fabricate_roce(self):
        p,a=profile_fixture();del a['prior_annual']
        result=self.compute(p,a)
        self.assertIsNone(result['metrics']['roce']);self.assertEqual(result['financial_screen'],'not_assessed')

    def test_negative_profit_allowed_and_not_a_financial_pass(self):
        p,a=profile_fixture()
        for period in a['quarter']['data']['periods']:
            if period['kind']=='duration':period['facts']['ProfitLossForPeriod']='-120'
        result=self.compute(p,a)
        self.assertAlmostEqual(result['metrics']['net_margin']['value'],-.1)
        self.assertEqual(result['financial_screen'],'does_not_pass')

    def test_zero_prior_revenue_does_not_make_infinite_growth(self):
        p,a=profile_fixture()
        for period in a['year_ago_quarter']['data']['periods']:
            if period['kind']=='duration':period['facts']['RevenueFromOperations']='0'
        self.assertIsNone(self.compute(p,a)['metrics']['revenue_yoy'])

    def test_zero_borrowings_is_valid_not_missing(self):
        p,a=profile_fixture()
        for period in a['quarter']['data']['periods']:
            if period['kind']=='instant':period['facts'].update(BorrowingsCurrent='0',BorrowingsNoncurrent='0')
        self.assertEqual(self.compute(p,a)['metrics']['borrowings_to_equity']['value'],0)

    def test_stale_statements_withhold_metrics(self):
        result=self.compute(today=date(2028,1,1))
        self.assertTrue(all(v is None for v in result['metrics'].values()))

    def test_quarter_never_substitutes_for_annual(self):
        p,a=profile_fixture()
        a['annual']['data']['periods']=[v for v in a['annual']['data']['periods'] if v['start']!='2025-04-01']
        result=self.compute(p,a)
        self.assertIsNone(result['metrics']['roce']);self.assertIsNone(result['metrics']['annual_pe'])

    def test_share_action_withholds_pe_but_cash_dividend_does_not(self):
        event={'symbol':'UP','ex_date':'2026-05-01','kind':'bonus'}
        self.assertIsNone(self.compute(actions=[event])['metrics']['annual_pe'])
        self.assertIsNotNone(self.compute(actions=[event|{'kind':'dividend'}])['metrics']['annual_pe'])
        self.assertIsNone(self.compute(action_start=date(2026,4,1))['metrics']['annual_pe'])

    def test_latest_revision_and_consistent_basis_are_selected(self):
        old=record('2026-09-30');new=old|{'url':URL+'revision.xml','published_at':iso(CUTOFF)}
        separate=record('2026-09-30',basis='standalone')
        plan=filing_plan([old,new,separate],{'UP'},as_of=CUTOFF)
        self.assertEqual(plan['records']['quarter']['url'],new['url']);self.assertEqual(plan['basis'],'consolidated')
        future=new|{'published_at':iso(CUTOFF+timedelta(seconds=1))}
        self.assertEqual(filing_plan([old,future],{'UP'},as_of=CUTOFF)['records']['quarter']['url'],old['url'])

    def test_nbfc_schema_not_treated_as_general_indas(self):
        r=record('2026-09-30');r['url']=r['url'].replace('FILING_INDAS','FILING_NBFC_INDAS')
        self.assertEqual(filing_plan([r],{'UP'},as_of=CUTOFF)['status'],'unsupported_schema')

    def test_peer_comparison_requires_five_other_matched_peers(self):
        profiles=[]
        for i in range(6):
            p=self.compute(close=100+i*10);p['industry']='Test industry'
            profiles.append({'symbol':f'S{i}','fundamentals':p})
        attach_peer_comparisons(profiles[:5])
        self.assertIsNone(profiles[0]['fundamentals']['metrics']['peer_pe_ratio'])
        attach_peer_comparisons(profiles)
        m=profiles[0]['fundamentals']['metrics']['peer_pe_ratio']
        self.assertEqual(m['peer_count'],5);self.assertAlmostEqual(m['value'],10/13)
        profiles[5]['fundamentals']['basis']='standalone'
        for p in profiles:p['fundamentals']['metrics']['peer_pe_ratio']=None
        attach_peer_comparisons(profiles)
        self.assertIsNone(profiles[0]['fundamentals']['metrics']['peer_pe_ratio'])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.cache=EvidenceStore(self.folder/'evidence.sqlite3')

    def test_subsecond_cutoff_and_immutable_receipt(self):
        t=CUTOFF.replace(microsecond=500000)
        self.cache.put('test','key',URL+'test.xml',b'raw',{'v':1},received_at=t)
        self.assertIsNone(self.cache.latest('test','key',as_of=CUTOFF))
        a=self.cache.fetch('test','key',URL+'test.xml',lambda _:self.fail('parse'),clock=lambda:t+timedelta(seconds=1),downloader=lambda _:self.fail('network'))
        self.assertEqual(a['received_at'],iso(t))
        with sqlite3.connect(self.cache.path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):conn.execute('UPDATE evidence SET checksum=?',('bad',))

    def test_modified_raw_is_detected_and_offline_missing_is_error(self):
        self.cache.put('test','key',URL+'test.xml',b'raw',{},received_at=CUTOFF)
        with sqlite3.connect(self.cache.path) as conn:
            conn.execute('DROP TRIGGER evidence_no_update');conn.execute("UPDATE evidence SET raw=X'00'")
        with self.assertRaises(ValidationError):self.cache.latest('test','key',as_of=CUTOFF)
        with self.assertRaisesRegex(ValidationError,'Offline'):self.cache.fetch('missing','key',URL+'test.xml',lambda x:{},offline=True,clock=lambda:CUTOFF)

    def test_restricted_https_and_redirect_destinations(self):
        for url in ('http://www.nseindia.com/a','https://evil.test/a','https://user@www.nseindia.com/a','https://www.nseindia.com:abc/a','https://www.nseindia.com/a#fragment'):
            with self.assertRaises(ValidationError):source_url(url)
        with self.assertRaises(ValidationError):ExchangeRedirect().redirect_request(None,None,302,'',{},'http://127.0.0.1/')

    def test_bad_download_never_replaces_evidence(self):
        self.cache.put('test','key',URL+'test.xml',b'old',{'v':1},received_at=CUTOFF-timedelta(days=2))
        def bad(_):raise ValidationError('bad format')
        with self.assertRaises(ValidationError):self.cache.fetch('test','key',URL+'test.xml',bad,clock=lambda:CUTOFF,max_age=timedelta(days=1),downloader=lambda _:b'bad')
        self.assertEqual(self.cache.latest('test','key',as_of=CUTOFF)['data'],{'v':1})

    def test_extended_identifier_view_preserves_original_cache(self):
        _,_,_,sessions,files,_=make_tape();d=sessions[-1]
        raw=files[d].replace(b',UP,EQ,',b',M&M,EQ,')
        store=MarketStore(self.folder/'market.sqlite3');old=store.ingest(raw,d,URL+'prices.csv',received_at=CUTOFF)
        self.assertNotIn('M&M',{r['symbol'] for r in old['rows']})
        extended=store.research_snapshots(start=d,end=d)[0]
        self.assertIn('M&M',{r['symbol'] for r in extended['rows']})
        self.assertEqual(store.snapshots(start=d,end=d)[0],old)
        self.assertEqual(extended['source_id'],old['source_id'])


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar,cls.raw,cls.info,cls.sessions,cls.files,cls.snaps=make_tape()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)

    def adjusted(self,**kwargs):
        actions=evidence('actions',{'coverage_start':str(self.sessions[0]),'coverage_end':str(self.sessions[-1]),'actions':[]})
        args={'actions':actions,'renames':evidence('renames',[]),'master':evidence('master',{})}|kwargs
        return build_adjusted(self.snaps,self.calendar,self.raw,self.info,as_of=CUTOFF,**args)

    def test_adjustment_coverage_and_receipt_are_required(self):
        data={'coverage_start':str(self.sessions[1]),'coverage_end':str(self.sessions[-1]),'actions':[]}
        with self.assertRaisesRegex(ValidationError,'cover'):self.adjusted(actions=evidence('actions',data))
        data['coverage_start']=str(self.sessions[0])
        with self.assertRaisesRegex(ValidationError,'cutoff'):self.adjusted(actions=evidence('actions',data,stamp=CUTOFF+timedelta(seconds=1)))

    def test_economic_split_changes_eligibility_preserving_raw_close(self):
        snaps=deepcopy(self.snaps)
        ex=self.sessions[30]
        for i,s in enumerate(snaps):
            for row in s['rows']:
                if row['symbol']=='FLAT' and i>=30:
                    row.update(open='50',high='51',low='49',close='50',volume=2000000)
        event={'symbol':'FLAT','ex_date':str(ex),'subject':'Bonus 1:1',**action_terms('Bonus 1:1')}
        actions=evidence('actions',{'coverage_start':str(self.sessions[0]),'coverage_end':str(self.sessions[-1]),'actions':[event]})
        r=build_adjusted(snaps,self.calendar,self.raw,self.info,as_of=CUTOFF,actions=actions,renames=evidence('renames',[]),master=evidence('master',{}))
        asset=next(a for a in r['assets'] if a['symbol']=='FLAT')
        self.assertEqual(asset['metrics']['close_inr'],50);self.assertEqual(asset['metrics']['trend_50d'],0)
        self.assertEqual(asset['status'],'eligible');self.assertEqual(asset['metrics']['volume_ratio_20d'],1)

    def test_integrator_failure_preserves_published_report(self):
        args={'downloader':lambda s:(self.files[s],URL+'price.csv'),'clock':lambda:CUTOFF,'pause':lambda _:None,'progress':lambda _:None}
        old=run_research(self.folder,**args)
        def broken(*a,**kw):raise ValidationError('integration failed')
        with self.assertRaises(ValidationError):run_research(self.folder,integrator=broken,**args)
        self.assertEqual(read_research(self.folder)['report_id'],old['report_id'])

    def test_new_schema_csv_html_and_http_reader_roundtrip(self):
        report=self.adjusted();plan,_=profile_fixture()
        from oraculum.financials import empty_profile
        for a in report['assets']:a.update(isin=ISIN,fundamentals=empty_profile(plan))
        report['fundamental_coverage']={'statuses':{'pending':7},'metrics':{m:0 for m in METRICS},'downloaded_this_run':0,'failed_this_run':0,'pending_documents':4}
        report['refresh_warnings']=['<script>unsafe</script>']
        report['report_id']=digest({k:v for k,v in report.items() if k!='report_id'})
        save_research(self.folder,report)
        self.assertEqual(read_research(self.folder),report)
        self.assertIn('annual_pe_periods',report_csv(report))
        html=research_html(report,now=CUTOFF)
        self.assertNotIn('<script>unsafe</script>',html);self.assertIn('&lt;script&gt;',html)
        self.assertIn('Unavailable',html)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
        self.calendar,self.raw,self.info,self.window,_,self.snapshots=make_tape()
        for snapshot in self.snapshots:
            for row in snapshot['rows']:row['isin']=ISIN
        self.store=type('FakeMarket',(),{'research_snapshots':lambda *a,**k:self.snapshots})()
        self.plan,self.available=profile_fixture()
        self.records=list(self.plan['records'].values())
        self.cache=EvidenceStore(self.folder/'evidence.sqlite3')
        today=CUTOFF.astimezone(IST).date()
        start=today-timedelta(days=450)
        from oraculum.nse_evidence import MASTER_URL,RENAMES_URL,actions_url,catalogue_url
        from oraculum.financials import INDUSTRY_URL
        items=[('master','equity',MASTER_URL,{'UP':{'isin':ISIN,'name':'Fixture Up','series':'EQ'}}),
               ('renames','equity',RENAMES_URL,[]),
               ('actions',f'{start}:{today}',actions_url(start,today),{'coverage_start':str(start),'coverage_end':str(today),'actions':[]}),
               ('catalogue',str(today),catalogue_url(today),self.records),
               ('industries','nifty-total-market',INDUSTRY_URL,{'UP':{'isin':ISIN,'industry':'Fixture industry'}})]
        for kind,key,url,data in items:self.cache.put(kind,key,url,b'fixture',data,received_at=CUTOFF)
        self.requested=[]

    def downloader(self,url):
        self.requested.append(url)
        end=next(r['period_end'] for r in self.records if r['url']==url)
        annual=end.endswith('03-31')
        start=end[:4]+('-01-01' if annual else '-07-01')
        return financial_xml(end=end,start=start,annual=annual)

    def run_batch(self,**kwargs):
        return integrate(self.folder,self.store,self.calendar,self.raw,self.info,self.window,
                         clock=lambda:CUTOFF,pause=lambda _:None,progress=lambda _:None,
                         downloader=kwargs.pop('downloader',self.downloader),**kwargs)

    def test_bounded_batch_resumes_and_offline_reuses_receipts(self):
        first=self.run_batch(max_filings=1)
        self.assertEqual(len(self.requested),1);self.assertEqual(first['fundamental_coverage']['pending_documents'],3)
        second=self.run_batch(max_filings=3)
        self.assertEqual(len(self.requested),4);self.assertEqual(len(set(self.requested)),4)
        self.assertEqual(second['fundamental_coverage']['pending_documents'],0)
        third=self.run_batch(offline=True,downloader=lambda _:self.fail('offline network'))
        up=next(a for a in third['assets'] if a['symbol']=='UP')
        self.assertEqual(up['fundamentals']['status'],'available')
        self.assertEqual(third['fundamental_coverage']['downloaded_this_run'],0)
        self.assertTrue(all(timestamp(m['available_at'],'time')<=CUTOFF for m in up['fundamentals']['metrics'].values() if m))

    def test_http_denial_stops_batch_without_retry(self):
        requests=[]
        def denied(url):
            requests.append(url);raise HTTPError(url,403,'Denied',None,None)
        result=self.run_batch(downloader=denied,max_filings=60)
        self.assertEqual(len(requests),1);self.assertEqual(result['fundamental_coverage']['failed_this_run'],1)
        self.assertIn('stopped',result['refresh_warnings'][0])
        self.assertEqual(result['fundamental_coverage']['metrics']['net_margin'],0)

    def test_revision_at_same_url_is_not_satisfied_by_old_cache(self):
        from oraculum.financials import filing_key
        old=self.records[0]
        self.cache.put('filing',filing_key(old),old['url'],financial_xml(),self.available['quarter']['data'],received_at=CUTOFF-timedelta(seconds=1))
        new=old|{'published_at':iso(CUTOFF)}
        records=[new]+self.records[1:]
        from oraculum.nse_evidence import catalogue_url
        self.cache.put('catalogue',str(CUTOFF.date()),catalogue_url(CUTOFF.date()),b'revision',records,received_at=CUTOFF)
        # Same receipt can be ambiguous by hash order; choose a distinct, earlier old catalogue in a fresh DB instead.
        with patch.object(EvidenceStore,'latest',autospec=True,side_effect=self._latest_override(records)):
            result=self.run_batch(max_filings=1)
        self.assertIn(old['url'],self.requested)
        self.assertEqual(result['fundamental_coverage']['downloaded_this_run'],1)

    def _latest_override(self,records):
        original=EvidenceStore.latest
        def get(store,kind,key,*,as_of):
            if kind=='catalogue':return evidence('catalogue',records)
            return original(store,kind,key,as_of=as_of)
        return get

    def test_catalogue_duplicate_url_keeps_latest_publication(self):
        import csv,io
        out=io.StringIO();writer=csv.writer(out)
        writer.writerow(['SYMBOL','QUARTER END DATE','CONSOLIDATED / STANDALONE','XBRL','BROADCAST DATE/TIME','REVISED DATE/TIME','EXCHANGE DISSEMINATION TIME'])
        for published in ('10-Oct-2026 10:00:00','14-Oct-2026 10:00:00'):
            writer.writerow(['UP','30-Sep-2026','Consolidated',URL+'same.xml',published,'-','-'])
        rows=parse_catalogue(out.getvalue().encode())
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['published_at'].startswith('2026-10-14'))


class AdditionalInvariants(unittest.TestCase):
    def test_conflicting_latest_filings_do_not_choose_an_arbitrary_url(self):
        one=record('2026-09-30');two=one|{'url':URL+'different.xml'}
        plan=filing_plan([one,two],{'UP'},as_of=CUTOFF)
        self.assertEqual(plan['status'],'ambiguous_filing');self.assertFalse(plan['records'])
        newer=two|{'published_at':iso(CUTOFF)}
        self.assertEqual(filing_plan([one,two,newer],{'UP'},as_of=CUTOFF)['records']['quarter']['url'],newer['url'])

    def test_conflicting_comparator_is_missing_not_arbitrarily_selected(self):
        latest=record('2026-09-30');old=record('2025-09-30')
        plan=filing_plan([latest,old,old|{'url':URL+'other.xml'}],{'UP'},as_of=CUTOFF)
        self.assertNotIn('year_ago_quarter',plan['records']);self.assertIn('quarter',plan['records'])

    def test_action_with_unrelated_isin_is_blocked(self):
        helper=ActionTests();tail,window=helper.tail()
        action=helper.event('Bonus 1:1')|{'isin':'IN0000000002'}
        prices,_,blocked,applied=adjusted_series('UP',tail,window,[action],[])
        self.assertTrue(blocked);self.assertEqual(applied,[]);self.assertEqual(prices[0],100)

    def test_tiny_financial_number_that_could_overflow_ratio_is_rejected(self):
        raw=financial_xml().replace(b'>1200</i:RevenueFromOperations>',b'>0.'+b'0'*350+b'1</i:RevenueFromOperations>')
        with self.assertRaises(ValidationError):parse_xbrl(raw)

    def test_dated_alias_can_validate_old_filing_but_not_unrelated_identity(self):
        data=parse_xbrl(financial_xml(symbol='OLD'))
        r=record('2026-09-30')
        with self.assertRaises(ValidationError):validate_filing(data,r,ISIN)
        validate_filing(data,r,ISIN,allowed_symbols={'OLD'})
        with self.assertRaises(ValidationError):validate_filing(data,r,'IN0000000002',allowed_symbols={'OLD'})

    def test_separate_same_day_dividend_records_may_be_revisions_not_additive(self):
        helper=ActionTests();tail,window=helper.tail()
        events=[helper.event('Interim Dividend - Re 0.80 Per Share'),helper.event('Interim Dividend - Rs 1.50 Per Share')]
        prices,_,blocked,applied=adjusted_series('UP',tail,window,events,[])
        self.assertTrue(blocked);self.assertFalse(applied);self.assertEqual(prices[0],100)
