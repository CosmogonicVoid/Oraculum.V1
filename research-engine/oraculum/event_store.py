"""Append-only event revisions and feed receipts; reads never initialize a database."""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from .contracts import UTC, ValidationError, iso, timestamp
from .event_sources import CompanyMatcher, FEEDS, parse_feed
from .serialization import digest

SCHEMA = 60
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def micros(value):
    stamp = timestamp(value, "event time") if isinstance(value,str) else value
    if stamp.tzinfo is None:
        raise ValidationError("Event time requires an offset")
    delta = stamp.astimezone(UTC)-EPOCH
    return (delta.days*86400+delta.seconds)*1000000+delta.microseconds


class EventStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self, *, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10)
        else:
            conn = sqlite3.connect(self.path.resolve().as_uri()+"?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.Error:
            conn.close()
            raise
        if write and version == 0:
            if conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                conn.close()
                raise ValidationError("Refusing to initialize an unknown event database")
            conn.executescript('''
                CREATE TABLE metadata(identity TEXT NOT NULL);
                CREATE TABLE receipts(id INTEGER PRIMARY KEY, feed_id TEXT NOT NULL, url TEXT NOT NULL,
                    received_at TEXT NOT NULL, received_us INTEGER NOT NULL, sha256 TEXT NOT NULL, raw BLOB NOT NULL);
                CREATE TABLE events(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, feed_id TEXT NOT NULL,
                    kind TEXT NOT NULL, known_us INTEGER NOT NULL, published_us INTEGER, receipt_id INTEGER NOT NULL,
                    payload TEXT NOT NULL, checksum TEXT NOT NULL, symbols TEXT NOT NULL, identities TEXT NOT NULL,
                    search_text TEXT NOT NULL, timing TEXT NOT NULL);
                CREATE INDEX event_versions ON events(event_id,known_us,id);
                CREATE INDEX event_time ON events(known_us);
                CREATE TABLE feed_state(feed_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
                CREATE TRIGGER receipts_no_delete BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
                CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable event'); END;
                CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable event'); END;
                PRAGMA user_version=60;
            ''')
            conn.execute("INSERT INTO metadata VALUES(?)", (uuid.uuid4().hex,))
            conn.commit()
            version = SCHEMA
        if version != SCHEMA:
            conn.close()
            raise ValidationError("Unsupported event database version")
        return conn

    def identity(self):
        if not self.path.exists():
            return None
        with closing(self.connect()) as conn:
            return conn.execute("SELECT identity FROM metadata").fetchone()[0]

    def states(self):
        if not self.path.exists():
            return {}
        with closing(self.connect()) as conn:
            return {r["feed_id"]:json.loads(r["payload"]) for r in conn.execute("SELECT * FROM feed_state")}

    def set_state(self, feed_id, value):
        with closing(self.connect(write=True)) as conn, conn:
            conn.execute("INSERT INTO feed_state VALUES(?,?) ON CONFLICT(feed_id) DO UPDATE SET payload=excluded.payload", (feed_id,json.dumps(value,sort_keys=True)))

    def ingest(self, raw, feed, url, assets, *, received_at):
        items, counts = parse_feed(raw, feed)
        matcher = CompanyMatcher(assets)
        known = micros(received_at)
        universe = digest(sorted((a["symbol"],a.get("isin"),a.get("company_name")) for a in assets))
        entries = []
        for item in items:
            matches, state = matcher.match(item)
            pub = micros(item["published_at"]) if item["published_at"] else None
            timing = "future_publication" if pub is not None and pub > known else "dated" if pub is not None else "publication_unknown"
            payload = {**item, "matches":matches, "match_state":state, "matching_version":matcher.version,
                       "universe_hash":universe, "timing":timing}
            event_id = digest({"source":feed["id"],"publisher_id":item["publisher_id"]})
            entries.append((event_id,payload,pub))
        inserted = 0
        raw_sha = hashlib.sha256(raw).hexdigest()
        with closing(self.connect(write=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT max(received_us) FROM receipts").fetchone()[0]
            if previous is not None and known < previous:
                raise ValidationError("System clock moved backwards; event refresh paused")
            receipt = conn.execute("INSERT INTO receipts(feed_id,url,received_at,received_us,sha256,raw) VALUES(?,?,?,?,?,?)",
                                   (feed["id"],url,iso(received_at),known,raw_sha,raw)).lastrowid
            for ident,payload,pub in entries:
                checksum = digest(payload)
                old = conn.execute("SELECT checksum FROM events WHERE event_id=? ORDER BY known_us DESC,id DESC LIMIT 1", (ident,)).fetchone()
                if old and old[0] == checksum:
                    continue
                symbols = "|" + "|".join(m["symbol"] for m in payload["matches"]) + "|"
                identities = "|" + "|".join(m["isin"] for m in payload["matches"] if m.get("isin")) + "|"
                search = " ".join([payload["title"],payload["excerpt"],payload["reported_symbol"],
                                   *(m["symbol"] for m in payload["matches"])]).casefold()
                conn.execute("INSERT INTO events(event_id,feed_id,kind,known_us,published_us,receipt_id,payload,checksum,symbols,identities,search_text,timing) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ident,feed["id"],feed["kind"],known,pub,receipt,json.dumps(payload,sort_keys=True),checksum,symbols,identities,search,payload["timing"]))
                inserted += 1
        return {**counts, "new_revisions":inserted, "receipt_id":receipt,"sha256":raw_sha,
                "matched_items":sum(bool(p["matches"]) for _,p,_ in entries),
                "unknown_publication":sum(p["timing"] == "publication_unknown" for _,p,_ in entries),
                "future_publication":sum(p["timing"] == "future_publication" for _,p,_ in entries),
                "identity_conflicts":sum(p["match_state"] == "identity_conflict" for _,p,_ in entries)}

    def cursor(self):
        if not self.path.exists():
            return 0
        with closing(self.connect()) as conn:
            return conn.execute("SELECT coalesce(max(id),0) FROM events").fetchone()[0]

    def query(self, *, as_of=None, cursor=None, symbol="", isin="", kind="", source="", q="", match="", offset=0, limit=30, days=30):
        as_of = as_of or datetime.now(UTC)
        if isinstance(as_of,str):
            as_of = timestamp(as_of, "event cutoff")
        if not isinstance(offset,int) or not 0 <= offset <= 10000000 or not 1 <= limit <= 100 or not 1 <= days <= 366:
            raise ValidationError("Invalid event page/window")
        if kind not in ("", "news", "announcement", "board_meeting") or source not in ("", *(f["id"] for f in FEEDS)) or match not in ("", "matched", "unmatched", "conflict"):
            raise ValidationError("Invalid event filter")
        if any(len(str(v)) > 200 for v in (q,symbol,isin)) or (cursor is not None and (not isinstance(cursor,int) or cursor < 0)):
            raise ValidationError("Invalid event filter or cursor")
        result = {"items":[], "total":0,"offset":offset,"next_offset":None,"as_of":iso(as_of),"days":days,"cursor":cursor}
        if not self.path.exists():
            return result
        # Select the last revision actually known at this report's cutoff, then filter it.
        prefix = """WITH ranked AS (SELECT *,row_number() OVER(PARTITION BY event_id ORDER BY known_us DESC,id DESC) AS version
                    FROM events WHERE known_us<=? AND id<=?), selected AS (SELECT * FROM ranked WHERE version=1) """
        params = [micros(as_of), cursor if cursor is not None else 9223372036854775807,
                  micros(as_of-timedelta(days=days)), micros(as_of)]
        where = " WHERE version=1 AND coalesce(published_us,known_us)>=? AND (published_us IS NULL OR published_us<=?)"
        for name,value in (("kind",kind),("feed_id",source)):
            if value:
                where += f" AND {name}=?"; params.append(value)
        if symbol:
            where += " AND instr(symbols,?)>0"; params.append("|"+symbol+"|")
        if isin:
            where += " AND instr(identities,?)>0"; params.append("|"+isin+"|")
        if q:
            where += " AND instr(search_text,?)>0"; params.append(q.casefold())
        if match:
            where += {"matched":" AND symbols!='||'", "unmatched":" AND symbols='||'", "conflict":" AND payload LIKE '%\"match_state\": \"identity_conflict\"%'"}[match]
        with closing(self.connect()) as conn:
            result["total"] = conn.execute(prefix+"SELECT count(*) FROM selected"+where,params).fetchone()[0]
            rows = conn.execute(prefix+"SELECT * FROM selected"+where+" ORDER BY coalesce(published_us,known_us) DESC,id DESC LIMIT ? OFFSET ?",[*params,limit,offset]).fetchall()
            for row in rows:
                item = json.loads(row["payload"])
                if digest(item) != row["checksum"]:
                    raise ValidationError("Event integrity check failed")
                receipt = conn.execute("SELECT id,url,received_at,sha256 FROM receipts WHERE id=?",(row["receipt_id"],)).fetchone()
                first = conn.execute("SELECT min(known_us) FROM events WHERE event_id=? AND id<=?",(row["event_id"],row["id"])).fetchone()[0]
                item.update(event_id=row["event_id"],revision_id=row["id"],revision_checksum=row["checksum"],
                            received_at=receipt["received_at"], first_seen_at=iso(EPOCH+timedelta(microseconds=first)),receipt=dict(receipt))
                result["items"].append(item)
        if offset+limit < result["total"]:
            result["next_offset"] = offset+limit
        return result

    def audit(self):
        if not self.path.exists():
            return {"receipts":0,"revisions":0}
        with closing(self.connect()) as conn:
            receipts = revisions = 0
            for row in conn.execute("SELECT sha256,raw FROM receipts"):
                if hashlib.sha256(row["raw"]).hexdigest() != row["sha256"]:
                    raise ValidationError("Feed receipt integrity check failed")
                receipts += 1
            for row in conn.execute("SELECT payload,checksum FROM events"):
                if digest(json.loads(row["payload"])) != row["checksum"]:
                    raise ValidationError("Event integrity check failed")
                revisions += 1
        return {"receipts":receipts,"revisions":revisions}
