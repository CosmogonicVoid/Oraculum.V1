"""Automatic forward-only virtual experiment, isolated from the manual ledger.

Decisions are committed before a future open. Precommitted holding-period exits
can be settled after downtime. Missed decisions are never reconstructed.
"""
from contextlib import closing
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sqlite3

from .combined_ranking import ALGORITHM, SCHEMA, POLICY as RANKING_POLICY
from .contracts import UTC, ValidationError, day, iso, timestamp
from .local_data import decimal_amount
from .serialization import canonical_json, digest

D = Decimal
POLICY = {"version": "forward-combined-v1", "ranking_algorithm": ALGORITHM,
          "ranking_policy_hash": digest(RANKING_POLICY),
          "initial_cash_inr": "100000.00", "maximum_positions": 5,
          "position_budget_fraction": "0.20", "holding_sessions": 20,
          "fee_bps_each_side": "10", "slippage_bps_each_side": "10",
          "sizing_gap_buffer": "0.05", "benchmark_symbol": "NIFTYBEES",
          "benchmark_method": "Buy and hold with the same initial cash, fixed pre-open quantity, costs and residual cash; ETF proxy, not index TRI.",
          "dividend_method": "Accrue an unspendable receivable on ex-date; payment dates are not supplied.",
          "entry_rule": "First saved decision per price session; up to five combined highlights not already held. Fixed integer quantity; next scheduled open only, cancelled if unavailable or over budget.",
          "exit_rule": "Sell at the first traded open after 20 completed holding sessions; the exit rule is committed at entry. No stop-loss, leverage or shorts.",
          "missing_price_rule": "Carry last mark explicitly as stale; withhold current return/comparison until all held instruments have a current quote."}


def money(value):
    return str(D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP))


def account(cash):
    return {"cash_inr": money(cash), "receivable_inr": "0.00", "positions": {}, "pending": [],
            "fees_inr": "0.00", "slippage_inr": "0.00", "closed_trades": 0,
            "winning_trades": 0, "realized_inr": "0.00"}


def equity(book):
    return D(book["cash_inr"]) + D(book["receivable_inr"]) + sum(
        (D(p["last_close"]) * p["quantity"] for p in book["positions"].values()), D(0))


def actions_for(evidence, session, symbols):
    return sorted((a for a in evidence["data"]["actions"]
                   if a["ex_date"] == str(session) and a["symbol"] in symbols and a["kind"] != "meeting"),
                  key=lambda a: (a["symbol"], digest(a)))


def _quote(row, symbol):
    if not row or not row.get("isin"):
        raise ValidationError(f"{symbol}: an identified raw price row is required")
    for key in ("open", "close"):
        decimal_amount(str(row[key]), symbol+" "+key, positive=True)
    if type(row["volume"]) is not int or row["volume"] <= 0:
        raise ValidationError(f"{symbol}: invalid traded volume")


def _fill(book, symbol, quantity, raw_price, side, details):
    slip, fee = D(POLICY["slippage_bps_each_side"])/10000, D(POLICY["fee_bps_each_side"])/10000
    execution = D(raw_price) * (1 + slip if side == "buy" else 1 - slip)
    gross = D(money(execution * quantity))
    fees = D(money(gross * fee))
    cashflow = gross + fees if side == "buy" else gross - fees
    book["cash_inr"] = money(D(book["cash_inr"]) + (-cashflow if side == "buy" else cashflow))
    book["fees_inr"] = money(D(book["fees_inr"]) + fees)
    book["slippage_inr"] = money(D(book["slippage_inr"]) + abs(execution-D(raw_price))*quantity)
    details.append({"type": "fill", "side": side, "symbol": symbol, "quantity": quantity,
                    "raw_open_inr": str(raw_price), "execution_price_inr": str(execution),
                    "fees_inr": str(fees), "cashflow_inr": str(cashflow)})
    return cashflow


def settle_book(book, snapshot, session, actions, *, benchmark=False):
    """Pure deterministic transition; caller commits both books atomically."""
    rows = {r["symbol"]: r for r in snapshot["rows"]}
    details, stale = [], []
    grouped = {}
    for a in actions:
        grouped.setdefault(a["symbol"], []).append(a)
    for symbol, position in list(book["positions"].items()):
        row = rows.get(symbol)
        events = grouped.get(symbol, [])
        if len(events) > 1 or any(a["kind"] not in ("bonus", "split", "dividend") for a in events):
            raise ValidationError(f"{symbol} {session}: ambiguous or unsupported action; paper evaluation paused")
        if events:
            event = events[0]
            identities = {position["isin"], row.get("isin") if row else None}
            if event.get("isin") not in (None, "", "-") and event["isin"] not in identities:
                raise ValidationError(f"{symbol}: action identity mismatch; paper evaluation paused")
            if event["kind"] in ("bonus", "split"):
                if not row:
                    raise ValidationError(f"{symbol}: share action needs an ex-date quote")
                quantity = D(position["quantity"]) * D(event["denominator"]) / D(event["numerator"])
                if quantity != quantity.to_integral_value() or quantity <= 0:
                    raise ValidationError(f"{symbol}: fractional share entitlement needs review; paper evaluation paused")
                position["quantity"] = int(quantity)
                position["isin"] = row["isin"]
            else:
                amount = D(money(D(event["cash_inr"]) * position["quantity"]))
                book["receivable_inr"] = money(D(book["receivable_inr"]) + amount)
                position["dividends_inr"] = money(D(position["dividends_inr"]) + amount)
            details.append({"type": "corporate_action", "symbol": symbol, "action": event})
        if row:
            _quote(row, symbol)
            if row["isin"] != position["isin"]:
                raise ValidationError(f"{symbol}: price identity changed; paper evaluation paused for review")
            if not benchmark and position["holding_sessions"] >= POLICY["holding_sessions"]:
                if row["volume"] >= position["quantity"]:
                    proceeds = _fill(book, symbol, position["quantity"], row["open"], "sell", details)
                    pnl = proceeds + D(position["dividends_inr"]) - D(position["entry_cost_inr"])
                    book["closed_trades"] += 1
                    book["winning_trades"] += int(pnl > 0)
                    book["realized_inr"] = money(D(book["realized_inr"]) + pnl)
                    details[-1].update(pnl_inr=money(pnl), entry_report_id=position["report_id"],
                                       entry_session=position["entry_session"])
                    del book["positions"][symbol]
                    continue
                details.append({"type": "exit_unfilled", "symbol": symbol, "reason": "Order exceeds reported whole-day volume"})
            position["last_close"], position["mark_session"] = row["close"], str(session)
        else:
            # A symbol rename can be recognized but is deliberately not guessed.
            if any(r.get("isin") == position["isin"] for r in rows.values()):
                raise ValidationError(f"{symbol}: symbol changed; paper identity review required")
            stale.append(symbol)
        position["holding_sessions"] += 1
    remaining = []
    for order in book["pending"]:
        if order["execution_session"] > str(session):
            remaining.append(order)
            continue
        if order["execution_session"] < str(session):
            raise ValidationError("A pending paper entry session was skipped; restore its price file")
        symbol, quantity = order["symbol"], order["quantity"]
        row = rows.get(symbol)
        reason = None
        if not row:
            reason = "No traded quote on the committed entry session"
        elif grouped.get(symbol):
            reason = "Entry cancelled on a corporate-action date; quantity was fixed before the event"
        else:
            _quote(row, symbol)
            if row["isin"] != order["isin"]:
                reason = "Entry identity changed"
            elif row["volume"] < quantity:
                reason = "Order exceeds reported whole-day volume"
            else:
                gross = D(money(D(row["open"]) * (1+D(POLICY["slippage_bps_each_side"])/10000)*quantity))
                required = gross + D(money(gross * D(POLICY["fee_bps_each_side"])/10000))
                if required > min(D(order["maximum_cost_inr"]), D(book["cash_inr"])):
                    reason = "Opening gap exceeds the precommitted cash budget"
        if reason:
            details.append({"type": "entry_cancelled", "symbol": symbol, "reason": reason})
            continue
        cost = _fill(book, symbol, quantity, row["open"], "buy", details)
        book["positions"][symbol] = {"quantity": quantity, "isin": row["isin"],
            "entry_session": str(session), "entry_cost_inr": money(cost), "dividends_inr": "0.00",
            "last_close": row["close"], "mark_session": str(session), "holding_sessions": 1,
            "report_id": order["report_id"], "decision_at": order["decision_at"]}
    book["pending"] = remaining
    return details, stale


def make_order(symbol, row, budget, report, next_session, now):
    _quote(row, symbol)
    if budget <= 0:
        return None
    buffer = (1+D(POLICY["sizing_gap_buffer"])) * (1+D(POLICY["fee_bps_each_side"])/10000) * (1+D(POLICY["slippage_bps_each_side"])/10000)
    quantity = int(budget / (D(row["close"]) * buffer))
    if quantity < 1:
        return None
    return {"symbol": symbol, "isin": row["isin"], "quantity": quantity,
            "reference_close_inr": row["close"], "maximum_cost_inr": money(budget),
            "report_id": report["report_id"], "decision_at": iso(now),
            "execution_session": str(next_session)}


class ForwardLedger:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self, create=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=20)
        else:
            conn = sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=20)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if create and version == 0 and not tables:
            conn.executescript("""
            CREATE TABLE events (seq INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
              payload TEXT NOT NULL, sha TEXT NOT NULL);
            CREATE TRIGGER forward_no_update BEFORE UPDATE ON events
              BEGIN SELECT RAISE(ABORT, 'forward events are immutable'); END;
            CREATE TRIGGER forward_no_delete BEFORE DELETE ON events
              BEGIN SELECT RAISE(ABORT, 'forward events are immutable'); END;
            PRAGMA user_version=51;
            """)
            version = 51
        if version != 51:
            conn.close()
            raise ValidationError("Not an Oraculum forward experiment database")
        return conn

    @staticmethod
    def _events(conn):
        result, previous = [], None
        for seq, key, raw, sha in conn.execute("SELECT seq,event_key,payload,sha FROM events ORDER BY seq"):
            event = json.loads(raw)
            if (digest(event) != sha or event["previous"] != previous or event["key"] != key
                    or seq != len(result)+1):
                raise ValidationError("Forward experiment integrity check failed")
            previous = sha
            result.append(event | {"sha": sha})
        return result

    @staticmethod
    def _append(conn, events, key, state, details, now):
        event = {"key": key, "recorded_at": iso(now), "previous": events[-1]["sha"] if events else None,
                 "state": deepcopy(state), "details": details}
        sha = digest(event)
        conn.execute("INSERT INTO events VALUES (?,?,?,?)", (len(events)+1,key,canonical_json(event),sha))
        events.append(event | {"sha": sha})

    def initialize(self, report, calendar, *, cash="100000.00", now=None):
        now = now or datetime.now(UTC)
        cash = decimal_amount(cash, "virtual initial cash", positive=True)
        if cash < 1000 or cash > 1000000000 or cash != cash.quantize(D(".01")):
            raise ValidationError("Virtual cash must be INR 1,000–1,000,000,000 with at most two decimals")
        self._validate_report(report, calendar, now)
        with closing(self._connect(True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            events = self._events(conn)
            if events:
                if D(events[0]["state"]["initial_cash_inr"]) != cash:
                    raise ValidationError("Experiment already exists with different cash; it cannot be reset in place")
                return events[-1]["state"]
            state = {"policy": POLICY, "policy_hash": digest(POLICY), "created_at": iso(now),
                     "initial_cash_inr": money(cash), "last_session": report["last_session"],
                     "strategy": account(cash), "benchmark": account(cash), "benchmark_committed": False,
                     "peak_equity_inr": money(cash), "maximum_drawdown": 0.0,
                     "action_checks": [], "latest_valuation": None}
            self._append(conn, events, "init", state, {"report_id": report["report_id"]}, now)
            return state

    @staticmethod
    def _validate_report(report, calendar, now):
        if (report.get("report_schema") != SCHEMA or report.get("algorithm") != ALGORITHM
                or digest({k:v for k,v in report.items() if k != "report_id"}) != report.get("report_id")):
            raise ValidationError("Forward experiment requires an intact combined-ranking v1 report")
        if digest(report.get("ranking_policy")) != POLICY["ranking_policy_hash"]:
            raise ValidationError("Ranking policy differs from this forward experiment")
        if timestamp(report["as_of"], "report cutoff") > now:
            raise ValidationError("Cannot record a decision before the report exists")
        closed = [s for s,e in calendar.items() if e["close_at"] <= now]
        if not closed or report["last_session"] != str(max(closed)):
            raise ValidationError("Forward decisions require the latest completed price session")

    def update(self, report, calendar, snapshots, action_evidence, *, now=None):
        now = now or datetime.now(UTC)
        self._validate_report(report, calendar, now)
        if timestamp(action_evidence["received_at"], "action receipt") > now:
            raise ValidationError("Future corporate-action evidence")
        by_session = {s["session"]: s for s in snapshots}
        if len(by_session) != len(snapshots):
            raise ValidationError("Duplicate paper price session")
        with closing(self._connect(True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            events = self._events(conn)
            if not events:
                raise ValidationError("Initialize the forward experiment first")
            state = deepcopy(events[-1]["state"])
            if state["policy_hash"] != digest(POLICY):
                raise ValidationError("Paper policy changed; an existing experiment cannot silently change rules")
            if timestamp(events[-1]["recorded_at"], "last event") > now:
                raise ValidationError("Paper event clock moved backwards")
            action_data = action_evidence["data"]
            for check in state["action_checks"]:
                if action_data["coverage_start"] <= check["session"] <= action_data["coverage_end"]:
                    current = actions_for(action_evidence, check["session"], check["symbols"])
                    if digest(current) != check["digest"]:
                        raise ValidationError("Previously settled corporate actions changed; paper history needs review")
            sessions = sorted(s for s,e in calendar.items()
                              if str(s) > state["last_session"] and e["close_at"] <= now)
            for session in sessions:
                snapshot = by_session.get(str(session))
                if snapshot is None:
                    raise ValidationError(f"Paper settlement is missing the complete price file for {session}")
                if timestamp(snapshot["received_at"], "price receipt") > now:
                    raise ValidationError("Paper price file was received in the future")
                if not action_data["coverage_start"] <= str(session) <= action_data["coverage_end"]:
                    raise ValidationError("Corporate-action evidence does not cover paper settlement")
                symbols = set()
                for book in (state["strategy"], state["benchmark"]):
                    symbols.update(book["positions"])
                    symbols.update(o["symbol"] for o in book["pending"])
                    for order in book["pending"]:
                        if order["execution_session"] == str(session) and timestamp(order["decision_at"], "decision") >= calendar[session]["open_at"]:
                            raise ValidationError("A paper decision must predate its execution open")
                selected_actions = actions_for(action_evidence, session, symbols)
                strategy_events, stale = settle_book(state["strategy"], snapshot, session, selected_actions)
                benchmark_events, benchmark_stale = settle_book(state["benchmark"], snapshot, session, selected_actions, benchmark=True)
                nav, benchmark_nav = equity(state["strategy"]), equity(state["benchmark"])
                initial = D(state["initial_cash_inr"])
                if not stale:
                    peak = max(D(state["peak_equity_inr"]),nav)
                    state["peak_equity_inr"] = money(peak)
                    state["maximum_drawdown"] = max(state["maximum_drawdown"], float(1-nav/peak))
                valuation = {"session": str(session), "equity_inr": money(nav), "benchmark_equity_inr": money(benchmark_nav),
                             "stale_symbols": stale, "benchmark_stale_symbols": benchmark_stale,
                             "return": None if stale else float(nav/initial-1),
                             "benchmark_return": None if benchmark_stale or not state["benchmark"]["positions"] else float(benchmark_nav/initial-1),
                             "excess_return": None if stale or benchmark_stale or not state["benchmark"]["positions"] else float((nav-benchmark_nav)/initial),
                             "maximum_drawdown": state["maximum_drawdown"]}
                state["latest_valuation"], state["last_session"] = valuation, str(session)
                state["action_checks"].append({"session": str(session), "symbols": sorted(symbols), "digest": digest(selected_actions)})
                details = {"valuation": valuation, "strategy": strategy_events, "benchmark": benchmark_events,
                           "price_source_id": snapshot["source_id"], "action_source_id": action_evidence["source_id"]}
                self._append(conn, events, "session:"+str(session), state, details, now)
            decision_key = "decision:"+report["last_session"]
            if not any(e["key"] == decision_key for e in events):
                future = sorted(s for s in calendar if str(s) > report["last_session"])
                if not future:
                    raise ValidationError("Calendar needs the next session before paper entries can be committed")
                next_session = future[0]
                if calendar[next_session]["open_at"] > now:
                    snapshot = by_session.get(report["last_session"])
                    if snapshot is None or timestamp(snapshot["received_at"], "price receipt") > timestamp(report["as_of"], "report cutoff"):
                        raise ValidationError("Decision prices were not available at the report cutoff")
                    rows = {r["symbol"]: r for r in snapshot["rows"]}
                    book, skipped = state["strategy"], []
                    occupied = set(book["positions"]) | {o["symbol"] for o in book["pending"]}
                    free = D(book["cash_inr"]) - sum((D(o["maximum_cost_inr"]) for o in book["pending"]),D(0))
                    budget_limit = D(state["initial_cash_inr"]) * D(POLICY["position_budget_fraction"])
                    picks = sorted((a for a in report["assets"] if a["combined"]["highlight"]),
                                   key=lambda a: a["combined"]["rank"])
                    for asset in picks:
                        if len(occupied) >= POLICY["maximum_positions"]:
                            break
                        symbol = asset["symbol"]
                        if symbol in occupied:
                            continue
                        row = rows.get(symbol)
                        if not row or row.get("isin") != asset.get("isin") or D(row["close"]) != D(str(asset["metrics"]["close_inr"])):
                            raise ValidationError(f"{symbol}: report and raw decision quote disagree")
                        budget = min(budget_limit, free)
                        order = make_order(symbol,row,budget,report,next_session,now)
                        if order:
                            book["pending"].append(order)
                            occupied.add(symbol)
                            free -= D(order["maximum_cost_inr"])
                        else:
                            skipped.append({"symbol":symbol,"reason":"Cash allocation cannot fund one buffered share"})
                    if not state["benchmark"]["positions"] and not state["benchmark"]["pending"]:
                        benchmark = POLICY["benchmark_symbol"]
                        order = make_order(benchmark,rows.get(benchmark),D(state["initial_cash_inr"]),report,next_session,now)
                        if order is None:
                            raise ValidationError("Initial virtual cash cannot fund a benchmark share")
                        state["benchmark"]["pending"].append(order)
                        state["benchmark_committed"] = True
                    self._append(conn,events,decision_key,state,
                        {"report_id":report["report_id"],"next_session":str(next_session),
                         "ranked_highlights":report["combined_highlights"],"skipped":skipped,
                         "price_source_id":snapshot["source_id"]},now)
            return self._status(events)

    @staticmethod
    def _status(events):
        if not events:
            return {"initialized":False}
        state = deepcopy(events[-1]["state"])
        sessions = [e for e in events if e["key"].startswith("session:")]
        return {"initialized":True,"paper_only":True,"state":state,"event_count":len(events),
                "last_recorded_at":events[-1]["recorded_at"],
                "equity_curve":[e["details"]["valuation"] for e in sessions],
                "recent_events":[{k:v for k,v in e.items() if k != "state"} for e in events[-50:]],
                "limitations":["Forward simulation only; opening fills, queue priority and market impact are not observed.",
                    "10 bps fees and 10 bps slippage per side are configurable only by a new policy version, and are estimates rather than an exact tax/broker tariff.",
                    "Benchmark is NIFTYBEES plus residual cash with identical modeled costs; not the Nifty total-return index.",
                    "Dividend receivables count in equity but cannot fund purchases; fractional/unsupported actions and identity changes pause settlement.",
                    "No historical decisions are reconstructed. A computer that is off misses new decisions; prior committed orders are settled from cached raw files on recovery.",
                    "Maximum drawdown is measured at available daily closes; stale prices suppress current return comparisons."]}

    def status(self):
        if not self.path.is_file():
            return {"initialized":False}
        with closing(self._connect()) as conn:
            return self._status(self._events(conn))
