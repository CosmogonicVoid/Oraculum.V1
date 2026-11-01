"""Economic and timestamp invariants for milestones 3–5. All prices are fictional."""
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from oraculum.combined_ranking import apply_combined_ranking, combine_asset
from oraculum.contracts import IST, ValidationError, iso
from oraculum.forward_paper import ForwardLedger, POLICY, account, equity, settle_book
from oraculum.serialization import digest


def fixture():
    sessions=[]
    d=date(2026,8,3)
    while len(sessions)<45:
        if d.weekday()<5:
            sessions.append(d)
        d+=timedelta(days=1)
    calendar={s:{"open_at":datetime.combine(s,time(9,15),IST),"close_at":datetime.combine(s,time(16),IST)} for s in sessions}
    return sessions,calendar


def stamp(session):
    return datetime.combine(session,time(19),IST)


def quote(symbol="UP", price="100", opening=None, isin="IN0000000001"):
    return {"symbol":symbol,"isin":isin,"open":opening or price,"close":price,"high":str(Decimal(price)+100),
            "low":"1","volume":1000000,"turnover_inr":"100000000"}


def snapshot(session, *, rows=None):
    return {"session":str(session),"received_at":iso(stamp(session)),"source_id":"fixture-"+str(session),
            "rows":rows if rows is not None else [quote(),quote("NIFTYBEES","200",isin="IN0000000099")]}


def asset(session, symbol="UP", price=100, isin="IN0000000001"):
    metrics={k:{"value":v,"available_at":iso(stamp(session)),"source_ids":["filing-fixture"]}
             for k,v in {"revenue_yoy":.10,"net_margin":.10,"borrowings_to_equity":.5,"roce":.15}.items()}
    return {"symbol":symbol,"instrument_id":"NSE:"+symbol,"isin":isin,"score":80,"status":"eligible",
            "metrics":{"close_inr":price,"momentum_20d":.1,"trend_50d":.1},
            "fundamentals":{"metrics":metrics,"financial_screen":"passes"}}


def report(session, assets=None):
    r={"as_of":iso(stamp(session)),"last_session":str(session),"counts":{},"limitations":["old","old"],
       "assets":assets if assets is not None else [asset(session)]}
    return apply_combined_ranking(r)


def actions(sessions,now,rows=None):
    return {"received_at":iso(now),"source_id":"actions-fixture","data":{"coverage_start":str(sessions[0]),
            "coverage_end":str(sessions[-1]),"actions":rows or []}}


class CombinedTests(unittest.TestCase):
    def setUp(self):
        self.sessions,self.calendar=fixture()
        self.a=asset(self.sessions[0]);self.now=stamp(self.sessions[0])

    def test_independent_arithmetic_and_no_change_to_technical_score(self):
        # 0.6*80 + 0.1*50 + 0.1*50 + 0.1*75 + 0.1*50 = 70.5
        c=combine_asset(self.a,as_of=self.now)
        self.assertAlmostEqual(c["score"],70.5)
        self.assertEqual(c["coverage"],1)
        self.assertEqual(self.a["score"],80)
        self.assertTrue(c["candidate"])

    def test_missing_metric_withholds_score_without_reweighting(self):
        self.a["fundamentals"]["metrics"]["roce"]=None
        c=combine_asset(self.a,as_of=self.now)
        self.assertIsNone(c["score"]);self.assertAlmostEqual(c["coverage"],.9)
        self.assertFalse(c["candidate"])

    def test_future_financial_evidence_cannot_enter_score(self):
        self.a["fundamentals"]["metrics"]["roce"]["available_at"]=iso(self.now+timedelta(seconds=1))
        self.assertIsNone(combine_asset(self.a,as_of=self.now)["score"])

    def test_invalid_negative_leverage_and_nan_are_withheld(self):
        for name,value in (("borrowings_to_equity",-1),("net_margin",float("nan"))):
            with self.subTest(name=name):
                a=deepcopy(self.a);a["fundamentals"]["metrics"][name]["value"]=value
                self.assertIsNone(combine_asset(a,as_of=self.now)["score"])

    def test_technical_exclusion_cannot_be_rescued_by_financials(self):
        self.a.update(score=None,status="excluded")
        self.assertIsNone(combine_asset(self.a,as_of=self.now)["score"])

    def test_failed_financial_screen_is_ranked_but_never_candidate(self):
        self.a["fundamentals"]["financial_screen"]="does_not_pass"
        c=combine_asset(self.a,as_of=self.now)
        self.assertIsNotNone(c["score"]);self.assertFalse(c["candidate"])

    def test_deterministic_ties_and_top_ten(self):
        r=report(self.sessions[0],[asset(self.sessions[0],f"S{i:02}") for i in reversed(range(12))])
        self.assertEqual(r["combined_highlights"],[f"NSE:S{i:02}" for i in range(10)])
        self.assertEqual(r["counts"]["combined_eligible"],12)

    def test_component_clamps_and_no_probability_output(self):
        for name in self.a["fundamentals"]["metrics"]:
            self.a["fundamentals"]["metrics"][name]["value"]=0 if name=="borrowings_to_equity" else 100
        c=combine_asset(self.a,as_of=self.now)
        self.assertAlmostEqual(c["score"],88)
        self.assertTrue(all(0<=f["normalized"]<=100 for f in c["factors"]))
        self.assertNotIn("probability",c)


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ledger=ForwardLedger(Path(self.tmp.name)/"forward.sqlite3")
        self.sessions,self.calendar=fixture()
        self.r=report(self.sessions[0])
        self.ledger.initialize(self.r,self.calendar,now=stamp(self.sessions[0]))

    def update(self,index,*,r=None,snaps=None,event_rows=None):
        now=stamp(self.sessions[index])
        return self.ledger.update(r or report(self.sessions[index]),self.calendar,
            snaps if snaps is not None else [snapshot(s) for s in self.sessions[:index+1]],
            actions(self.sessions,now,event_rows),now=now)

    def enter(self):
        self.update(0)
        return self.update(1)

    def test_decision_is_saved_before_next_open_and_repeat_is_idempotent(self):
        first=self.update(0);again=self.update(0)
        self.assertEqual(first,again)
        self.assertEqual(first["state"]["strategy"]["positions"],{})
        order=first["state"]["strategy"]["pending"][0]
        self.assertEqual(order["execution_session"],str(self.sessions[1]))
        self.assertEqual(order["quantity"],190)
        self.assertEqual(first["event_count"],2)

    def test_entry_costs_cash_and_equity_independently(self):
        s=self.enter()["state"]
        # 190 shares * INR100 *1.001 = 19019; fee=19.02; total=19038.02.
        self.assertEqual(s["strategy"]["cash_inr"],"80961.98")
        self.assertEqual(s["strategy"]["fees_inr"],"19.02")
        self.assertEqual(s["strategy"]["slippage_inr"],"19.00")
        self.assertEqual(s["latest_valuation"]["equity_inr"],"99961.98")
        self.assertEqual(s["strategy"]["positions"]["UP"]["holding_sessions"],1)

    def test_same_day_reranking_cannot_replace_recorded_decision(self):
        first=self.update(0)
        r=report(self.sessions[0],[])
        again=self.update(0,r=r)
        self.assertEqual(again,first)

    def test_future_report_and_stale_report_are_rejected(self):
        now=stamp(self.sessions[0])
        for r in (report(self.sessions[1]),report(self.sessions[0])):
            with self.subTest(session=r["last_session"]):
                with self.assertRaises(ValidationError):
                    self.ledger.update(r,self.calendar,[snapshot(self.sessions[0])],actions(self.sessions,now),
                        now=now if r["last_session"]==str(self.sessions[1]) else stamp(self.sessions[1]))

    def test_in_session_run_does_not_place_a_past_open_entry(self):
        now=self.calendar[self.sessions[1]]["open_at"]+timedelta(hours=1)
        status=self.ledger.update(self.r,self.calendar,[snapshot(self.sessions[0])],actions(self.sessions,now),now=now)
        self.assertEqual(status["state"]["strategy"]["pending"],[])
        self.assertEqual(status["event_count"],1)

    def test_gap_over_budget_cancels_without_resizing(self):
        self.update(0)
        rows=[quote(price="120",opening="120"),quote("NIFTYBEES","200",isin="IN0000000099")]
        s=self.update(1,r=report(self.sessions[1],[asset(self.sessions[1],price=120)]),
                      snaps=[snapshot(self.sessions[0]),snapshot(self.sessions[1],rows=rows)])
        self.assertEqual(s["state"]["strategy"]["positions"],{})
        cancelled=[e for e in s["recent_events"] if e["key"].startswith("session:")][0]["details"]["strategy"]
        self.assertEqual(cancelled[0]["type"],"entry_cancelled")
        self.assertEqual(s["state"]["strategy"]["cash_inr"],"100000.00")

    def test_missing_execution_row_cancels_entry(self):
        self.update(0)
        r=report(self.sessions[1],[])
        s=self.update(1,r=r,snaps=[snapshot(self.sessions[0]),snapshot(self.sessions[1],rows=[quote("NIFTYBEES","200",isin="IN0000000099")])])
        self.assertFalse(s["state"]["strategy"]["positions"])
        self.assertFalse(s["state"]["strategy"]["pending"])

    def test_missing_complete_session_rolls_back_settlement(self):
        before=self.enter()
        with self.assertRaisesRegex(ValidationError,"missing the complete price file"):
            self.update(4,snaps=[snapshot(s) for i,s in enumerate(self.sessions[:5]) if i!=3])
        self.assertEqual(self.ledger.status(),before)

    def test_missing_held_quote_suppresses_returns_but_does_not_delete_position(self):
        self.enter()
        s=self.update(2,r=report(self.sessions[2],[]),snaps=[snapshot(self.sessions[2],rows=[quote("NIFTYBEES","200",isin="IN0000000099")])])
        self.assertIn("UP",s["state"]["strategy"]["positions"])
        self.assertIsNone(s["state"]["latest_valuation"]["return"])
        self.assertIsNone(s["state"]["latest_valuation"]["excess_return"])
        self.assertEqual(s["state"]["latest_valuation"]["stale_symbols"],["UP"])

    def test_exit_after_twenty_complete_sessions_even_after_downtime(self):
        self.update(0)
        s=self.update(20)
        self.assertEqual(s["state"]["strategy"]["positions"]["UP"]["holding_sessions"],20)
        s=self.update(21)
        self.assertFalse(s["state"]["strategy"]["positions"])
        self.assertEqual(s["state"]["strategy"]["closed_trades"],1)
        # Sell gross=18981, fee=18.98, net=18962.02; round-trip loss=76.
        self.assertEqual(s["state"]["strategy"]["realized_inr"],"-76.00")
        self.assertEqual(s["state"]["strategy"]["cash_inr"],"99924.00")
        self.assertEqual(len(s["state"]["benchmark"]["positions"]),1)

    def test_missed_days_do_not_generate_retroactive_decisions(self):
        self.update(0)
        s=self.update(5)
        keys=[e["key"] for e in s["recent_events"] if e["key"].startswith("decision:")]
        self.assertEqual(keys,["decision:"+str(self.sessions[0]),"decision:"+str(self.sessions[5])])

    def test_split_preserves_economic_equity_and_changes_quantity(self):
        self.enter()
        action={"symbol":"UP","kind":"split","ex_date":str(self.sessions[2]),"numerator":"5","denominator":"10","isin":"IN0000000001"}
        rows=[quote(price="50",isin="IN0000000002"),quote("NIFTYBEES","200",isin="IN0000000099")]
        s=self.update(2,r=report(self.sessions[2],[asset(self.sessions[2],price=50,isin="IN0000000002")]),
                      snaps=[snapshot(self.sessions[2],rows=rows)],event_rows=[action])
        self.assertEqual(s["state"]["strategy"]["positions"]["UP"]["quantity"],380)
        self.assertEqual(s["state"]["latest_valuation"]["equity_inr"],"99961.98")

    def test_dividend_is_receivable_not_spendable_cash(self):
        self.enter()
        action={"symbol":"UP","kind":"dividend","ex_date":str(self.sessions[2]),"cash_inr":"2"}
        rows=[quote(price="98"),quote("NIFTYBEES","200",isin="IN0000000099")]
        s=self.update(2,r=report(self.sessions[2],[asset(self.sessions[2],price=98)]),snaps=[snapshot(self.sessions[2],rows=rows)],event_rows=[action])
        self.assertEqual(s["state"]["strategy"]["receivable_inr"],"380.00")
        self.assertEqual(s["state"]["strategy"]["cash_inr"],"80961.98")
        self.assertEqual(s["state"]["latest_valuation"]["equity_inr"],"99961.98")

    def test_unsupported_and_fractional_actions_pause_without_partial_writes(self):
        before=self.enter()
        cases=[{"kind":"unsupported"},{"kind":"bonus","numerator":3,"denominator":4}]
        for case in cases:
            a={"symbol":"UP","ex_date":str(self.sessions[2]),**case}
            with self.subTest(case=case):
                with self.assertRaises(ValidationError):self.update(2,event_rows=[a])
                self.assertEqual(self.ledger.status(),before)

    def test_action_revision_cannot_silently_rewrite_settled_results(self):
        before=self.enter()
        revision={"symbol":"UP","kind":"dividend","ex_date":str(self.sessions[1]),"cash_inr":"2"}
        with self.assertRaisesRegex(ValidationError,"Previously settled"):
            self.update(2,event_rows=[revision])
        self.assertEqual(self.ledger.status(),before)

    def test_future_receipts_and_insufficient_action_coverage_are_rejected(self):
        self.update(0)
        s=snapshot(self.sessions[1]);s["received_at"]=iso(stamp(self.sessions[1])+timedelta(seconds=1))
        with self.assertRaisesRegex(ValidationError,"future"):self.update(1,snaps=[s])
        a=actions(self.sessions,stamp(self.sessions[1]));a["data"]["coverage_end"]=str(self.sessions[0])
        with self.assertRaisesRegex(ValidationError,"does not cover"):
            self.ledger.update(report(self.sessions[1]),self.calendar,[snapshot(self.sessions[1])],a,now=stamp(self.sessions[1]))

    def test_more_than_five_candidates_reserves_cash_without_overdraft(self):
        assets=[asset(self.sessions[0],f"S{i}",isin=f"IN00000000{i+1:02}") for i in range(8)]
        rows=[quote(a["symbol"],isin=a["isin"]) for a in assets]+[quote("NIFTYBEES","200",isin="IN0000000099")]
        s=self.update(0,r=report(self.sessions[0],assets),snaps=[snapshot(self.sessions[0],rows=rows)])
        pending=s["state"]["strategy"]["pending"]
        self.assertEqual(len(pending),5)
        self.assertEqual(sum(Decimal(o["maximum_cost_inr"]) for o in pending),Decimal("100000"))

    def test_state_cannot_be_reset_or_mutated(self):
        self.enter()
        with self.assertRaisesRegex(ValidationError,"different cash"):
            self.ledger.initialize(self.r,self.calendar,cash="200000",now=stamp(self.sessions[0]))
        with closing(sqlite3.connect(self.ledger.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):conn.execute("DELETE FROM events")
            with self.assertRaises(sqlite3.IntegrityError):conn.execute("UPDATE events SET payload='{}'")

    def test_altered_report_is_rejected_before_mutation(self):
        r=deepcopy(self.r);r["combined_highlights"]=[]
        with self.assertRaisesRegex(ValidationError,"intact"):
            self.update(0,r=r)

    def test_ledger_status_does_not_create_a_database(self):
        p=Path(self.tmp.name)/"absent.sqlite3"
        self.assertEqual(ForwardLedger(p).status(),{"initialized":False})
        self.assertFalse(p.exists())

    def test_drawdown_and_positive_gain_use_actual_cash_and_marks(self):
        self.enter()
        rows=[quote(price="90"),quote("NIFTYBEES","200",isin="IN0000000099")]
        s=self.update(2,r=report(self.sessions[2],[asset(self.sessions[2],price=90)]),snaps=[snapshot(self.sessions[2],rows=rows)])
        self.assertEqual(s["state"]["latest_valuation"]["equity_inr"],"98061.98")
        self.assertAlmostEqual(s["state"]["maximum_drawdown"],.0193802)

        rows[0]=quote(price="110")
        s=self.update(3,r=report(self.sessions[3],[asset(self.sessions[3],price=110)]),snaps=[snapshot(self.sessions[3],rows=rows)])
        self.assertEqual(s["state"]["latest_valuation"]["equity_inr"],"101861.98")
        self.assertAlmostEqual(s["state"]["maximum_drawdown"],.0193802)

    def test_benchmark_gap_cancels_then_retries_without_false_comparison(self):
        self.update(0)
        rows=[quote(),quote("NIFTYBEES","250",isin="IN0000000099")]
        s=self.update(1,snaps=[snapshot(self.sessions[1],rows=rows)])
        self.assertFalse(s["state"]["benchmark"]["positions"])
        self.assertEqual(len(s["state"]["benchmark"]["pending"]),1)
        self.assertIsNone(s["state"]["latest_valuation"]["benchmark_return"])
        self.assertIsNone(s["state"]["latest_valuation"]["excess_return"])

    def test_identity_change_requires_review_instead_of_wrong_stock_mark(self):
        before=self.enter()
        rows=[quote(isin="IN0000000002"),quote("NIFTYBEES","200",isin="IN0000000099")]
        with self.assertRaisesRegex(ValidationError,"identity changed"):
            self.update(2,snaps=[snapshot(self.sessions[2],rows=rows)])
        self.assertEqual(self.ledger.status(),before)

    def test_changed_ranking_policy_cannot_enter_existing_experiment(self):
        r=deepcopy(self.r);r["ranking_policy"]["technical_weight"]=.9
        r["report_id"]=digest({k:v for k,v in r.items() if k!="report_id"})
        with self.assertRaisesRegex(ValidationError,"Ranking policy"):
            self.update(0,r=r)

    def test_concurrent_duplicate_runs_have_one_decision(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:self.update(0),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(self.ledger.status()["event_count"],2)

    def test_missing_exit_quote_carries_position_until_next_traded_open(self):
        self.update(0);self.update(20)
        rows=[quote("NIFTYBEES","200",isin="IN0000000099")]
        s=self.update(21,r=report(self.sessions[21],[]),snaps=[snapshot(self.sessions[21],rows=rows)])
        self.assertEqual(s["state"]["strategy"]["closed_trades"],0)
        s=self.update(22)
        self.assertEqual(s["state"]["strategy"]["closed_trades"],1)
        self.assertFalse(s["state"]["strategy"]["positions"])
