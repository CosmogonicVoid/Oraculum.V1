"""Strict, versioned contracts at the boundary between contributors.

All decimal returns are fractions: 0.05 means 5%, not 5.
Timestamps must include an explicit offset and are normalized to UTC.
Missing metrics are omitted or null; they are never silently replaced with zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
import re
from typing import Any, Mapping

from . import SCHEMA_VERSION

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
METRICS = frozenset({
    "close_inr", "turnover_20d_inr", "volatility_20d_annualized",
    "momentum_20d", "trend_50d", "volume_ratio_20d", "roce",
    "revenue_growth_yoy", "debt_to_equity", "pe_to_sector_median",
    "news_sentiment", "announcement_impact",
})
DAILY_METRICS = frozenset({
    "close_inr", "turnover_20d_inr", "volatility_20d_annualized",
    "momentum_20d", "trend_50d", "volume_ratio_20d",
})
FUNDAMENTAL_METRICS = frozenset({
    "roce", "revenue_growth_yoy", "debt_to_equity", "pe_to_sector_median",
})
SOURCE_KINDS = frozenset({"prices", "fundamentals", "news", "announcement", "derived"})
SECTORS = frozenset({
    "industrials", "technology", "consumer", "healthcare", "energy",
    "materials", "utilities", "real_estate", "telecom", "financials", "other",
})
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")


class ValidationError(ValueError):
    """An actionable, user-facing input error."""


def obj(value: Any, path: str, required: set[str], optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected an object")
    if any(not isinstance(k, str) for k in value):
        raise ValidationError(f"{path}: object field names must be strings")
    missing = required - value.keys()
    extra = value.keys() - required - (optional or set())
    if missing:
        raise ValidationError(f"{path}: missing fields {', '.join(sorted(missing))}")
    if extra:
        raise ValidationError(f"{path}: unknown fields {', '.join(sorted(extra))}")
    return value


def sequence(value: Any, path: str, *, limit: int = 10_000) -> list:
    if not isinstance(value, list) or len(value) > limit:
        raise ValidationError(f"{path}: expected an array with at most {limit} entries")
    return value


def text_value(value: Any, path: str, *, token: bool = False, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError(f"{path}: expected nonempty text, at most {limit} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError(f"{path}: control characters are not permitted")
    if token and not TOKEN.fullmatch(value):
        raise ValidationError(f"{path}: invalid identifier")
    return value


def number(value: Any, path: str, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{path}: expected a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValidationError(f"{path}: expected a finite number") from exc
    if not math.isfinite(result):
        raise ValidationError(f"{path}: expected a finite number")
    if low is not None and result < low:
        raise ValidationError(f"{path}: must be >= {low}")
    if high is not None and result > high:
        raise ValidationError(f"{path}: must be <= {high}")
    return result


def integer(value: Any, path: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValidationError(f"{path}: expected an integer from {low} to {high}")
    return value


def timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValidationError(f"{path}: expected an ISO timestamp including a timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValidationError(f"{path}: timezone is required")
        return result.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(f"{path}: invalid ISO timestamp") from exc


def day(value: Any, path: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError(f"{path}: expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{path}: invalid date") from exc


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Source:
    id: str
    kind: str
    title: str
    uri: str
    published_at: datetime
    available_at: datetime
    content_sha256: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "uri": self.uri,
            "published_at": iso(self.published_at), "available_at": iso(self.available_at),
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class Metric:
    value: float | None
    observed_at: datetime
    available_at: datetime
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "value": self.value, "observed_at": iso(self.observed_at),
            "available_at": iso(self.available_at), "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class AssetSnapshot:
    symbol: str
    exchange: str
    sector: str
    session: date
    metrics: Mapping[str, Metric]

    @property
    def instrument_id(self) -> str:
        return f"{self.exchange}:{self.symbol}"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "exchange": self.exchange, "sector": self.sector,
            "session": self.session.isoformat(),
            "metrics": {k: v.to_dict() for k, v in sorted(self.metrics.items())},
        }


@dataclass(frozen=True)
class ResearchBundle:
    dataset_id: str
    mode: str
    as_of: datetime
    last_session: date
    session_close_at: datetime
    sources: tuple[Source, ...]
    assets: tuple[AssetSnapshot, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION, "dataset_id": self.dataset_id,
            "mode": self.mode, "as_of": iso(self.as_of),
            "last_session": self.last_session.isoformat(),
            "session_close_at": iso(self.session_close_at),
            "sources": [s.to_dict() for s in sorted(self.sources, key=lambda s: s.id)],
            "assets": [a.to_dict() for a in sorted(self.assets, key=lambda a: a.instrument_id)],
        }


def _metric_range(name: str, value: Any, path: str) -> float | None:
    if value is None:
        return None
    lower = {
        "close_inr": 0, "turnover_20d_inr": 0, "volatility_20d_annualized": 0,
        "momentum_20d": -1, "trend_50d": -1, "volume_ratio_20d": 0,
        "revenue_growth_yoy": -1, "debt_to_equity": 0, "pe_to_sector_median": 0,
        "news_sentiment": -1, "announcement_impact": -1,
    }.get(name)
    upper = 1 if name in {"news_sentiment", "announcement_impact"} else None
    result = number(value, path, lower, upper)
    if name in {"close_inr", "pe_to_sector_median"} and result == 0:
        raise ValidationError(f"{path}: must be positive; use null if unavailable")
    return result


def parse_bundle(raw: Any) -> ResearchBundle:
    """Reject malformed data, duplicate identifiers and known future information.

    This verifies declared timestamps, not the truthfulness of a data vendor.
    A provider must retain historical vintages and genuine first-availability times.
    """
    root = obj(raw, "bundle", {
        "schema_version", "dataset_id", "mode", "as_of", "last_session", "session_close_at",
        "sources", "assets",
    })
    integer(root["schema_version"], "schema_version", SCHEMA_VERSION, SCHEMA_VERSION)
    dataset = text_value(root["dataset_id"], "dataset_id", token=True)
    if root["mode"] not in ("synthetic", "imported"):
        raise ValidationError("mode: expected synthetic or imported")
    as_of = timestamp(root["as_of"], "as_of")
    last_session = day(root["last_session"], "last_session")
    session_close = timestamp(root["session_close_at"], "session_close_at")
    if session_close.astimezone(IST).date() != last_session or session_close > as_of:
        raise ValidationError("session_close_at: must match last_session and be <= as_of")
    if last_session > as_of.astimezone(IST).date():
        raise ValidationError("last_session: cannot be after as_of in India")
    sources: dict[str, Source] = {}
    for i, raw_source in enumerate(sequence(root["sources"], "sources")):
        path = f"sources[{i}]"
        s = obj(raw_source, path, {
            "id", "kind", "title", "uri", "published_at", "available_at", "content_sha256",
        })
        sid = text_value(s["id"], f"{path}.id", token=True)
        if sid in sources:
            raise ValidationError(f"{path}: duplicate source id {sid}")
        if not isinstance(s["kind"], str) or s["kind"] not in SOURCE_KINDS:
            raise ValidationError(f"{path}.kind: unknown source kind")
        uri = text_value(s["uri"], f"{path}.uri", limit=2000)
        allowed = ("https://", "http://", "file://")
        if root["mode"] == "synthetic":
            allowed += ("fixture://",)
        if not uri.startswith(allowed):
            raise ValidationError(f"{path}.uri: unsupported source URI")
        published = timestamp(s["published_at"], f"{path}.published_at")
        available = timestamp(s["available_at"], f"{path}.available_at")
        if not published <= available <= as_of:
            raise ValidationError(f"{path}: require published_at <= available_at <= as_of")
        sha = s["content_sha256"]
        if sha is not None and (not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)):
            raise ValidationError(f"{path}.content_sha256: expected lowercase SHA-256 or null")
        sources[sid] = Source(sid, s["kind"], text_value(s["title"], f"{path}.title"),
                              uri, published, available, sha)
    assets: list[AssetSnapshot] = []
    instruments: set[str] = set()
    for i, raw_asset in enumerate(sequence(root["assets"], "assets", limit=5000)):
        path = f"assets[{i}]"
        a = obj(raw_asset, path, {"symbol", "exchange", "sector", "session", "metrics"})
        symbol = text_value(a["symbol"], f"{path}.symbol", token=True)
        if symbol != symbol.upper():
            raise ValidationError(f"{path}.symbol: use uppercase symbols")
        if a["exchange"] not in ("NSE", "BSE"):
            raise ValidationError(f"{path}.exchange: expected NSE or BSE")
        if not isinstance(a["sector"], str) or a["sector"] not in SECTORS:
            raise ValidationError(f"{path}.sector: unknown sector")
        session = day(a["session"], f"{path}.session")
        if session > last_session:
            raise ValidationError(f"{path}.session: after last_session")
        instrument = f'{a["exchange"]}:{symbol}'
        if instrument in instruments:
            raise ValidationError(f"{path}: duplicate instrument {instrument}")
        instruments.add(instrument)
        raw_metrics = obj(a["metrics"], f"{path}.metrics", set(), set(METRICS))
        metrics: dict[str, Metric] = {}
        for name, raw_metric in raw_metrics.items():
            mp = f"{path}.metrics.{name}"
            m = obj(raw_metric, mp, {"value", "observed_at", "available_at", "source_ids"})
            observed = timestamp(m["observed_at"], f"{mp}.observed_at")
            available = timestamp(m["available_at"], f"{mp}.available_at")
            if not observed <= available <= as_of:
                raise ValidationError(f"{mp}: require observed_at <= available_at <= as_of")
            refs = sequence(m["source_ids"], f"{mp}.source_ids", limit=100)
            ids = tuple(text_value(sid, f"{mp}.source_ids", token=True) for sid in refs)
            if len(set(ids)) != len(ids):
                raise ValidationError(f"{mp}: duplicate source references")
            value = _metric_range(name, m["value"], f"{mp}.value")
            if value is not None and not ids:
                raise ValidationError(f"{mp}: non-null metrics require a source")
            for sid in ids:
                if sid not in sources:
                    raise ValidationError(f"{mp}: unknown source {sid}")
                if sources[sid].available_at > available:
                    raise ValidationError(f"{mp}: metric available before its source {sid}")
            if name in DAILY_METRICS and observed.astimezone(IST).date() != session:
                raise ValidationError(f"{mp}: daily observation must match asset session")
            if name in DAILY_METRICS and session == last_session and observed != session_close:
                raise ValidationError(f"{mp}: daily observation must equal session_close_at")
            metrics[name] = Metric(value, observed, available, tuple(sorted(ids)))
        assets.append(AssetSnapshot(symbol, a["exchange"], a["sector"], session, metrics))
    return ResearchBundle(dataset, root["mode"], as_of, last_session, session_close,
                          tuple(sorted(sources.values(), key=lambda s: s.id)),
                          tuple(sorted(assets, key=lambda a: a.instrument_id)))
