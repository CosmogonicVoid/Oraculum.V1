"""Transactional, hash-chained virtual order and execution history.

The ledger is append-only at the SQL level, not tamper-proof against its owner.
The simulator remains the single source of cash/position accounting rules.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from ..contracts import IST, UTC, ValidationError, day, iso, text_value, timestamp
from ..interfaces import PaperOrder, PortfolioState, Position
from ..local_data import decimal_amount
from ..repository import RunRepository
from ..serialization import canonical_json, digest
from .simulator import BasicPaperSimulator


def plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def decode_state(raw: dict) -> PortfolioState:
    try:
        state = PortfolioState(Decimal(raw["cash_inr"]), tuple(
            Position(p["instrument_id"], p["quantity"], Decimal(p["average_cost_inr"])) for p in raw["positions"]),
            tuple(raw["processed_order_ids"]))
        BasicPaperSimulator().execute_session(state, (), (), fee_bps=Decimal(0), slippage_bps=Decimal(0))
        return state
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Malformed paper portfolio") from exc


def decode_order(raw: dict) -> PaperOrder:
    return PaperOrder(raw["order_id"], raw["instrument_id"], raw["side"], raw["quantity"],
                      timestamp(raw["submitted_at"], "submitted_at"), raw["signal_run_id"])


class PaperLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self, *, create=False, write=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if not create and not self.path.is_file():
            raise ValidationError("Paper portfolio is not initialized; run paper-init")
        conn = (sqlite3.connect(self.path, timeout=20) if create or write else
                sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=20))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if create and version == 0 and not tables:
            conn.executescript("""
                CREATE TABLE paper_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_json TEXT NOT NULL, event_sha TEXT NOT NULL);
                CREATE TRIGGER paper_no_update BEFORE UPDATE ON paper_events
                BEGIN SELECT RAISE(ABORT, 'paper events are immutable'); END;
                CREATE TRIGGER paper_no_delete BEFORE DELETE ON paper_events
                BEGIN SELECT RAISE(ABORT, 'paper events are immutable'); END;
                PRAGMA user_version = 21;
            """)
            version = 21
        if version != 21:
            conn.close()
            raise ValidationError("Not an Oraculum paper ledger (use a separate database)")
        return conn

    @staticmethod
    def _read(conn) -> list[dict]:
        previous, events = "0" * 64, []
        try:
            for sequence, encoded, sha in conn.execute("SELECT seq,event_json,event_sha FROM paper_events ORDER BY seq"):
                event = json.loads(encoded)
                if (sequence != len(events) + 1 or digest(event) != sha or event["previous_sha256"] != previous
                        or (events and timestamp(event["recorded_at"], "recorded_at") <
                            timestamp(events[-1]["recorded_at"], "recorded_at"))):
                    raise ValueError("broken chain")
                events.append(event)
                previous = sha
            return events
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationError("Paper ledger integrity check failed") from exc

    @staticmethod
    def _append(conn, events, kind, payload, now):
        if now.tzinfo is None:
            raise ValidationError("Event time must be timezone aware")
        if events and now < timestamp(events[-1]["recorded_at"], "recorded_at"):
            raise ValidationError("Paper ledger clock moved backwards")
        event = {"kind": kind, "recorded_at": iso(now), "payload": payload,
                 "previous_sha256": digest(events[-1]) if events else "0" * 64}
        conn.execute("INSERT INTO paper_events (event_json,event_sha) VALUES (?,?)", (canonical_json(event), digest(event)))
        return event

    @staticmethod
    def _view(events):
        if not events or events[0]["kind"] != "init":
            raise ValidationError("Paper portfolio is not initialized")
        initial = events[0]["payload"]
        state, orders, executions = initial["state"], [], []
        for event in events[1:]:
            if event["kind"] == "order":
                orders.append(event["payload"])
            elif event["kind"] == "settle":
                state = event["payload"]["result"]["state"]
                executions.append(event["payload"])
            else:
                raise ValidationError("Unknown paper ledger event")
        decode_state(state)
        processed = set(state["processed_order_ids"])
        return {"mode": initial["mode"], "starting_cash_inr": initial["state"]["cash_inr"],
                "state": state, "pending": [o for o in orders if o["order_id"] not in processed],
                "orders": orders, "executions": executions, "event_count": len(events),
                "head_sha256": digest(events[-1])}

    def initialize(self, cash: Decimal, mode: str, *, now=None) -> dict:
        now = now or datetime.now(UTC)
        amount = decimal_amount(str(cash), "starting cash", positive=True)
        if amount != amount.quantize(Decimal("0.01")) or mode not in ("synthetic", "imported"):
            raise ValidationError("Use whole paise and mode synthetic or imported")
        payload = {"mode": mode, "state": plain(PortfolioState(amount, ()))}
        with closing(self._connect(create=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            events = self._read(conn)
            if events:
                if events[0]["payload"] != payload:
                    raise ValidationError("Portfolio already initialized with different settings; use a new ledger")
            else:
                events = [self._append(conn, events, "init", payload, now)]
            return self._view(events)

    def status(self) -> dict:
        with closing(self._connect()) as conn:
            return self._view(self._read(conn))

    def submit(self, repository: RunRepository, *, order_id, instrument_id, side, quantity, run_id, now=None) -> dict:
        now = now or datetime.now(UTC)
        text_value(order_id, "order_id", token=True)
        text_value(instrument_id, "instrument_id", token=True)
        report = repository.get(run_id)
        if now < max(timestamp(report["as_of"], "signal as_of"), timestamp(report["generated_at"], "signal generated_at")):
            raise ValidationError("An order cannot precede its saved research report")
        if side == "buy" and instrument_id not in report["shortlist"]:
            raise ValidationError("A research-backed paper buy must be in the saved shortlist")
        known = {d["instrument_id"] for d in report["decisions"]}
        if instrument_id not in known:
            raise ValidationError("Order instrument is absent from the saved report")
        order = PaperOrder(order_id, instrument_id, side, quantity, now, run_id)
        # Reuse the pure simulator's type/range validation; discard its no-bar rejection.
        BasicPaperSimulator().execute_session(PortfolioState(Decimal(0), ()), [order], [],
                                              fee_bps=Decimal(0), slippage_bps=Decimal(0))
        encoded = plain(order)
        with closing(self._connect(write=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            events = self._read(conn)
            view = self._view(events)
            if report["mode"] != view["mode"]:
                raise ValidationError("Synthetic and imported research require separate paper ledgers")
            for old in view["orders"]:
                if old["order_id"] == order_id:
                    if {k: v for k, v in old.items() if k != "submitted_at"} != {
                            k: v for k, v in encoded.items() if k != "submitted_at"}:
                        raise ValidationError("Order ID already exists with different details")
                    return old
            if view["executions"] and now <= timestamp(view["executions"][-1]["close_at"], "close_at"):
                raise ValidationError("Order cannot be inserted into an already settled session")
            self._append(conn, events, "order", encoded, now)
            return encoded

    def settle(self, session: date, bars, calendar: dict, *, fee_bps=Decimal("10"),
               slippage_bps=Decimal("10"), now=None) -> dict:
        now = now or datetime.now(UTC)
        if session not in calendar:
            raise ValidationError("Execution session is not in the supplied calendar")
        entry = calendar[session]
        if entry["close_at"] > now:
            raise ValidationError("Wait for the execution session to close before EOD settlement")
        bars = sorted(bars, key=lambda b: b.instrument_id)
        for bar in bars:
            if (bar.session != session or bar.open_at != entry["open_at"] or bar.close_at != entry["close_at"]
                    or bar.available_at > now):
                raise ValidationError("Execution bars must match this calendar session and be available now")
        request = {"session": session.isoformat(), "bars": plain(bars),
                   "fee_bps": str(fee_bps), "slippage_bps": str(slippage_bps),
                   "calendar": {s.isoformat(): plain(e) for s, e in sorted(calendar.items()) if s <= session}}
        request_sha = digest(request)
        with closing(self._connect(write=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            events = self._read(conn)
            view = self._view(events)
            for old in view["executions"]:
                if old["session"] == session.isoformat():
                    if old["request_sha256"] != request_sha:
                        raise ValidationError("Session already settled with different inputs")
                    return old
            if view["executions"] and session <= day(view["executions"][-1]["session"], "session"):
                raise ValidationError("Paper sessions must be settled chronologically")
            if not calendar or entry["open_at"] <= timestamp(events[0]["recorded_at"], "portfolio creation"):
                raise ValidationError("Cannot settle a session opened before this portfolio existed")
            orders = []
            for raw in view["pending"]:
                order = decode_order(raw)
                if min(calendar) > order.submitted_at.astimezone(IST).date():
                    raise ValidationError("Calendar must cover every pending order's submission date")
                following = [s for s, e in calendar.items() if e["open_at"] > order.submitted_at]
                if not following:
                    if order.submitted_at < entry["open_at"]:
                        raise ValidationError("Calendar has no next session for a pending order")
                    continue
                intended = min(following)
                if intended < session:
                    raise ValidationError(f"Pending order {order.order_id} requires settlement of {intended} first")
                if intended == session:
                    orders.append(order)
            result = BasicPaperSimulator().execute_session(decode_state(view["state"]), orders, bars,
                                                           fee_bps=fee_bps, slippage_bps=slippage_bps)
            payload = {"session": session.isoformat(), "close_at": iso(entry["close_at"]),
                       "request_sha256": request_sha, "request": request,
                       "orders": plain(orders), "result": plain(result)}
            self._append(conn, events, "settle", payload, now)
            return payload
