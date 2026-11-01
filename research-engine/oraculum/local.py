"""Zero-subscription local operations. Run: python -m oraculum.local --help."""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal, DecimalException
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import sys

from .contracts import IST, UTC, ValidationError, day, iso
from .local_ai import analyze_document
from .local_data import (
    MAX_FILE, MarketStore, decimal_amount, download_bhavcopy, load_calendar, scan_local, snapshot_bars,
)
from .local_web import serve
from .local_paths import data_directory, recover_market_cache
from .paper.ledger import PaperLedger, plain
from .pipeline import build_run
from .providers.csv_provider import _load_calendar, build_merged_bundle
from .reporting import terminal_report, write_report
from .repository import RunRepository
from .serialization import load_json

LOCAL_RELEASE = "0.8.4"
PROJECT = Path(__file__).resolve().parents[1]


def parser():
    root = argparse.ArgumentParser(description="Oraculum local operations — no broker or paid AI API")
    root.add_argument("--version", action="version", version=f"Oraculum local {LOCAL_RELEASE}; core 0.1.0")
    commands = root.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    # Parent argparse actions are shared: never change their defaults on a child.
    # Choose the workspace after parsing, once the command is known.
    common.add_argument("--data-dir", default=None,
                        help="Override workspace (Windows: LOCALAPPDATA/Oraculum/data; demo is separate)")
    commands.add_parser("init", parents=[common], help="Create editable setup files; preserve existing files")
    commands.add_parser("doctor", parents=[common], help="Show Python, disk and optional Ollama availability")
    p = commands.add_parser("demo", parents=[common], help="Persist and replay a fully fictional workflow")
    p = commands.add_parser("repair-local", parents=[common], help="Recover price downloads into the corrected local workspace")
    p.add_argument("--from-dir", action="append", help="Old data folder; may repeat. Default: project data/demo and data/local")
    p = commands.add_parser("research", parents=[common], help="Automatically backfill NSE history and rank real price/volume research leads")
    p.add_argument("--offline", action="store_true", help="Use cached files only; fail if any required session is missing")
    p.add_argument("--calendar", help="Advanced: explicit complete exchange calendar; otherwise use the bundled reviewed schedule")
    p.add_argument("--integrated", action="store_true", help="Add supported corporate-action adjustments and sourced financial statements")
    p.add_argument("--max-filings", type=int, default=60, help="Integrated mode: maximum new filing attempts per run, 0–10000 (default 60); rerun to resume")
    p = commands.add_parser("auto-daily", parents=[common], help="Combined ranking, immutable history and automatic forward paper evaluation")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--calendar", help="Complete sourced exchange calendar override")
    p.add_argument("--max-filings", type=int, default=60)
    p.add_argument("--no-paper", action="store_true", help="Refresh research and history only; do not initialize or advance the forward experiment")
    p.add_argument("--cash", default="100000.00", help="Initial virtual cash on first run only; an existing experiment is preserved")
    p = commands.add_parser("news-refresh", parents=[common], help="Collect free news and announcements using the latest report's company identities")
    p.add_argument("--offline", action="store_true", help="Inspect cached feeds without network requests")
    p = commands.add_parser("news-status", parents=[common], help="Inspect feed health without fetching data")
    p.add_argument("--audit", action="store_true", help="Verify stored feed bytes and event revision hashes")
    p = commands.add_parser("coverage-status", parents=[common], help="Read saved coverage and current workflow health; no downloads")
    p.add_argument("--report", help="Saved report ID; defaults to latest")
    p.add_argument("--symbol", default="", help="Filter by symbol or company name")
    from .coverage import FILTERS as COVERAGE_FILTERS
    p.add_argument("--filter", default="all", choices=COVERAGE_FILTERS)
    from .ai_runtime import DEFAULT_MODEL
    for name in ("ai-doctor", "ai-evaluate"):
        p = commands.add_parser(name, parents=[common], help="Inspect local model" if name == "ai-doctor" else "Run fictional model checks")
        p.add_argument("--model")
        p.add_argument("--port", type=int)
        if name == "ai-evaluate":
            p.add_argument("--timeout", type=int)
            p.add_argument("--extended", action="store_true", help="Run eight fictional model checks instead of three")
    p = commands.add_parser("ai-configure", parents=[common], help="Pin installed local weights and enable bounded briefs")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--port", type=int, default=11434)
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--budget", type=int, default=1800)
    commands.add_parser("ai-disable", parents=[common], help="Stop generation and preserve saved evidence")
    p = commands.add_parser("ai-status", parents=[common], help="Read local AI setup and progress")
    p.add_argument("--audit", action="store_true")
    p = commands.add_parser("ai-refresh", parents=[common], help="Generate evidence-selected briefs from a saved report")
    p.add_argument("--symbol")
    p.add_argument("--report", help="Saved report ID; defaults to latest")
    p.add_argument("--limit", type=int)
    p.add_argument("--retry", action="store_true", help="Retry failed/rejected attempts; reuse accepted selections")
    commands.add_parser("forward-status", parents=[common], help="Inspect the automatic forward experiment")
    p = commands.add_parser("research-history", parents=[common], help="List saved automatic research reports")
    p.add_argument("--recover", action="store_true", help="Index preserved older/interrupted reports without changing their contents")
    p.add_argument("--limit", type=int, default=100)
    for operation in ("install", "status", "remove"):
        commands.add_parser("schedule-"+operation, parents=[common], help="Windows current-user daily task: "+operation)
    for name in ("import-nse", "fetch-nse"):
        p = commands.add_parser(name, parents=[common])
        p.add_argument("--session", required=True, help="YYYY-MM-DD, an actual completed exchange session")
        if name == "import-nse":
            p.add_argument("--input", required=True, help="CM UDiFF final CSV or ZIP")
    for name in ("scan", "daily"):
        p = commands.add_parser(name, parents=[common])
        p.add_argument("--watchlist", help="Default: DATA_DIR/watchlist.json")
        p.add_argument("--calendar", help="Default: DATA_DIR/calendar.json")
        p.add_argument("--supplement", help="Default: DATA_DIR/supplement.json, if present")
        p.add_argument("--config", help="Optional complete research engine configuration")
        if name == "daily":
            p.add_argument("--download", action="store_true", help="Fetch latest missing final NSE snapshot")
            p.add_argument("--settle-paper", action="store_true", help="Settle previously queued virtual orders")
    p = commands.add_parser("serve", parents=[common], help="Read-only local report viewer")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open-browser", action="store_true")
    p = commands.add_parser("paper-init", parents=[common])
    p.add_argument("--cash", default="100000.00")
    p.add_argument("--mode", choices=["imported", "synthetic"], default="imported")
    commands.add_parser("paper-status", parents=[common])
    p = commands.add_parser("paper-order", parents=[common], help="Record an explicit virtual order now")
    p.add_argument("--order-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--instrument", required=True)
    p.add_argument("--side", choices=["buy", "sell"], required=True)
    p.add_argument("--quantity", type=int, required=True)
    p = commands.add_parser("paper-settle", parents=[common])
    p.add_argument("--session", required=True)
    p.add_argument("--calendar")
    p.add_argument("--fee-bps", default="10")
    p.add_argument("--slippage-bps", default="10")
    p = commands.add_parser("analyze-text", parents=[common], help="Optional local Ollama draft; does not affect rankings")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True, help="New JSON file; existing files are never replaced")
    p.add_argument("--model", required=True, help="Installed local Ollama model name")
    p.add_argument("--instrument", required=True)
    p.add_argument("--source-uri", required=True)
    p.add_argument("--kind", choices=["news", "announcement"], required=True)
    p.add_argument("--port", type=int, default=11434)
    return root


def initialize(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("watchlist.json", "calendar.json", "supplement.json"):
        target = folder / name
        if not target.exists():
            with target.open("x", encoding="utf-8") as handle:
                handle.write((PROJECT / "examples/local" / name).read_text(encoding="utf-8"))
    print(f"Setup files: {folder.resolve()}")
    print("Review watchlist.json; replace calendar.json with a complete, sourced exchange calendar. See docs/LOCAL.md.")


def save_report(report, folder):
    saved = RunRepository(folder / "runs.sqlite3").save(report)
    for suffix, markdown in (("json", False), ("md", True)):
        path = folder / "reports" / f"{saved['run_id']}.{suffix}"
        if not path.exists():
            write_report(saved, path, markdown=markdown)
    print(terminal_report(saved))
    print(f"Saved: {folder / 'reports'}")
    return saved


def settle_cached(folder, session, calendar_path, *, fee="10", slippage="10"):
    now = datetime.now(UTC)
    calendar, _ = load_calendar(calendar_path, as_of=now)
    if session not in calendar:
        raise ValidationError("Requested paper session is not in the calendar")
    ledger = PaperLedger(folder / "paper.sqlite3")
    status = ledger.status()
    if status["mode"] != "imported":
        raise ValidationError("Real NSE snapshots cannot settle a synthetic ledger")
    # Include only instruments already ordered before this open; stable on retries.
    from .contracts import timestamp
    symbols = {o["instrument_id"].removeprefix("NSE:") for o in status["orders"]
               if timestamp(o["submitted_at"], "submitted_at") < calendar[session]["open_at"]}
    snapshots = MarketStore(folder / "market.sqlite3").snapshots(start=session, end=session)
    if not snapshots:
        raise ValidationError("Import the execution session's final raw bhavcopy first")
    bars = snapshot_bars(snapshots[0], calendar[session], symbols)
    return ledger.settle(session, bars, calendar, fee_bps=decimal_amount(fee, "fee bps"),
                         slippage_bps=decimal_amount(slippage, "slippage bps"), now=now)


def persisted_demo(folder: Path):
    from .interfaces import PriceBar
    fixtures = PROJECT / "examples/qwen"
    bundle = build_merged_bundle(fixtures / "prices.csv", fixtures / "base.json", fixtures / "sessions.json")
    # Fixed fictional timestamps intentionally make this demonstration replayable.
    report = save_report(build_run(bundle, generated_at=bundle.as_of), folder)
    ledger = PaperLedger(folder / "paper.sqlite3")
    ledger.initialize(Decimal("10000.00"), "synthetic", now=bundle.as_of)
    ledger.submit(RunRepository(folder / "runs.sqlite3", create=False), order_id="DEMO-PAPER-001",
                  instrument_id=report["shortlist"][0], side="buy", quantity=3,
                  run_id=report["run_id"], now=bundle.as_of)
    bar = PriceBar(report["shortlist"][0], date(2026, 10, 12),
        datetime(2026, 10, 12, 9, 15, tzinfo=IST), datetime(2026, 10, 12, 15, 30, tzinfo=IST),
        datetime(2026, 10, 12, 15, 35, tzinfo=IST), Decimal("130"), Decimal("132"), Decimal("128"),
        Decimal("131"), 100000, Decimal("13000000"), "fictional-paper-session", "raw")
    calendar = _load_calendar(fixtures / "sessions.json")
    calendar[bar.session] = {"open_at": bar.open_at, "close_at": bar.close_at}
    result = ledger.settle(bar.session, [bar], calendar, now=bar.available_at)
    print("FICTIONAL PERSISTENT PAPER DEMO (safe to rerun):")
    print(json.dumps(result["result"], indent=2))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        folder = data_directory(args.command, args.data_dir)
        if sys.version_info < (3, 12):
            raise ValidationError("Python 3.12 or newer is required")
        if args.command == "init":
            initialize(folder)
        elif args.command == "repair-local":
            sources = args.from_dir or [PROJECT / "data/demo", PROJECT / "data/local"]
            recover_market_cache(folder, sources, progress=lambda message: print(message, flush=True))
        elif args.command == "doctor":
            print(json.dumps({"local_release": LOCAL_RELEASE, "python": platform.python_version(),
                "executable": sys.executable, "system": platform.system(), "cpu_count": os.cpu_count(),
                "free_disk_gib": round(shutil.disk_usage(PROJECT).free / 2**30, 1),
                "ollama_installed": shutil.which("ollama") is not None,
                "core_dependencies": "Python standard library only", "data_dir": str(folder.resolve())}, indent=2))
        elif args.command == "demo":
            persisted_demo(folder)
        elif args.command == "auto-daily":
            from .daily_workflow import run_daily
            run_daily(folder,offline=args.offline,calendar_path=args.calendar,max_filings=args.max_filings,
                      paper=not args.no_paper,cash=args.cash,progress=lambda message:print(message,flush=True))
        elif args.command in ("news-refresh", "news-status"):
            from .market_events import refresh_events, event_status
            from .event_store import EventStore
            from .market_research import read_research
            if args.command == "news-refresh":
                report = read_research(folder)
                if not report:
                    raise ValidationError("Run research.cmd once to establish the company universe before collecting news")
                result = refresh_events(folder,report["assets"],offline=args.offline,progress=lambda m:print(m,flush=True))
            else:
                result = event_status(folder)
                if args.audit:
                    result["audit"] = EventStore(folder/"events.sqlite3").audit()
            print(json.dumps(result,indent=2))
        elif args.command == "coverage-status":
            from .coverage import snapshot, select, freshness
            from .market_research import read_research, research_status
            from .workflow_view import automation_status
            report = read_research(folder, args.report)
            result = select(snapshot(report), query=args.symbol, category=args.filter, limit=10000)
            result["current_health"] = {"freshness": freshness(report), "research": research_status(folder), "daily": automation_status(folder)}
            print(json.dumps(result, indent=2))
        elif args.command.startswith("ai-"):
            from . import research_briefs as ai
            if args.command == "ai-configure":
                result = ai.configure(folder, model=args.model, port=args.port, limit=args.limit, timeout=args.timeout, budget=args.budget)
            elif args.command == "ai-disable":
                result = ai.disable(folder)
            elif args.command == "ai-status":
                result = ai.status(folder, audit=args.audit)
            elif args.command == "ai-doctor":
                result = ai.doctor(folder, model=args.model, port=args.port)
            elif args.command == "ai-evaluate":
                from .ai_evaluation import evaluate
                result = evaluate(folder, model=args.model, port=args.port, timeout=args.timeout, extended=args.extended, progress=lambda m: print(m, flush=True))
            else:
                from .market_research import read_research
                if args.report and not re.fullmatch(r"[a-f0-9]{64}", args.report):
                    raise ValidationError("Invalid report identifier")
                result = ai.run_briefs(folder, read_research(folder, args.report), symbol=args.symbol.upper() if args.symbol else None, limit=args.limit, retry=args.retry, progress=lambda m: print(m, flush=True))
            display = result
            if args.command == "ai-evaluate":
                display = {**result, "cases": [{k: v for k, v in case.items() if k != "raw_output"} for case in result["cases"]]}
                display["saved_to"] = str(folder / "ai/evaluations" / (result["evaluation_id"] + ".json"))
            print(json.dumps(display, indent=2))
            if args.command == "ai-evaluate" and result["passed"] != result["total"]:
                return 1
            if result.get("state") in ("unavailable", "needs_review", "partial", "not_configured"):
                return 1
        elif args.command == "forward-status":
            from .forward_paper import ForwardLedger
            print(json.dumps(ForwardLedger(folder/"forward.sqlite3").status(),indent=2))
        elif args.command == "research-history":
            from .research_history import ResearchHistory
            history = ResearchHistory(folder)
            if args.recover:
                history.recover()
            print(json.dumps(history.list(limit=args.limit),indent=2))
        elif args.command.startswith("schedule-"):
            from .local_schedule import schedule
            if args.data_dir:
                raise ValidationError("Scheduled jobs use the standard local workspace; omit --data-dir")
            print(json.dumps(schedule(args.command.removeprefix("schedule-")),indent=2))
        elif args.command == "research":
            from .market_research import run_research
            from functools import partial
            integrator = None
            if args.integrated:
                from .integrated_research import integrate
                if not 0 <= args.max_filings <= 10000:
                    raise ValidationError("max-filings must be between 0 and 10000")
                integrator = partial(integrate, max_filings=args.max_filings)
            print(f"Market workspace: {folder.resolve()}", flush=True)
            run_research(folder, offline=args.offline, calendar_path=args.calendar,
                         progress=lambda message: print(message, flush=True), integrator=integrator, collect_news=args.integrated)
        elif args.command in ("import-nse", "fetch-nse"):
            session = day(args.session, "session")
            if args.command == "import-nse":
                source = Path(args.input)
                with source.open("rb") as handle:
                    content = handle.read(MAX_FILE + 1)
                uri = source.resolve().as_uri()
            else:
                content, uri = download_bhavcopy(session)
            saved = MarketStore(folder / "market.sqlite3").ingest(content, session, uri)
            print(json.dumps({k: v for k, v in saved.items() if k != "rows"} | {"supported_stocks": len(saved["rows"])}, indent=2))
        elif args.command in ("scan", "daily"):
            watchlist = args.watchlist or folder / "watchlist.json"
            calendar_path = args.calendar or folder / "calendar.json"
            supplement = args.supplement or (folder / "supplement.json" if (folder / "supplement.json").is_file() else None)
            store = MarketStore(folder / "market.sqlite3")
            if args.command == "daily" and args.download:
                calendar, _ = load_calendar(calendar_path, as_of=datetime.now(UTC))
                closed = [s for s, e in calendar.items() if e["close_at"] <= datetime.now(UTC)]
                if not closed:
                    raise ValidationError("No session has closed yet")
                latest = max(closed)
                if not store.has_session(latest):
                    content, uri = download_bhavcopy(latest)
                    store.ingest(content, latest, uri)
            report = scan_local(store, watchlist, calendar_path, supplement_path=supplement,
                                config=load_json(args.config) if args.config else None)
            save_report(report, folder)
            if args.command == "daily" and args.settle_paper:
                result = settle_cached(folder, day(report["last_session"], "session"), calendar_path)
                print(json.dumps(result["result"], indent=2))
        elif args.command == "serve":
            if not 1024 <= args.port <= 65535:
                raise ValidationError("Use a port between 1024 and 65535")
            serve(folder / "runs.sqlite3", folder / "paper.sqlite3", port=args.port, open_browser=args.open_browser)
        elif args.command == "paper-init":
            status = PaperLedger(folder / "paper.sqlite3").initialize(decimal_amount(args.cash, "cash"), args.mode)
            print(json.dumps(status, indent=2))
        elif args.command == "paper-status":
            print(json.dumps(PaperLedger(folder / "paper.sqlite3").status(), indent=2))
        elif args.command == "paper-order":
            order = PaperLedger(folder / "paper.sqlite3").submit(RunRepository(folder / "runs.sqlite3", create=False),
                order_id=args.order_id, instrument_id=args.instrument, side=args.side, quantity=args.quantity, run_id=args.run_id)
            print(json.dumps(order, indent=2))
        elif args.command == "paper-settle":
            result = settle_cached(folder, day(args.session, "session"), args.calendar or folder / "calendar.json",
                                   fee=args.fee_bps, slippage=args.slippage_bps)
            print(json.dumps(result["result"], indent=2))
        elif args.command == "analyze-text":
            target = Path(args.output)
            if target.exists():
                raise ValidationError("AI output already exists; choose a new filename")
            with Path(args.input).open("r", encoding="utf-8-sig") as handle:
                document = handle.read(12_001)
            draft = analyze_document(document, model=args.model, instrument_id=args.instrument,
                source_uri=args.source_uri, kind=args.kind, port=args.port)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as handle:
                json.dump(draft, handle, indent=2, allow_nan=False)
                handle.write("\n")
            print(f"Unreviewed local AI draft: {target}. Ranking unchanged.")
        return 0
    except KeyboardInterrupt:
        print("\nStopped. Completed market downloads remain cached; rerun research to resume.", file=sys.stderr)
        return 130
    except (ValidationError, OSError, sqlite3.Error, DecimalException, UnicodeError) as exc:
        print(f"Oraculum local error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
