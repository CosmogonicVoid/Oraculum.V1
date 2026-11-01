"""Append-only index of immutable research reports; timestamps are never backdated."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from .contracts import UTC, ValidationError, iso, timestamp
from .serialization import canonical_json, digest


def time_key(value):
    return timestamp(value, "history cutoff").astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ResearchHistory:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / "research-history.sqlite3"

    def _connect(self, create=False):
        if create:
            self.folder.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=20)
        else:
            conn = sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=20)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if create and version == 0 and not tables:
            conn.executescript("""
            CREATE TABLE reports (report_id TEXT PRIMARY KEY, as_of TEXT NOT NULL,
                payload TEXT NOT NULL, payload_sha TEXT NOT NULL);
            CREATE INDEX reports_time ON reports(as_of);
            CREATE TRIGGER reports_no_update BEFORE UPDATE ON reports
              BEGIN SELECT RAISE(ABORT, 'history is immutable'); END;
            CREATE TRIGGER reports_no_delete BEFORE DELETE ON reports
              BEGIN SELECT RAISE(ABORT, 'history is immutable'); END;
            PRAGMA user_version=50;
            """)
            version = 50
        if version != 50:
            conn.close()
            raise ValidationError("Not an Oraculum research history database")
        return conn

    def add(self, report, *, now=None):
        ident = report["report_id"]
        if digest({k:v for k,v in report.items() if k != "report_id"}) != ident:
            raise ValidationError("Cannot archive an altered research report")
        summary = {"report_id": ident, "as_of": report["as_of"], "session": report["last_session"],
                   "algorithm": report["algorithm"], "counts": report["counts"],
                   "combined_highlights": report.get("combined_highlights", []),
                   "technical_highlights": report.get("highlights", []),
                   "financial_coverage": report.get("fundamental_coverage", {}),
                   "archived_at": iso(now or datetime.now(UTC))}
        with closing(self._connect(True)) as conn, conn:
            conn.execute("INSERT OR IGNORE INTO reports VALUES (?,?,?,?)",
                         (ident, time_key(report["as_of"]), canonical_json(summary), digest(summary)))
        return summary

    def list(self, *, limit=100, offset=0):
        if not self.path.is_file():
            return {"total": 0, "items": [], "next_offset": None}
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 500 or offset < 0:
            raise ValidationError("Invalid history pagination")
        with closing(self._connect()) as conn:
            total = conn.execute("SELECT count(*) FROM reports").fetchone()[0]
            rows = conn.execute("SELECT report_id,as_of,payload,payload_sha FROM reports ORDER BY as_of DESC,report_id LIMIT ? OFFSET ?", (limit,offset)).fetchall()
        items = []
        for ident, cutoff, raw, sha in rows:
            item = json.loads(raw)
            if digest(item) != sha or item["report_id"] != ident or time_key(item["as_of"]) != cutoff:
                raise ValidationError("Research history integrity check failed")
            items.append(item)
        return {"total": total, "items": items, "next_offset": offset+limit if offset+limit < total else None}

    def recover(self):
        """Index old or interrupted publications without replacing their contents."""
        from .market_research import read_research
        known = set()
        if self.path.is_file():
            with closing(self._connect()) as conn:
                known = {r[0] for r in conn.execute("SELECT report_id FROM reports")}
        count = 0
        for path in sorted((self.folder / "research").glob("*.json")):
            ident = path.stem
            if len(ident) != 64 or any(c not in "0123456789abcdef" for c in ident) or ident in known:
                continue
            report = read_research(self.folder, ident)
            # A JSON left by interruption is still an auditable research record.
            self.add(report)
            count += 1
        return count
