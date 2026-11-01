"""Bounded public-source downloads and append-only, point-in-time evidence.

No login, cookie emulation or access-denial retry. The source can change its
public interface; a failed refresh never becomes an empty authoritative dataset.
"""
from contextlib import closing
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import IST, UTC, ValidationError, iso, timestamp
from .serialization import canonical_json, digest

MAX_BYTES = 24 * 1024 * 1024
HOSTS = {"www.nseindia.com", "nsearchives.nseindia.com", "www.niftyindices.com"}
MASTER_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
RENAMES_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&_.-]{0,49}$")


def source_url(url):
    if not isinstance(url, str) or len(url) > 2500:
        raise ValidationError("Invalid exchange source URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Malformed exchange source URL") from exc
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username
            or parsed.password or port not in (None, 443) or parsed.fragment):
        raise ValidationError("Evidence downloads require a supported public exchange HTTPS source")
    return url


class ExchangeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        source_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url):
    source_url(url)
    req = Request(url, headers={"User-Agent": "Oraculum-local-research/0.4",
                               "Accept": "application/json,text/csv,application/xml,text/xml,*/*"})
    with build_opener(ExchangeRedirect()).open(req, timeout=25) as response:
        source_url(response.url)
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValidationError("Exchange response empty or larger than 24 MiB")
    return raw


def exchange_date(value):
    if not isinstance(value, str):
        raise ValidationError("Expected exchange date")
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise ValidationError(f"Unsupported exchange date: {value!r}")


def exchange_time(value):
    if not isinstance(value, str) or not value.strip() or value.strip() == "-":
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=IST).astimezone(UTC)
        except ValueError:
            pass
    raise ValidationError(f"Unsupported exchange timestamp: {value!r}")


def csv_rows(raw, required):
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        if len(set(headers)) != len(headers) or not set(required).issubset(headers):
            raise ValidationError("Exchange CSV columns changed or are incomplete")
        result = []
        for row in reader:
            if None in row or any(v is None for v in row.values()) or len(result) >= 100_000:
                raise ValidationError("Malformed or oversized exchange CSV")
            result.append({k.strip(): v.strip() for k, v in row.items()})
        if not result:
            raise ValidationError("Empty exchange CSV cannot replace a previous dataset")
        return result
    except (UnicodeError, csv.Error) as exc:
        raise ValidationError("Could not decode exchange CSV") from exc


def parse_master(raw):
    rows = csv_rows(raw, {"SYMBOL", "NAME OF COMPANY", "ISIN NUMBER", "SERIES"})
    result = {}
    for r in rows:
        if not SYMBOL.fullmatch(r["SYMBOL"]):
            continue
        isin = r["ISIN NUMBER"]
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin) or r["SYMBOL"] in result:
            raise ValidationError("Ambiguous security master identity")
        result[r["SYMBOL"]] = {"isin": isin, "name": r["NAME OF COMPANY"], "series": r["SERIES"]}
    return result


def parse_catalogue(raw):
    rows = csv_rows(raw, {"SYMBOL", "QUARTER END DATE", "CONSOLIDATED / STANDALONE", "XBRL",
                          "BROADCAST DATE/TIME", "REVISED DATE/TIME", "EXCHANGE DISSEMINATION TIME"})
    selected = {}
    for r in rows:
        symbol, url = r["SYMBOL"], r["XBRL"]
        if not SYMBOL.fullmatch(symbol) or not url or url == "-":
            continue
        source_url(url)
        if urlsplit(url).hostname != "nsearchives.nseindia.com" or not url.lower().endswith(".xml"):
            continue
        basis = r["CONSOLIDATED / STANDALONE"].lower()
        if basis not in ("consolidated", "standalone"):
            continue
        stamps = [exchange_time(r.get(k)) for k in
                  ("BROADCAST DATE/TIME", "REVISED DATE/TIME", "EXCHANGE DISSEMINATION TIME")]
        stamps = [x for x in stamps if x]
        if not stamps:
            continue  # No verifiable public availability time.
        end = exchange_date(r["QUARTER END DATE"])
        published = max(stamps)
        if end > published.astimezone(IST).date():
            raise ValidationError("Filing period ends after its publication")
        key = (symbol, basis, str(end), url)
        item = {"symbol": symbol, "company_name": r.get("COMPANY NAME", symbol),
                        "period_end": str(end), "basis": basis, "url": url,
                        "published_at": iso(published), "audit": r.get("AUDITED / UNAUDITED", "unknown"),
                        "submission": r.get("TYPE OF SUBMISSION", "unknown")}
        if key not in selected or published > timestamp(selected[key]["published_at"], "publication"):
            selected[key] = item
    results = sorted(selected.values(), key=lambda r: (r["symbol"], r["basis"], r["period_end"], r["published_at"], r["url"]))
    if not results:
        raise ValidationError("No usable filing records in the exchange catalogue")
    return results


def catalogue_url(today):
    # Integrated financial filings began in 2025. 600 days includes YoY and annual comparators.
    start = max(today - timedelta(days=600), exchange_date("2025-03-01"))
    return "https://www.nseindia.com/api/integrated-filing-results?" + urlencode({
        "index": "equities", "type": "Integrated Filing- Financials", "from_date": start.strftime("%d-%m-%Y"),
        "to_date": today.strftime("%d-%m-%Y"), "csv": "true"})


def actions_url(start, end):
    return "https://www.nseindia.com/api/corporates-corporateActions?" + urlencode({
        "index": "equities", "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")})


class EvidenceStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self, create=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=20)
        elif self.path.is_file():
            conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
        else:
            return None
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = list(conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        if create and version == 0 and not tables:
            conn.executescript("""
                CREATE TABLE evidence (id TEXT PRIMARY KEY, kind TEXT NOT NULL, lookup_key TEXT NOT NULL,
                    received_at TEXT NOT NULL, payload TEXT NOT NULL, checksum TEXT NOT NULL, raw BLOB NOT NULL);
                CREATE INDEX evidence_lookup ON evidence(kind,lookup_key,received_at);
                CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
                CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
                PRAGMA user_version=40;
            """)
            version = 40
        if version != 40:
            conn.close()
            raise ValidationError("Not an Oraculum evidence database")
        return conn

    @staticmethod
    def decode(row):
        try:
            p = json.loads(row[0])
            if digest(p) != row[1] or hashlib.sha256(row[2]).hexdigest() != p["sha256"]:
                raise ValueError("checksum")
            return p
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationError("Evidence cache integrity check failed") from exc

    def latest(self, kind, key, *, as_of):
        conn = self.connect()
        if conn is None:
            return None
        with closing(conn):
            row = conn.execute("SELECT payload,checksum,raw FROM evidence WHERE kind=? AND lookup_key=? AND received_at<=? ORDER BY received_at DESC,id DESC LIMIT 1",
                               (kind, key, as_of.astimezone(UTC).isoformat(timespec="microseconds"))).fetchone()
            result = self.decode(row) if row else None
            if result and (result["kind"] != kind or result["key"] != key or timestamp(result["received_at"], "receipt") > as_of):
                raise ValidationError("Evidence index disagrees with verified payload")
            return result

    def get(self, source_id):
        """Resolve an exact report receipt, never substitute a newer revision."""
        if (not isinstance(source_id, str) or not source_id.startswith("evidence-")
                or len(source_id) != 73 or any(c not in "0123456789abcdef" for c in source_id[9:])):
            raise ValidationError("Invalid evidence source ID")
        conn = self.connect()
        if conn is None:
            raise ValidationError("Evidence cache is unavailable")
        with closing(conn):
            row = conn.execute("SELECT payload,checksum,raw FROM evidence WHERE id=?", (source_id[9:],)).fetchone()
            result = self.decode(row) if row else None
            if result is None or result["source_id"] != source_id:
                raise ValidationError("Exact evidence receipt is unavailable")
            return result

    def put(self, kind, key, url, raw, parsed, *, received_at):
        source_url(url)
        sha = hashlib.sha256(raw).hexdigest()
        payload = {"kind": kind, "key": key, "uri": url, "sha256": sha,
                   "received_at": iso(received_at), "data": parsed}
        identity = digest(payload)
        payload["source_id"] = "evidence-" + identity
        with closing(self.connect(create=True)) as conn, conn:
            conn.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?,?)",
                         (identity, kind, key, received_at.astimezone(UTC).isoformat(timespec="microseconds"), canonical_json(payload), digest(payload), raw))
        return payload

    def fetch(self, kind, key, url, parse, *, offline=False, clock=None, downloader=None, max_age=None):
        clock, downloader = clock or (lambda: datetime.now(UTC)), downloader or download
        now = clock()
        old = self.latest(kind, key, as_of=now)
        if old and (max_age is None or now - timestamp(old["received_at"], "receipt") <= max_age):
            return old
        if offline:
            raise ValidationError(f"Offline evidence missing or stale: {kind}. Run an online integrated scan.")
        raw = downloader(url)
        data = parse(raw)  # Never persist an error page as valid evidence.
        return self.put(kind, key, url, raw, data, received_at=clock())


def evidence_reference(evidence):
    return {k: evidence[k] for k in ("source_id", "kind", "uri", "sha256", "received_at")}
