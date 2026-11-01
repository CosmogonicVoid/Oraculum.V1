"""Local NSE EOD ingestion. Public files are conveniences, not a guaranteed feed.

The archive stores actual receipt times. Historical downloads received today
cannot be used as if this installation knew their contents in the past.
"""
from __future__ import annotations

from contextlib import closing
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
from pathlib import Path
import sqlite3
import tempfile
from urllib.request import Request, urlopen
import zipfile

from .contracts import (
    DAILY_METRICS, IST, TOKEN, UTC, ValidationError, day, iso, obj,
    parse_bundle, sequence, text_value, timestamp,
)
from .interfaces import PriceBar
from .pipeline import build_run
from .providers.csv_provider import CSV_HEADER, _load_calendar, build_merged_bundle
from .serialization import canonical_json, digest, load_json

MAX_FILE = 16 * 1024 * 1024
MAX_CSV = 32 * 1024 * 1024
REQUIRED = frozenset({
    "TradDt", "BizDt", "Sgmt", "Src", "FinInstrmTp", "TckrSymb", "SctySrs",
    "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol", "TtlTrfVal", "SsnId",
})


def decimal_amount(value, label: str, *, positive=False) -> Decimal:
    if not isinstance(value, str) or len(value) > 64:
        raise ValidationError(f"{label}: supply a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{label}: invalid decimal") from exc
    if (not result.is_finite() or result < 0 or (positive and result == 0)
            or abs(result.adjusted()) > 20 or -result.as_tuple().exponent > 12):
        raise ValidationError(f"{label}: unsupported amount")
    return result


def parse_bhavcopy(content: bytes, expected_session: date, *, extended=False) -> dict:
    """Read NSE CM UDiFF final CSV/ZIP; retain supported EQ/STK/F1 rows.

    TtlTrfVal is INR. A VWAP range check guards against a unit/schema change.
    Unsupported series, no-trade rows and identifiers are counted, never imputed.
    No archive paths are extracted to the filesystem.
    """
    if not content or len(content) > MAX_FILE:
        raise ValidationError("Bhavcopy is empty or exceeds 16 MiB")
    try:
        if content.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = [x for x in archive.infolist() if not x.is_dir()]
                if (len(entries) != 1 or not entries[0].filename.lower().endswith(".csv")
                        or entries[0].file_size > MAX_CSV):
                    raise ValidationError("ZIP must contain exactly one CSV, at most 32 MiB")
                content_csv = archive.read(entries[0])
        else:
            content_csv = content
        reader = csv.DictReader(io.StringIO(content_csv.decode("utf-8-sig")), strict=True)
        header = reader.fieldnames or []
        if len(header) != len(set(header)) or not REQUIRED.issubset(header):
            raise ValidationError("Expected NSE CM UDiFF final bhavcopy columns; see docs/LOCAL.md")
        rows, skipped, seen = [], {}, set()
        for i, row in enumerate(reader, 2):
            if i > 100_000:
                raise ValidationError("Bhavcopy contains too many rows")
            if None in row or any(v is None for v in row.values()):
                raise ValidationError(f"Bhavcopy row {i}: wrong number of columns")
            row = {k: v.strip() for k, v in row.items()}
            if row["TradDt"] != expected_session.isoformat() or row["BizDt"] != expected_session.isoformat():
                raise ValidationError(f"Bhavcopy row {i}: wrong session")
            if row["Sgmt"] != "CM" or row["Src"] != "NSE":
                raise ValidationError(f"Bhavcopy row {i}: expected NSE cash-market data")
            reason = None
            if (row["SctySrs"], row["FinInstrmTp"], row["SsnId"]) != ("EQ", "STK", "F1"):
                reason = "outside_EQ_STK_F1"
            symbol = row["TckrSymb"]
            identifier = re.compile(r"^[A-Z0-9][A-Z0-9&_.-]{0,49}$") if extended else TOKEN
            if not reason and (not identifier.fullmatch(symbol) or symbol != symbol.upper()):
                reason = "unsupported_symbol"
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            if symbol in seen:
                raise ValidationError(f"Duplicate EQ stock {symbol}")
            seen.add(symbol)
            try:
                volume = int(row["TtlTradgVol"])
            except ValueError as exc:
                raise ValidationError(f"{symbol}: invalid volume") from exc
            if not 0 <= volume <= 10**15:
                raise ValidationError(f"{symbol}: unsupported volume")
            if volume == 0:
                skipped["no_trades"] = skipped.get("no_trades", 0) + 1
                continue
            prices = {k: decimal_amount(row[c], f"{symbol}.{k}", positive=True) for k, c in (
                ("open", "OpnPric"), ("high", "HghPric"), ("low", "LwPric"), ("close", "ClsPric"),
            )}
            if not (prices["low"] <= min(prices["open"], prices["close"])
                    <= max(prices["open"], prices["close"]) <= prices["high"]):
                raise ValidationError(f"{symbol}: invalid OHLC geometry")
            turnover = decimal_amount(row["TtlTrfVal"], f"{symbol}.turnover", positive=True)
            # Tolerate one rupee of aggregate rounding, not lakh/crore unit errors.
            if not prices["low"] * volume - 1 <= turnover <= prices["high"] * volume + 1:
                raise ValidationError(f"{symbol}: turnover/volume falls outside OHLC; check units/file format")
            rows.append({"symbol": symbol, **{k: str(v) for k, v in prices.items()},
                         "volume": volume, "turnover_inr": str(turnover)})
            if extended:
                isin = row.get("ISIN", "")
                if isin and not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
                    raise ValidationError(f"{symbol}: invalid ISIN")
                rows[-1].update(isin=isin, exchange_id=row.get("FinInstrmId", ""),
                                company_name=row.get("FinInstrmNm", symbol))
        if not rows:
            raise ValidationError("No supported traded EQ stocks in bhavcopy")
        return {"rows": sorted(rows, key=lambda x: x["symbol"]), "skipped": skipped}
    except (UnicodeError, csv.Error, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValidationError(f"Cannot decode bhavcopy: {exc}") from exc


def download_bhavcopy(session: date) -> tuple[bytes, str]:
    if session > datetime.now(IST).date():
        raise ValidationError("Cannot download a future session")
    uri = ("https://nsearchives.nseindia.com/content/cm/"
           f"BhavCopy_NSE_CM_0_0_0_{session:%Y%m%d}_F_0000.csv.zip")
    request = Request(uri, headers={"User-Agent": "Oraculum-local-research/0.2"})
    try:
        with urlopen(request, timeout=30) as response:
            # Do not accept redirects to an unrelated service.
            if not response.url.startswith("https://nsearchives.nseindia.com/"):
                raise ValidationError("Unexpected download redirect")
            data = response.read(MAX_FILE + 1)
    except OSError as exc:
        raise ValidationError(
            "NSE download unavailable. Download CM-UDiFF Common Bhavcopy Final from "
            "https://www.nseindia.com/all-reports and use import-nse. "
            f"The existing cache was retained. ({type(exc).__name__})"
        ) from exc
    parse_bhavcopy(data, session)
    return data, uri


class MarketStore:
    """Immutable first-receipt snapshots, separate from research and paper DBs."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self, *, create=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=20)
        elif self.path.is_file():
            conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
        else:
            raise ValidationError("No price cache yet; run import-nse or fetch-nse")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if create and version == 0 and not tables:
            conn.executescript("""
                CREATE TABLE market_snapshots (
                    session TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    payload_sha TEXT NOT NULL, raw BLOB NOT NULL);
                CREATE TRIGGER market_no_update BEFORE UPDATE ON market_snapshots
                BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
                CREATE TRIGGER market_no_delete BEFORE DELETE ON market_snapshots
                BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
                PRAGMA user_version = 20;
            """)
            version = 20
        if version != 20:
            conn.close()
            raise ValidationError("Not an Oraculum market cache (use a separate database)")
        return conn

    @staticmethod
    def _decode(row) -> dict:
        try:
            payload = json.loads(row[0])
            if digest(payload) != row[1] or hashlib.sha256(row[2]).hexdigest() != payload["sha256"]:
                raise ValueError("checksum")
            return payload
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationError("Market cache integrity check failed") from exc

    def ingest(self, content: bytes, session: date, uri: str, *, received_at: datetime | None = None) -> dict:
        received = received_at or datetime.now(UTC)
        if received.tzinfo is None or session > received.astimezone(IST).date():
            raise ValidationError("Invalid receipt time or future session")
        text_value(uri, "source URI", limit=2000)
        if not uri.startswith(("https://", "file://")):
            raise ValidationError("Source URI must be HTTPS or a local file URI")
        parsed = parse_bhavcopy(content, session)
        sha = hashlib.sha256(content).hexdigest()
        payload = {"session": session.isoformat(), "received_at": iso(received), "uri": uri,
                   "sha256": sha, "source_id": "nse-" + sha, **parsed}
        with closing(self._connect(create=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT payload,payload_sha,raw FROM market_snapshots WHERE session=?",
                               (session.isoformat(),)).fetchone()
            if old:
                saved = self._decode(old)
                if saved["sha256"] != sha:
                    raise ValidationError("A different snapshot already exists for this session; use a new cache for revisions")
                return saved
            conn.execute("INSERT INTO market_snapshots VALUES (?,?,?,?)",
                         (session.isoformat(), canonical_json(payload), digest(payload), content))
        return payload

    def snapshots(self, *, start: date | None = None, end: date | None = None) -> list[dict]:
        with closing(self._connect()) as conn:
            return [self._decode(row) for row in conn.execute(
                "SELECT payload,payload_sha,raw FROM market_snapshots WHERE session>=? AND session<=? ORDER BY session",
                ((start or date.min).isoformat(), (end or date.max).isoformat()))]

    def has_session(self, session: date) -> bool:
        if not self.path.is_file():
            return False
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM market_snapshots WHERE session=?", (session.isoformat(),)).fetchone() is not None

    def research_snapshots(self, *, start, end):
        """A versioned extended view over original bytes; never rewrite old receipts/payloads."""
        with closing(self._connect()) as conn:
            result = []
            for row in conn.execute("SELECT payload,payload_sha,raw FROM market_snapshots WHERE session>=? AND session<=? ORDER BY session",
                                    (str(start), str(end))):
                original = self._decode(row)
                parsed = parse_bhavcopy(row[2], day(original["session"], "session"), extended=True)
                result.append({**original, **parsed, "parser_version": "nse-udiff-equity-v2"})
            return result


def load_calendar(path: str | Path, *, as_of: datetime) -> tuple[dict, dict]:
    raw = obj(load_json(path), "calendar", {"coverage_start", "coverage_end", "source_uri", "sessions"})
    start, end = day(raw["coverage_start"], "coverage_start"), day(raw["coverage_end"], "coverage_end")
    uri = text_value(raw["source_uri"], "calendar.source_uri", limit=2000)
    if not uri.startswith(("https://", "file://")):
        raise ValidationError("Calendar source_uri must identify its source")
    if not start <= as_of.astimezone(IST).date() <= end:
        raise ValidationError("Calendar coverage does not include the requested cutoff; update the exchange calendar")
    with tempfile.TemporaryDirectory(prefix="oraculum-calendar-") as folder:
        temp = Path(folder) / "sessions.json"
        temp.write_text(canonical_json({"sessions": raw["sessions"]}), encoding="utf-8")
        calendar = _load_calendar(temp)
    if any(not start <= s <= end for s in calendar):
        raise ValidationError("Session falls outside the declared calendar coverage")
    return calendar, raw


def snapshot_bars(snapshot: dict, entry: dict, symbols: set[str] | None = None) -> list[PriceBar]:
    available = timestamp(snapshot["received_at"], "received_at")
    if available < entry["close_at"]:
        raise ValidationError("Final snapshot was received before the supplied session close")
    return [PriceBar(
        instrument_id="NSE:" + row["symbol"], session=day(snapshot["session"], "session"),
        open_at=entry["open_at"], close_at=entry["close_at"], available_at=available,
        open=Decimal(row["open"]), high=Decimal(row["high"]), low=Decimal(row["low"]),
        close=Decimal(row["close"]), volume=row["volume"], turnover_inr=Decimal(row["turnover_inr"]),
        source_id=snapshot["source_id"], adjustment_version="raw",
    ) for row in snapshot["rows"] if symbols is None or row["symbol"] in symbols]


def scan_local(store: MarketStore, watchlist_path, calendar_path, *, as_of=None,
               supplement_path=None, config=None) -> dict:
    cutoff = as_of or datetime.now(UTC)
    calendar, calendar_raw = load_calendar(calendar_path, as_of=cutoff)
    closed = [s for s, e in calendar.items() if e["close_at"] <= cutoff]
    if not closed:
        raise ValidationError("Calendar has no closed session at this cutoff")
    last = max(closed)
    watch = obj(load_json(watchlist_path), "watchlist", {"dataset_id", "assets"})
    assets = []
    for raw in sequence(watch["assets"], "watchlist.assets", limit=500):
        entry = obj(raw, "watchlist asset", {"symbol", "sector"})
        assets.append({**entry, "exchange": "NSE", "session": last.isoformat(), "metrics": {}})
    if not assets:
        raise ValidationError("Add at least one stock to the watchlist")
    bundle = {"schema_version": 1, "dataset_id": watch["dataset_id"], "mode": "imported",
              "as_of": iso(cutoff), "last_session": last.isoformat(),
              "session_close_at": iso(calendar[last]["close_at"]), "sources": [], "assets": assets}
    parse_bundle(bundle)  # Validate symbols/sectors before matching or network-independent computation.
    symbols = {a["symbol"] for a in assets}
    # At most 60 actual sessions are needed for the present 50-session features.
    window = set(closed[-60:])
    snapshots = [s for s in store.snapshots(start=min(window), end=last) if day(s["session"], "session") in window
                 and timestamp(s["received_at"], "received_at") <= cutoff]
    if last.isoformat() not in {s["session"] for s in snapshots}:
        raise ValidationError(f"Missing received final bhavcopy for latest closed session {last}; import it before scanning")
    bars = []
    for snap in snapshots:
        bars.extend(snapshot_bars(snap, calendar[day(snap["session"], "session")], symbols))
        bundle["sources"].append({"id": snap["source_id"], "kind": "prices",
            "title": f"NSE raw EOD {snap['session']}; publication conservatively set to local receipt",
            "uri": snap["uri"], "published_at": snap["received_at"], "available_at": snap["received_at"],
            "content_sha256": snap["sha256"]})
    if supplement_path:
        extra = obj(load_json(supplement_path), "supplement", {"sources", "assets"})
        bundle["sources"].extend(sequence(extra["sources"], "supplement.sources"))
        mapped, seen = {a["symbol"]: a for a in assets}, set()
        for a in sequence(extra["assets"], "supplement.assets"):
            a = obj(a, "supplement asset", {"symbol", "metrics"})
            if a["symbol"] not in mapped or a["symbol"] in seen:
                raise ValidationError("Supplement contains an unknown or duplicate watchlist symbol")
            seen.add(a["symbol"])
            if not isinstance(a["metrics"], dict) or DAILY_METRICS.intersection(a["metrics"]):
                raise ValidationError("Supplement may contain only non-price metrics")
            mapped[a["symbol"]]["metrics"] = a["metrics"]
    parse_bundle(bundle)
    with tempfile.TemporaryDirectory(prefix="oraculum-scan-") as folder:
        base, prices, sessions = [Path(folder) / x for x in ("base.json", "prices.csv", "sessions.json")]
        base.write_text(canonical_json(bundle), encoding="utf-8")
        sessions.write_text(canonical_json({"sessions": calendar_raw["sessions"]}), encoding="utf-8")
        with prices.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADER)
            for b in bars:
                writer.writerow([b.instrument_id, b.session.isoformat(), iso(b.open_at), iso(b.close_at),
                    iso(b.available_at), b.open, b.high, b.low, b.close, b.volume, b.turnover_inr,
                    b.source_id, b.adjustment_version])
        return build_run(build_merged_bundle(prices, base, sessions), config, generated_at=cutoff)
