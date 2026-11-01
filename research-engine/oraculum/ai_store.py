"""Append-only local AI packets and attempt receipts, separate from paper ledgers."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from .ai_contract import assemble
from .contracts import ValidationError, timestamp
from .serialization import canonical_json, digest


class BriefStore:
    def __init__(self, folder):
        self.path = Path(folder) / "ai-briefs.sqlite3"

    def connect(self, create=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=15)
        else:
            conn = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15
            )
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if (
            create
            and version == 0
            and not conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ):
            conn.executescript("""
            CREATE TABLE packets(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE records(id INTEGER PRIMARY KEY,attempt TEXT NOT NULL,phase TEXT NOT NULL,
              report TEXT NOT NULL,symbol TEXT NOT NULL,cache_key TEXT NOT NULL,packet TEXT NOT NULL,
              payload TEXT NOT NULL,sha TEXT NOT NULL,UNIQUE(attempt,phase));
            CREATE INDEX records_cache ON records(cache_key,id);
            CREATE INDEX records_report ON records(report,symbol,id);
            CREATE TRIGGER packets_no_update BEFORE UPDATE ON packets BEGIN SELECT RAISE(ABORT,'AI evidence is immutable'); END;
            CREATE TRIGGER packets_no_delete BEFORE DELETE ON packets BEGIN SELECT RAISE(ABORT,'AI evidence is immutable'); END;
            CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'AI journal is immutable'); END;
            CREATE TRIGGER records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'AI journal is immutable'); END;
            PRAGMA user_version=70;
            """)
            version = 70
        if version != 70:
            conn.close()
            raise ValidationError("Not an Oraculum AI journal")
        return conn

    def save_packet(self, packet):
        if packet.get("packet_id") != digest(
            {k: v for k, v in packet.items() if k != "packet_id"}
        ):
            raise ValidationError("AI evidence integrity check failed")
        with closing(self.connect(True)) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO packets VALUES (?,?)",
                (packet["packet_id"], canonical_json(packet)),
            )

    def packet(self, ident):
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM packets WHERE id=?", (ident,)
            ).fetchone()
        if not row:
            raise ValidationError("Saved evidence packet is missing")
        packet = json.loads(row[0])
        if (
            not isinstance(packet, dict)
            or packet.get("packet_id") != ident
            or digest({k: v for k, v in packet.items() if k != "packet_id"}) != ident
        ):
            raise ValidationError("AI evidence integrity check failed")
        return packet

    def validate(self, item):
        packet = self.packet(item["packet_id"])
        if (
            item.get("state") not in ("started", "accepted", "rejected", "failed")
            or item["report_id"] != packet["report_id"]
            or item["symbol"] != packet["symbol"]
        ):
            raise ValidationError("AI receipt does not match its evidence")
        if timestamp(item["started_at"], "AI start") < timestamp(
            packet["report_as_of"], "cutoff"
        ):
            raise ValidationError("AI generation precedes its evidence cutoff")
        if item["state"] != "started" and timestamp(
            item["generated_at"], "AI finish"
        ) < timestamp(item["started_at"], "AI start"):
            raise ValidationError("AI generation clock moved backwards")
        if item["state"] == "accepted" and item["brief"] != assemble(
            item["selection"], packet
        ):
            raise ValidationError("AI narrative does not match its evidence selection")

    def record(self, item):
        self.validate(item)
        phase = "start" if item["state"] == "started" else "finish"
        with closing(self.connect(True)) as conn, conn:
            if phase == "finish":
                start = conn.execute(
                    "SELECT report,symbol,cache_key,packet FROM records WHERE attempt=? AND phase='start'",
                    (item["attempt_id"],),
                ).fetchone()
                if start != (
                    item["report_id"],
                    item["symbol"],
                    item["cache_key"],
                    item["packet_id"],
                ):
                    raise ValidationError("AI result lacks a matching start receipt")
            conn.execute(
                "INSERT INTO records(attempt,phase,report,symbol,cache_key,packet,payload,sha) VALUES(?,?,?,?,?,?,?,?)",
                (
                    item["attempt_id"],
                    phase,
                    item["report_id"],
                    item["symbol"],
                    item["cache_key"],
                    item["packet_id"],
                    canonical_json(item),
                    digest(item),
                ),
            )

    def decode(self, row):
        item = json.loads(row[6])
        if not isinstance(item, dict) or digest(item) != row[7]:
            raise ValidationError("AI journal integrity check failed")
        expected = (
            item["attempt_id"],
            "start" if item["state"] == "started" else "finish",
            item["report_id"],
            item["symbol"],
            item["cache_key"],
            item["packet_id"],
        )
        if tuple(row[:6]) != expected:
            raise ValidationError("AI journal identity check failed")
        self.validate(item)
        return item

    def latest(self, *, report_id=None, symbol=None, cache_key=None):
        if not self.path.is_file():
            return None
        clauses, values = ["phase='finish'"], []
        for column, value in (
            ("report", report_id),
            ("symbol", symbol),
            ("cache_key", cache_key),
        ):
            if value is not None:
                clauses.append(column + "=?")
                values.append(value)
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT attempt,phase,report,symbol,cache_key,packet,payload,sha FROM records WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id DESC LIMIT 1",
                values,
            ).fetchone()
        return self.decode(row) if row else None

    def summaries(self, report_id):
        if not self.path.is_file():
            return {}
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT attempt,phase,report,symbol,cache_key,packet,payload,sha FROM records WHERE id IN (SELECT MAX(id) FROM records WHERE report=? AND phase='finish' GROUP BY symbol)",
                (report_id,),
            ).fetchall()
        return {item["symbol"]: item for item in map(self.decode, rows)}

    def audit(self):
        if not self.path.is_file():
            return {"ok": True, "packets": 0, "records": 0}
        with closing(self.connect()) as conn:
            packets = list(conn.execute("SELECT id FROM packets"))
            rows = list(
                conn.execute(
                    "SELECT attempt,phase,report,symbol,cache_key,packet,payload,sha FROM records ORDER BY id"
                )
            )
        for row in packets:
            self.packet(row[0])
        starts = {}
        for row in rows:
            item = self.decode(row)
            identity = (
                item["report_id"],
                item["symbol"],
                item["cache_key"],
                item["packet_id"],
            )
            if item["state"] == "started":
                starts[item["attempt_id"]] = identity
            elif starts.get(item["attempt_id"]) != identity:
                raise ValidationError("AI result lacks its matching start receipt")
        return {"ok": True, "packets": len(packets), "records": len(rows)}
