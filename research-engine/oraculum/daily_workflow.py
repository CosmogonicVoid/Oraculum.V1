"""One local daily job: refresh, archive, settle existing paper plans, record new ones."""
from datetime import datetime
from functools import partial
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .contracts import UTC, ValidationError, day, iso
from .forward_paper import ForwardLedger
from .integrated_research import integrate
from .local_data import MarketStore
from .market_calendar import research_calendar
from .market_research import run_research, workflow_lock, write_json
from .nse_evidence import EvidenceStore
from .research_history import ResearchHistory


def advance_paper(folder, report, *, calendar_path=None, cash="100000.00", clock=None):
    clock = clock or (lambda:datetime.now(UTC))
    now = clock()
    calendar, _, _ = research_calendar(now, calendar_path)
    ledger = ForwardLedger(Path(folder)/"forward.sqlite3")
    status = ledger.status()
    if not status["initialized"]:
        ledger.initialize(report,calendar,cash=cash,now=now)
        status = ledger.status()
    start = min(day(status["state"]["last_session"],"last settlement"),day(report["last_session"],"report session"))
    snapshots = MarketStore(Path(folder)/"market.sqlite3").research_snapshots(start=start,end=day(report["last_session"],"session"))
    refs = [s for s in report["evidence_sources"] if s["kind"] == "actions"]
    if len(refs) != 1:
        raise ValidationError("Paper settlement needs exactly one action receipt")
    actions = EvidenceStore(Path(folder)/"evidence.sqlite3").get(refs[0]["source_id"])
    return ledger.update(report,calendar,snapshots,actions,now=clock())


def run_daily(folder, *, offline=False, calendar_path=None, max_filings=60, paper=True,
              cash="100000.00", progress=print, clock=None, research_runner=None, paper_runner=None, ai_runner=None):
    folder = Path(folder)
    clock = clock or (lambda:datetime.now(UTC))
    research_runner, paper_runner = research_runner or run_research, paper_runner or advance_paper
    root = folder / "automation"
    with workflow_lock(root) as activity:
        status = {"state":"running","started_at":iso(clock()),"phase":"research",
                  "report_id":None,"paper_enabled":paper,"error":None,"activity_id":activity["id"]}
        path = root/"status.json"
        write_json(path,status)
        log = logging.getLogger("oraculum.daily."+str(folder.resolve()))
        log.setLevel(logging.INFO)
        log.propagate = False
        handler = RotatingFileHandler(root/"daily.log",maxBytes=2*1024*1024,backupCount=3,encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(handler)
        def note(message):
            status.update(last_message=str(message)[:1000], updated_at=iso(clock()))
            try:
                write_json(path, status)
            except OSError:
                pass
            log.info(message)
            progress(message)
        try:
            ResearchHistory(folder).recover()
            note("Starting combined research and forward paper workflow.")
            report = research_runner(folder,offline=offline,calendar_path=calendar_path,clock=clock,
                    progress=note,integrator=partial(integrate,max_filings=max_filings),collect_news=True)
            status.update(news_state=report.get("event_coverage",{}).get("state","not_captured"),report_id=report["report_id"],phase="paper" if paper else "complete")
            write_json(path,status)
            paper_status = None
            if paper:
                paper_status = paper_runner(folder,report,calendar_path=calendar_path,cash=cash,clock=clock)
                write_json(root/"paper-latest.json",paper_status)
                note(f"Forward experiment: {len(paper_status['state']['strategy']['positions'])} virtual positions; "
                     f"{len(paper_status['state']['strategy']['pending'])} pending entries. No real-money orders.")
            status["phase"] = "ai"
            write_json(path, status)
            try:
                from .research_briefs import run_briefs
                ai_status = (ai_runner or run_briefs)(folder, report, clock=clock, progress=note)
            except Exception as exc:
                ai_status = {"state": "unavailable", "error": str(exc)[:800]}
            status.update(ai_state=ai_status["state"], ai_error=ai_status.get("error"))
            note("Local AI: " + ai_status["state"] + ". Research and paper records are saved.")
            status.update(state="ready",phase="complete",finished_at=iso(clock()))
            write_json(path,status)
            write_json(root/("run-"+clock().strftime("%Y%m%dT%H%M%S%fZ")+".json"),status)
            note("Daily workflow complete. Open start.cmd to inspect ranking, history and paper results.")
            return {"report":report,"paper":paper_status,"ai":ai_status,"status":status}
        except (Exception,KeyboardInterrupt) as exc:
            status.update(state="failed",finished_at=iso(clock()),error=str(exc) or type(exc).__name__)
            write_json(path,status)
            write_json(root/("run-"+clock().strftime("%Y%m%dT%H%M%S%fZ")+".json"),status)
            note(f"Daily workflow stopped in {status['phase']}: {status['error']}. Cached inputs and committed records are preserved.")
            raise
        finally:
            log.removeHandler(handler)
            handler.close()
