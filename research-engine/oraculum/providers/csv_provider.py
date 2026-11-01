# oraculum/providers/csv_provider.py
"""Supplied-data CSV adapter (Qwen assignment, Part B).

Offline command:

    python -m oraculum.providers.csv_provider \
        --prices INPUT.csv --base-bundle BASE.json \
        --sessions SESSIONS.json --output BUNDLE.json [--force]

Merge semantics, validation rules and the adjustment-version policy are
documented in docs/QWEN_IMPLEMENTATION.md. This module performs no network
access, no scraping and no corporate-action adjustment.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime
from decimal import Decimal, DecimalException
from pathlib import Path
import sys
from typing import Any

from ..contracts import (
    IST, ResearchBundle, ValidationError, day, iso, obj, parse_bundle, sequence, timestamp,
)
from ..features import BasicPriceFeatureBuilder
from ..interfaces import PriceBar
from ..serialization import load_json

CSV_HEADER = (
    "instrument_id", "session", "open_at", "close_at", "available_at",
    "open", "high", "low", "close", "volume", "turnover_inr", "source_id",
    "adjustment_version",
)

_DAILY_METRICS = frozenset({
    "close_inr", "turnover_20d_inr", "volatility_20d_annualized",
    "momentum_20d", "trend_50d", "volume_ratio_20d",
})


class CsvResearchProvider:
    """ResearchProvider over the supplied CSV tape, base bundle and calendar."""

    def __init__(self, prices_path: str | Path, base_bundle_path: str | Path, sessions_path: str | Path):
        self.prices_path = Path(prices_path)
        self.base_bundle_path = Path(base_bundle_path)
        self.sessions_path = Path(sessions_path)

    def load_bundle(self, *, as_of: datetime, last_session: date) -> ResearchBundle:
        if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValidationError("as_of: timezone is required")
        if type(last_session) is not date:
            raise ValidationError("last_session: expected a date")
        bundle = build_merged_bundle(self.prices_path, self.base_bundle_path, self.sessions_path)
        if bundle.as_of != as_of:
            raise ValidationError(
                f"load_bundle: requested as_of {as_of.isoformat()} does not match base bundle "
                f"{bundle.as_of.isoformat()}"
            )
        if bundle.last_session != last_session:
            raise ValidationError(
                f"load_bundle: requested last_session {last_session.isoformat()} does not match base bundle "
                f"{bundle.last_session.isoformat()}"
            )
        return bundle


def build_merged_bundle(
    prices_path: str | Path, base_bundle_path: str | Path, sessions_path: str | Path,
) -> ResearchBundle:
    """Build and validate the merged canonical bundle. Never writes inputs."""
    base_bundle = parse_bundle(load_json(base_bundle_path))
    calendar = _load_calendar(sessions_path)
    _check_base_against_calendar(base_bundle, calendar)
    bars = _load_price_rows(prices_path, base_bundle, calendar)
    raw = base_bundle.to_dict()
    raw["assets"] = [_merge_asset(asset, bars, base_bundle, calendar) for asset in base_bundle.assets]
    return parse_bundle(raw)


def _merge_asset(asset, bars: list[PriceBar], base_bundle: ResearchBundle, calendar: dict) -> dict:
    raw_asset = asset.to_dict()
    # Filter BEFORE choosing the latest session, vintage or contiguous window.
    own = [bar for bar in bars if bar.instrument_id == asset.instrument_id
           and bar.close_at <= base_bundle.as_of and bar.available_at <= base_bundle.as_of]
    if not own:
        return raw_asset  # never silently drop an input asset
    suffix = _contiguous_suffix(own, calendar)
    metrics = BasicPriceFeatureBuilder().build_metrics(suffix, as_of=base_bundle.as_of)
    sources = {source.id: source for source in base_bundle.sources}
    for metric in metrics.values():
        if metric["value"] is None:
            continue
        availability = [datetime.fromisoformat(metric["available_at"].replace("Z", "+00:00"))]
        availability.extend(sources[sid].available_at for sid in metric["source_ids"])
        metric["available_at"] = iso(max(availability))
    merged = {name: metric for name, metric in raw_asset["metrics"].items() if name not in _DAILY_METRICS}
    merged.update(metrics)
    raw_asset["metrics"] = merged
    raw_asset["session"] = suffix[-1].session.isoformat()  # leave stale sessions visibly stale
    return raw_asset


def _contiguous_suffix(bars: list[PriceBar], calendar: dict[date, dict]) -> list[PriceBar]:
    """Contiguous calendar-session suffix ending at the latest known session.

    Bars are already eligible (available_at/close_at <= as_of) and validated
    against the calendar. Contiguity means adjacency in the supplied ordered
    calendar; exchange holidays are never inferred from weekdays. A missing
    session or an adjustment-version change breaks the window. When the newest
    session carries raw plus one adjusted version, use the adjusted version.
    Multiple adjusted versions at that session are ambiguous and rejected.
    Row order never selects the research vintage.
    """
    latest_session = max(bar.session for bar in bars)
    versions = {bar.adjustment_version for bar in bars if bar.session == latest_session}
    adjusted = versions - {"raw"}
    if len(adjusted) > 1:
        raise ValidationError(
            f"{bars[0].instrument_id} {latest_session}: ambiguous adjustment versions; "
            "supply one adjusted research vintage (raw execution rows may coexist)"
        )
    version = next(iter(adjusted)) if adjusted else "raw"
    by_session = {bar.session: bar for bar in bars if bar.adjustment_version == version}
    dates = sorted(calendar)
    index = dates.index(latest_session)  # rows were validated against the calendar
    suffix = [by_session[latest_session]]
    position = index - 1
    while position >= 0 and dates[position] in by_session:
        suffix.append(by_session[dates[position]])
        position -= 1
    suffix.reverse()
    return suffix


def _load_calendar(path: str | Path) -> dict[date, dict[str, datetime]]:
    raw = load_json(path)
    root = obj(raw, "sessions-file", {"sessions"})
    entries = sequence(root["sessions"], "sessions", limit=5000)
    calendar: dict[date, dict[str, datetime]] = {}
    ordered: list[date] = []
    for i, entry in enumerate(entries):
        entry_path = f"sessions[{i}]"
        fields = obj(entry, entry_path, {"session", "open_at", "close_at"})
        session = day(fields["session"], f"{entry_path}.session")
        open_at = timestamp(fields["open_at"], f"{entry_path}.open_at")
        close_at = timestamp(fields["close_at"], f"{entry_path}.close_at")
        if not open_at < close_at:
            raise ValidationError(f"{entry_path}: open_at must be before close_at")
        if open_at.astimezone(IST).date() != session or close_at.astimezone(IST).date() != session:
            raise ValidationError(
                f"{entry_path}: open_at and close_at must fall on the session date in India (+05:30)"
            )
        if session in calendar:
            raise ValidationError(f"{entry_path}: duplicate session {session.isoformat()}")
        if ordered and session <= ordered[-1]:
            raise ValidationError(f"{entry_path}: sessions must be strictly ordered by date")
        calendar[session] = {"open_at": open_at, "close_at": close_at}
        ordered.append(session)
    if not calendar:
        raise ValidationError("sessions: at least one session is required")
    return calendar


def _check_base_against_calendar(base_bundle: ResearchBundle, calendar: dict[date, dict]) -> None:
    if base_bundle.last_session not in calendar:
        raise ValidationError(
            f"base bundle: last_session {base_bundle.last_session.isoformat()} is not in the supplied calendar"
        )
    if calendar[base_bundle.last_session]["close_at"] != base_bundle.session_close_at:
        raise ValidationError("base bundle: session_close_at does not match the calendar close time for last_session")
    closed = [session for session, entry in calendar.items() if entry["close_at"] <= base_bundle.as_of]
    if not closed:
        raise ValidationError("base bundle: the calendar has no session closed by as_of")
    if max(closed) != base_bundle.last_session:
        raise ValidationError(
            "base bundle: last_session must be the most recent session closed by as_of "
            f"(calendar gives {max(closed).isoformat()})"
        )


def _load_price_rows(path: str | Path, base_bundle: ResearchBundle, calendar: dict) -> list[PriceBar]:
    prices_path = Path(path)
    try:
        with prices_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                raise ValidationError(f"{prices_path.name}: file is empty") from None
            if header != list(CSV_HEADER):
                raise ValidationError(
                    f"{prices_path.name}: header must be exactly {','.join(CSV_HEADER)}"
                )
            instruments = {asset.instrument_id for asset in base_bundle.assets}
            source_ids = {source.id for source in base_bundle.sources}
            bars: list[PriceBar] = []
            seen: set[tuple[str, date, str]] = set()
            for number, row in enumerate(reader, start=2):
                if not row:
                    continue
                bars.append(_parse_row(
                    row, number, prices_path.name, base_bundle, calendar, instruments, source_ids, seen,
                ))
            return bars
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValidationError(f"Cannot read {prices_path.name}: {exc}") from exc


def _parse_row(
    row: list[str], number: int, filename: str, base_bundle: ResearchBundle,
    calendar: dict, instruments: set[str], source_ids: set[str], seen: set,
) -> PriceBar:
    row_path = f"{filename} row {number}"
    if len(row) != len(CSV_HEADER):
        raise ValidationError(f"{row_path}: expected {len(CSV_HEADER)} fields, found {len(row)}")
    raw = dict(zip(CSV_HEADER, (cell.strip() for cell in row)))
    for column in ("instrument_id", "source_id", "adjustment_version"):
        if not raw[column]:
            raise ValidationError(f"{row_path}: {column} must not be empty")
    if raw["instrument_id"] not in instruments:
        raise ValidationError(
            f"{row_path}: instrument {raw['instrument_id']} is not declared in the base bundle"
        )
    session = day(raw["session"], f"{row_path}: session")
    if session not in calendar:
        raise ValidationError(f"{row_path}: session {session.isoformat()} is not in the supplied calendar")
    entry = calendar[session]
    open_at = timestamp(raw["open_at"], f"{row_path}: open_at")
    close_at = timestamp(raw["close_at"], f"{row_path}: close_at")
    available_at = timestamp(raw["available_at"], f"{row_path}: available_at")
    if open_at != entry["open_at"] or close_at != entry["close_at"]:
        raise ValidationError(
            f"{row_path}: open_at/close_at must match the calendar times for {session.isoformat()}"
        )
    if available_at < close_at:
        raise ValidationError(f"{row_path}: available_at must be at or after close_at")
    open_ = _decimal(raw["open"], f"{row_path}: open", positive=True)
    high = _decimal(raw["high"], f"{row_path}: high", positive=True)
    low = _decimal(raw["low"], f"{row_path}: low", positive=True)
    close = _decimal(raw["close"], f"{row_path}: close", positive=True)
    volume = _int(raw["volume"], f"{row_path}: volume")
    turnover = _decimal(raw["turnover_inr"], f"{row_path}: turnover_inr")
    if high < low or high < open_ or high < close or low > open_ or low > close:
        raise ValidationError(f"{row_path}: OHLC geometry violated (require low <= open/close <= high)")
    if raw["source_id"] not in source_ids:
        raise ValidationError(f"{row_path}: source {raw['source_id']} is not declared in the base bundle")
    version = raw["adjustment_version"]
    key = (raw["instrument_id"], session, version)
    if key in seen:
        raise ValidationError(
            f"{row_path}: duplicate bar for {raw['instrument_id']} on {session.isoformat()} "
            f"with adjustment_version {version}"
        )
    seen.add(key)
    return PriceBar(
        instrument_id=raw["instrument_id"], session=session, open_at=open_at, close_at=close_at,
        available_at=available_at, open=open_, high=high, low=low, close=close, volume=volume,
        turnover_inr=turnover, source_id=raw["source_id"], adjustment_version=version,
    )


def _decimal(text: str, path: str, *, positive: bool = False) -> Decimal:
    try:
        value = Decimal(text)
    except (DecimalException, ValueError) as exc:
        raise ValidationError(f"{path}: expected a finite decimal number") from exc
    if not value.is_finite():
        raise ValidationError(f"{path}: expected a finite decimal number")
    if positive and value <= 0:
        raise ValidationError(f"{path}: must be positive")
    if not positive and value < 0:
        raise ValidationError(f"{path}: must not be negative")
    return value


def _int(text: str, path: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise ValidationError(f"{path}: expected an integer") from exc
    if value < 0:
        raise ValidationError(f"{path}: must not be negative")
    return value


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oraculum.providers.csv_provider",
        description="Build a canonical ResearchBundle from a supplied CSV price tape (offline).",
    )
    p.add_argument("--prices", required=True)
    p.add_argument("--base-bundle", required=True, dest="base_bundle")
    p.add_argument("--sessions", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--force", action="store_true", help="Replace an existing output file")
    return p


def _check_output_paths(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    protected = {Path(p).resolve() for p in (args.prices, args.base_bundle, args.sessions)}
    if output in protected or (output.exists() and any(output.samefile(p) for p in protected if p.exists())):
        raise ValidationError("Output path must differ from the input CSV, base bundle and calendar")
    if output.exists() and not args.force:
        raise ValidationError(f"Output already exists: {output}; use --force to replace it")


def _write_bundle(bundle: ResearchBundle, args: argparse.Namespace) -> None:
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    _check_output_paths(args)
    with target.open("w" if args.force else "x", encoding="utf-8", newline="\n") as handle:
        json.dump(bundle.to_dict(), handle, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        _check_output_paths(args)
        bundle = build_merged_bundle(args.prices, args.base_bundle, args.sessions)
        _write_bundle(bundle, args)
        print(
            f"WROTE {args.output}: {len(bundle.assets)} instruments, "
            f"{len(bundle.sources)} sources, mode={bundle.mode}"
        )
        return 0
    except (ValidationError, OSError) as exc:
        print(f"Oraculum error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
