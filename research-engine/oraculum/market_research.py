"""Automatic real-data PRICE/VOLUME research, separate from the buy engine.

No model, brokerage, API key or external Python package is needed. All supported
stocks in the latest EQ/STK/F1 file are inspected; no fundamentals are invented.
The existing bounded-factor buy gates and paper-order permissions are untouched.
"""
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import datetime
import csv
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from urllib.error import HTTPError, URLError

from .contracts import UTC, ValidationError, day, iso, timestamp
from .features import BasicPriceFeatureBuilder
from .local_data import MarketStore, download_bhavcopy, snapshot_bars
from .market_calendar import closed_window, research_calendar
from .serialization import canonical_json, digest, load_json

ALGORITHM = "nse-price-watchlist-v1"
SETTINGS = {"history_sessions": 60, "minimum_consecutive_sessions": 50,
            "minimum_turnover_20d_inr": 50_000_000, "maximum_volatility_20d": 0.80,
            "maximum_absolute_daily_move_50d": 0.20, "highlight_limit": 10,
            "minimum_highlight_score": 55,
            "weights": {"momentum": 0.45, "trend": 0.35, "volume_confirmation": 0.20}}
LIMITATIONS = [
    "Price/volume research only: fundamentals, valuation, news and announcements are not assessed.",
    "Raw prices are not adjusted for splits, bonuses or dividends. The large-move exclusion is only a heuristic and misses some actions.",
    "Scores are transparent, unvalidated heuristics, not probabilities, return forecasts or buy recommendations.",
    "This report cannot authorize paper orders. The full research engine retains its separate data and risk gates.",
    "Universe is currently traded NSE EQ/STK/F1 rows with supported identifiers, not all listed securities or BSE.",
    "Today's universe and locally received history cannot establish past investment performance; no historical availability is backdated.",
    "Public end-of-day downloads can be delayed or unavailable. This is not a live-price feed.",
]


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=".oraculum-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        # Windows can briefly deny replacement while another reader or sync
        # process holds a handle. Retry without deleting/chmod-ing the old file.
        for delay in (0, .05, .15, .35, .75, 1.5):
            if delay:
                time.sleep(delay)
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if delay == 1.5:
                    raise
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Cleanup must never mask the write error or delete the old report.


def write_json(path, value):
    atomic_text(Path(path), canonical_json(value) + "\n")


@contextmanager
def workflow_lock(folder):
    """A SQLite lock releases on process exit, including a crashed download."""
    folder.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(folder / "workflow.sqlite3", timeout=0)) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise ValidationError("Another research update is running. Wait for it to finish before rerunning.") from exc
        try:
            from .activity import heartbeat
            with heartbeat(folder) as activity:
                yield activity
        finally:
            conn.rollback()


def clip(value, low=-1.0, high=1.0):
    return min(high, max(low, value))


def technical_score(metrics):
    """Fixed, disclosed weights. Volume only confirms the direction of momentum."""
    m = metrics["momentum_20d"]
    volume_sign = 1 if m > 0 else -1 if m < 0 else 0
    components = {
        "momentum": 22.5 * clip(m / 0.20),
        "trend": 17.5 * clip(metrics["trend_50d"] / 0.15),
        "volume_confirmation": 10.0 * volume_sign * clip((metrics["volume_ratio_20d"] - 1) / 2, 0, 1),
        "volatility_penalty": -15.0 * clip((metrics["volatility_20d_annualized"] - 0.20) / 0.60, 0, 1),
    }
    return round(clip(50 + sum(components.values()), 0, 100), 6), {k: round(v, 6) for k, v in components.items()}


def max_drawdown(closes):
    peak, worst = closes[0], 0.0
    for price in closes:
        peak = max(peak, price)
        worst = min(worst, price / peak - 1)
    return worst


def build_research(snapshots, calendar, calendar_raw, calendar_info, *, as_of, window=None):
    required_window = closed_window(calendar, as_of, SETTINGS["history_sessions"])
    if window is not None and window != required_window:
        raise ValidationError("Research window must end at the latest completed session and contain the full required history")
    window = required_window
    expected = set(window)
    mapped = {}
    for snap in snapshots:
        session = day(snap["session"], "session")
        if session in mapped:
            raise ValidationError("Duplicate price snapshot in research window")
        if session not in expected:
            continue
        if timestamp(snap["received_at"], "received_at") > as_of:
            raise ValidationError("Price snapshot had not been received at the research cutoff")
        mapped[session] = snap
    missing = sorted(expected - mapped.keys())
    if missing:
        raise ValidationError("Missing scheduled sessions: " + ", ".join(map(str, missing)) + ". No research ranking was published.")
    latest = mapped[window[-1]]
    symbols = {r["symbol"] for r in latest["rows"]}
    history = defaultdict(dict)
    for session in window:
        for bar in snapshot_bars(mapped[session], calendar[session], symbols):
            history[bar.instrument_id.removeprefix("NSE:")][session] = bar
    assets, builder = [], BasicPriceFeatureBuilder()
    for symbol in sorted(symbols):
        # Missing/no-trade rows break continuity; never bridge gaps or fill prices.
        tail = []
        for session in reversed(window):
            bar = history[symbol].get(session)
            if bar is None:
                break
            tail.append(bar)
        tail.reverse()
        metrics = {k: v["value"] for k, v in builder.build_metrics(tail, as_of=as_of).items()}
        closes = [float(b.close) for b in tail]
        metrics["return_1d"] = closes[-1] / closes[-2] - 1 if len(closes) >= 2 else None
        metrics["drawdown_50d"] = max_drawdown(closes[-50:]) if len(closes) >= 50 else None
        # Decimal prices keep exactly-20% moves on the excluded side of the boundary.
        recent = tail[-50:]
        metrics["max_absolute_daily_move_50d"] = (float(max(abs(b.close / a.close - 1)
            for a, b in zip(recent, recent[1:]))) if len(recent) == 50 else None)
        blockers, warnings, reasons = [], [], []
        if len(tail) < SETTINGS["minimum_consecutive_sessions"]:
            blockers.append(f"Only {len(tail)} consecutive traded sessions; 50 required")
        if metrics.get("turnover_20d_inr") is not None and metrics["turnover_20d_inr"] < SETTINGS["minimum_turnover_20d_inr"]:
            blockers.append("20-session average turnover below INR 5 crore")
        if metrics.get("volatility_20d_annualized") is not None and metrics["volatility_20d_annualized"] > SETTINGS["maximum_volatility_20d"]:
            blockers.append("Annualized 20-session volatility exceeds 80%")
        if metrics["max_absolute_daily_move_50d"] is not None and metrics["max_absolute_daily_move_50d"] >= SETTINGS["maximum_absolute_daily_move_50d"]:
            blockers.append("At least one raw daily move is 20% or larger; check corporate actions or extreme price moves")
        score, components = (None, {}) if blockers else technical_score(metrics)
        if not blockers:
            reasons = [f"20-session price return {metrics['momentum_20d']:+.2%}",
                       f"Close {metrics['trend_50d']:+.2%} versus its 50-session average",
                       f"Latest volume {metrics['volume_ratio_20d']:.2f}x the previous 20-session average",
                       f"20-session average turnover INR {metrics['turnover_20d_inr'] / 1e7:.2f} crore"]
            if metrics["volatility_20d_annualized"] > .40:
                warnings.append("High recent price volatility")
            if metrics["trend_50d"] > .15:
                warnings.append("Price is more than 15% above its 50-session average; possible overextension")
            if metrics["volume_ratio_20d"] < 1:
                warnings.append("Latest volume is below its previous 20-session average")
            if metrics["return_1d"] is not None and metrics["return_1d"] < 0:
                warnings.append("Price fell in the latest session")
        assets.append({"symbol": symbol, "instrument_id": "NSE:" + symbol,
                       "status": "excluded" if blockers else "eligible", "rank": None,
                       "highlight": False, "score": score, "components": components,
                       "consecutive_sessions": len(tail), "metrics": metrics,
                       "reasons": reasons, "blockers": blockers, "warnings": warnings})
    eligible = sorted((a for a in assets if not a["blockers"]), key=lambda a: (-a["score"], a["symbol"]))
    for rank, asset in enumerate(eligible, 1):
        asset["rank"] = rank
    positive = [a for a in eligible if a["metrics"]["momentum_20d"] > 0 and a["metrics"]["trend_50d"] > 0
                and a["score"] >= SETTINGS["minimum_highlight_score"]]
    highlights = positive[:SETTINGS["highlight_limit"]]
    for asset in highlights:
        asset["highlight"] = True
    assets.sort(key=lambda a: (a["rank"] is None, a["rank"] or 0, a["symbol"]))
    moves = [a["metrics"]["return_1d"] for a in assets if a["metrics"]["return_1d"] is not None]
    report = {"report_schema": "oraculum-price-research-v1", "algorithm": ALGORITHM,
              "mode": "imported", "as_of": iso(as_of), "last_session": str(window[-1]),
              "session_close_at": iso(calendar[window[-1]]["close_at"]),
              "history_start": str(window[0]), "history_sessions": len(window),
              "calendar": {**calendar_info, "coverage_start": calendar_raw["coverage_start"],
                           "coverage_end": calendar_raw["coverage_end"], "source_uri": calendar_raw["source_uri"],
                           "sha256": digest(calendar_raw), "schedule": calendar_raw},
              "settings": dict(SETTINGS), "limitations": list(LIMITATIONS),
              "coverage": {"price_volume": "available", "fundamentals": "not_assessed",
                           "news_sentiment": "not_assessed", "corporate_announcements": "not_assessed",
                           "corporate_action_adjustments": "not_available"},
              "counts": {"scanned": len(assets), "eligible": len(eligible), "excluded": len(assets) - len(eligible),
                         "positive_setups": len(positive), "highlights": len(highlights),
                         "advanced": sum(x > 0 for x in moves), "declined": sum(x < 0 for x in moves),
                         "unchanged": sum(x == 0 for x in moves), "breadth_observations": len(moves)},
              "skipped_latest_rows": latest["skipped"],
              "exclusion_counts": dict(Counter(b for a in assets for b in a["blockers"])),
              "highlights": [a["instrument_id"] for a in highlights], "assets": assets,
              "sources": [{k: mapped[s][k] for k in ("session", "source_id", "uri", "sha256", "received_at")}
                          for s in window]}
    report["report_id"] = digest(report)
    return report


def report_csv(report):
    if report.get("report_schema") in ("oraculum-integrated-research-v1", "oraculum-integrated-research-v2"):
        from .integrated_view import integrated_csv
        return integrated_csv(report)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    fields = ["close_inr", "return_1d", "momentum_20d", "trend_50d", "volume_ratio_20d",
              "turnover_20d_inr", "volatility_20d_annualized", "drawdown_50d"]
    writer.writerow(["session", "instrument", "status", "rank", "highlight", "score", *fields, "blockers", "warnings"])
    for asset in report["assets"]:
        writer.writerow([report["last_session"], asset["instrument_id"], asset["status"], asset["rank"],
                         asset["highlight"], asset["score"], *[asset["metrics"].get(f) for f in fields],
                         "; ".join(asset["blockers"]), "; ".join(asset["warnings"])])
    return buffer.getvalue()


def read_research(folder, report_id=None):
    folder = Path(folder) / "research"
    if report_id is None:
        if not (folder / "latest.json").is_file():
            return None
        report_id = load_json(folder / "latest.json").get("report_id")
    if not isinstance(report_id, str) or len(report_id) != 64 or any(c not in "0123456789abcdef" for c in report_id):
        raise ValidationError("Invalid research report ID")
    report = load_json(folder / f"{report_id}.json")
    if (not isinstance(report, dict) or report.get("report_schema") not in ("oraculum-price-research-v1", "oraculum-integrated-research-v1", "oraculum-integrated-research-v2")
            or report.get("report_id") != report_id
            or digest({k: v for k, v in report.items() if k != "report_id"}) != report_id):
        raise ValidationError("Research report integrity check failed")
    return report


def research_status(folder):
    path = Path(folder) / "research/status.json"
    from .activity import observed_status
    return observed_status(folder, load_json(path)) if path.is_file() else None


def save_research(folder, report):
    # JSON is the immutable record. The pointer moves only after all outputs exist.
    from .research_view import research_html
    root = folder / "research"
    target = root / f"{report['report_id']}.json"
    if target.exists():
        read_research(folder, report["report_id"])
    else:
        write_json(target, report)
    atomic_text(root / f"{report['report_id']}.csv", report_csv(report))
    atomic_text(root / f"{report['report_id']}.html", research_html(report, standalone=True))
    from .research_history import ResearchHistory
    ResearchHistory(folder).add(report)
    write_json(root / "latest.json", {"report_id": report["report_id"], "last_session": report["last_session"]})
    return target


def run_research(folder, *, offline=False, calendar_path=None, progress=print,
                 downloader=None, clock=None, pause=None, integrator=None, collect_news=False):
    folder = Path(folder)
    downloader, clock, pause = downloader or download_bhavcopy, clock or (lambda: datetime.now(UTC)), pause or time.sleep
    with workflow_lock(folder) as activity:
        status = {"state": "running", "started_at": iso(clock()), "expected_session": None,
                  "completed_sessions": 0, "total_sessions": SETTINGS["history_sessions"], "error": None,
                  "activity_id": activity["id"], "phase": "Preparing price history"}
        status_path = folder / "research/status.json"
        status_unavailable = False

        def record_status(*, final=False):
            nonlocal status_unavailable
            if status_unavailable and not final:
                return
            try:
                write_json(status_path, status)
            except OSError as exc:
                if not status_unavailable:
                    progress(f"Progress file unavailable ({exc}). Continuing; report publication still requires a successful save.")
                status_unavailable = True

        output = progress
        def note(message):
            status.update(last_message=str(message)[:1000], updated_at=iso(clock()))
            record_status()
            output(message)

        # A progress display must not abort or mask the actual download/report result.
        record_status()
        try:
            start = clock()
            calendar, raw, info = research_calendar(start, calendar_path)
            window = closed_window(calendar, start, SETTINGS["history_sessions"])
            status["expected_session"] = str(window[-1])
            record_status()
            store = MarketStore(folder / "market.sqlite3")
            note(f"NSE price/volume research | Latest closed session: {window[-1]}")
            note(f"Preparing {len(window)} sessions ({window[0]} to {window[-1]}). Cached files are reused.")
            downloaded = 0
            # Latest first: an unpublished final file fails promptly, not after backfill.
            for index, session in enumerate(reversed(window), 1):
                cached = store.has_session(session)
                if cached:
                    note(f"[{index}/{len(window)}] {session}: cached")
                elif offline:
                    raise ValidationError(f"Offline cache is missing {session}. Run research online to resume.")
                else:
                    note(f"[{index}/{len(window)}] {session}: downloading final bhavcopy...",)
                    if downloaded:
                        pause(.35)
                    for attempt in range(2):
                        try:
                            content, uri = downloader(session)
                            break
                        except (OSError, ValidationError) as exc:
                            cause = exc.__cause__ or exc
                            # One short retry for a broken connection/timeout.
                            # HTTP denials, absent files and malformed data are
                            # never retried or interpreted as exchange holidays.
                            transient = (isinstance(cause, (TimeoutError, ConnectionError)) or
                                         isinstance(cause, URLError) and not isinstance(cause, HTTPError))
                            if attempt == 0 and transient:
                                note(f"{session}: connection interrupted; retrying once in 2 seconds...")
                                pause(2)
                                continue
                            raise ValidationError(f"Required session {session}: {exc}") from exc
                    store.ingest(content, session, uri, received_at=clock())
                    downloaded += 1
                status["completed_sessions"] = index
                if not cached or index % 10 == 0 or index == len(window):
                    record_status()
            as_of = clock()
            current, _, _ = research_calendar(as_of, calendar_path)
            if closed_window(current, as_of, SETTINGS["history_sessions"])[-1] != window[-1]:
                raise ValidationError("Another session closed during setup. Rerun research to include its final file.")
            note("Computing features and exclusions for every supported stock in the latest file...")
            if integrator is None:
                report = build_research(store.snapshots(start=window[0], end=window[-1]), calendar, raw, info,
                                        as_of=as_of, window=window)
            else:
                status["phase"] = "Loading corporate actions and financial statements"
                record_status()
                report = integrator(folder, store, calendar, raw, info, window,
                                    offline=offline, progress=note, clock=clock, pause=pause)
            if collect_news:
                from .market_events import collect_report_events
                status["phase"] = "Collecting news and announcements"
                record_status()
                report["event_coverage"] = collect_report_events(folder,report,offline=offline,clock=clock,progress=note)
                report["as_of"] = iso(clock())
                report["report_id"] = digest({k:v for k,v in report.items() if k != "report_id"})
            final_calendar, _, _ = research_calendar(clock(), calendar_path)
            if closed_window(final_calendar, clock(), SETTINGS["history_sessions"])[-1] != window[-1]:
                raise ValidationError("Another session closed during the update. Rerun before publishing.")
            # Separate generated calendar; never replace the user's manual setup.
            write_json(folder / "calendar-auto.json", raw)
            target = save_research(folder, report)
            status.update(state="ready", finished_at=iso(clock()), report_id=report["report_id"],
                          downloaded_sessions=downloaded, phase="Complete")
            record_status(final=True)
            note(f"Saved {report['counts']['scanned']} stocks; {report['counts']['eligible']} pass data/liquidity/risk filters; "
                     f"{report['counts']['highlights']} positive technical highlights.")
            for asset in report["assets"]:
                if asset["highlight"]:
                    note(f"  {asset['rank']:>2}. {asset['symbol']:<15} {asset['score']:6.2f} | " + " | ".join(asset["reasons"][:2]))
            if "ranking_policy" in report:
                note(f"Combined ranking: {report['counts']['combined_eligible']} complete profiles, "
                         f"{report['counts']['combined_candidates']} candidates, {report['counts']['combined_highlights']} highlights.")
                ranked = sorted((a for a in report["assets"] if a["combined"]["highlight"]),key=lambda a:a["combined"]["rank"])
                for asset in ranked:
                    note(f"  Combined {asset['combined']['rank']:>2}. {asset['symbol']:<15} {asset['combined']['score']:6.2f}")
            note(f"Report: {target.with_suffix('.html').resolve()}")
            note("Research observations only; no buy orders are created. See the report for evidence coverage and unassessed inputs.")
            return report
        except (Exception, KeyboardInterrupt) as exc:
            status.update(state="failed", finished_at=iso(clock()), error=str(exc) or type(exc).__name__)
            record_status(final=True)
            raise
