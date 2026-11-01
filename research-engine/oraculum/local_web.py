"""Loopback research viewer with explicit, isolated manual-simulation POST forms."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import hmac
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .contracts import ValidationError
from .paper.ledger import PaperLedger
from .repository import RunRepository


from .ui import document, esc


def report_html(report: dict) -> str:
    rows = []
    for decision in report["decisions"]:
        rows.append("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in (
            decision["instrument_id"], decision["status"],
            "—" if decision["score"] is None else f"{decision['score']:.2f}",
            f"{decision['coverage']:.0%}", "; ".join(decision["blockers"] or decision["reasons"]),
        )) + "</tr>")
    details = []
    for d in report["decisions"]:
        factors = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in (
            f["factor"], "missing" if f["normalized"] is None else f"{f['normalized']:.3f}",
            f"{f['points']:.2f}", ", ".join(f["source_ids"]), f["unavailable_reason"] or "",
        )) + "</tr>" for f in d["factors"])
        cautions = "".join(f"<li>{esc(c)}</li>" for c in (*d["blockers"], *d["counterarguments"], *d["warnings"]))
        details.append(f"<details><summary>{esc(d['instrument_id'])} — factors and cautions</summary>"
                       f"<ul>{cautions}</ul><div class='scroll'><table><tr><th>Factor</th><th>Normalized</th>"
                       f"<th>Points</th><th>Source IDs</th><th>Unavailable</th></tr>{factors}</table></div></details>")
    sources = "".join(f"<li>{esc(s['id'])}: {esc(s['title'])}<br><small>{esc(s['uri'])} · "
                      f"available {esc(s['available_at'])}</small></li>" for s in report["input"]["sources"])
    mode = "FICTIONAL DEMONSTRATION" if report["mode"] == "synthetic" else "IMPORTED DATA"
    message = "No candidates passed the current gates." if report["abstained"] else ", ".join(report["shortlist"])
    content = (f"<p class='tag'>{mode}</p><p>Session {esc(report['last_session'])} · Cutoff {esc(report['as_of'])}</p>"
               f"<div class='notice'>{esc(message)}</div><p><a href='/api/run/{report['run_id']}'>Full audited JSON</a></p>"
               "<div class='scroll'><table><tr><th>Instrument</th><th>Status</th><th>Score</th>"
               f"<th>Coverage</th><th>Reasons / blockers</th></tr>{''.join(rows)}</table></div>"
               f"{''.join(details)}<details><summary>Source provenance</summary><ul>{sources}</ul></details>"
               f"<p><small>Run ID: {esc(report['run_id'])}</small></p>")
    return document("Manual research report", content, active="advanced")


def home_html(repository, ledger) -> str:
    history = repository.history(50) if repository else []
    if history:
        rows = "".join(f"<tr><td><a href='/run/{r['run_id']}'>{esc(r['as_of'])}</a></td>"
                       f"<td>{esc(r['mode'])}</td><td>{esc(r['dataset_id'])}</td>"
                       f"<td>{r['counts']['candidate']}</td><td>{r['counts']['excluded']}</td></tr>" for r in history)
        content = ("<p>Saved research runs, newest cutoff first. Select a run to inspect evidence and missing data.</p>"
                   "<div class='scroll'><table><tr><th>Cutoff (UTC)</th><th>Mode</th><th>Dataset</th>"
                   f"<th>Candidates</th><th>Excluded</th></tr>{rows}</table></div>")
    else:
        content = "<div class='notice'>No manual or demo runs are saved here. Your daily reports are on Today and History; the current virtual experiment is on Paper Portfolio.</div>"
    if ledger:
        status = ledger.status()
        positions = "".join(f"<li>{esc(p['instrument_id'])}: {p['quantity']} shares · average cost INR "
                            f"{esc(p['average_cost_inr'])}</li>" for p in status["state"]["positions"])
        content += (f"<h2>Virtual portfolio</h2><p>Mode: {esc(status['mode'])} · Cash: INR "
                    f"{esc(status['state']['cash_inr'])} · Pending orders: {len(status['pending'])}</p>"
                    f"<ul>{positions}</ul><p><a href='/api/paper'>Full virtual ledger</a></p>"
                    "<small>Average cost is bookkeeping, not current market value. Dividends and corporate actions are not applied.</small>")
    return document("Advanced · earlier manual engine", "<p>This area contains imported datasets and fictional demos from the earlier engine. <a href='/'>Open daily research</a> or <a href='/forward'>the current paper portfolio</a>.</p>" + content, active="advanced")


def make_server(database: str | Path, ledger_path: str | Path, *, port=8765):
    database, ledger_path = Path(database), Path(ledger_path)

    secret = secrets.token_bytes(32)
    csrf = secrets.token_hex(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            if self.path not in ("/sandbox/preview", "/sandbox/confirm"):
                self.send_error(501)
                return
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if (self.headers.get("Host") not in allowed or self.headers.get("Origin") not in {"http://"+x for x in allowed}
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded" or self.headers.get("Transfer-Encoding"):
                    self.send_error(400)
                    return
                fields = parse_qs(self.rfile.read(size).decode("utf-8"), max_num_fields=8, keep_blank_values=True)
                if any(len(v)!=1 for v in fields.values()) or not hmac.compare_digest(fields.get("csrf", [""])[0].encode("utf-8"), csrf.encode("utf-8")):
                    self.send_error(403)
                    return
                from . import demo_trading, demo_view
                from .market_research import read_research
                report = read_research(database.parent)
                account = demo_trading.state(database.parent)
                if self.path == "/sandbox/preview":
                    q = demo_trading.quote(report, fields.get("symbol",[""])[0].strip().upper(), fields.get("side",[""])[0], fields.get("quantity",[""])[0], account["revision"])
                    demo_trading.validate(account, q)
                    body = demo_view.page(report, account, csrf, symbol=q["symbol"], confirmation=q, secret=secret)
                    payload = body.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    q = demo_trading.verify(fields.get("quote", [""])[0], secret)
                    demo_trading.execute(database.parent, q, report)
                    self.send_response(303)
                    self.send_header("Location", "/sandbox")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
            except (ValidationError, ValueError, UnicodeError) as exc:
                self.send_error(400, "Virtual trade not recorded", str(exc))
            except (OSError, sqlite3.Error) as exc:
                self.send_error(503, "Demo account unavailable", str(exc))

        def do_GET(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send_error(403)
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + x for x in allowed}:
                self.send_error(403)
                return
            try:
                parsed_url = urlsplit(self.path)
                path = parsed_url.path
                manual = path in ("/advanced", "/api/runs") or re.fullmatch(r"/(?:api/)?run/[a-f0-9]{64}", path)
                repository = RunRepository(database, create=False) if manual and database.is_file() else None
                ledger = PaperLedger(ledger_path) if path in ("/advanced", "/api/paper") and ledger_path.is_file() else None
                from .workflow_view import automation_status
                workflow = automation_status(database.parent)
                if path in ("/", "/explore", "/stock", "/system"):
                    from .market_research import read_research, research_status
                    from .dashboard_view import today_html, explore_html, stock_html, system_html, no_report_html
                    query = {k: v[0] for k, v in parse_qs(parsed_url.query, max_num_fields=12).items()}
                    ident = query.get("report", "latest")
                    if ident != "latest" and not re.fullmatch(r"[a-f0-9]{64}", ident):
                        raise ValidationError("Invalid report identifier")
                    latest = read_research(database.parent)
                    report = latest if ident == "latest" else read_research(database.parent, ident)
                    if ident != "latest" and report is None:
                        self.send_error(404)
                        return
                    archived = bool(report and (latest is None or report["report_id"] != latest["report_id"]))
                    status = research_status(database.parent)
                    if path == "/system":
                        from .market_events import event_status
                        from .research_briefs import status as ai_status
                        result = system_html(report, status, workflow, archived=archived, events_status=event_status(database.parent), ai_status=ai_status(database.parent))
                    elif report is None:
                        if path == "/stock":
                            self.send_error(404)
                            return
                        result = no_report_html(status, workflow, active="explore" if path != "/" else "today")
                    elif path == "/explore":
                        result = explore_html(report, query, status=status, archived=archived)
                    elif path == "/stock":
                        asset = next((a for a in report["assets"] if a["symbol"] == query.get("symbol")), None)
                        if asset is None:
                            self.send_error(404)
                            return
                        from .market_events import report_events
                        events = report_events(database.parent,report,symbol=asset["symbol"],isin=asset.get("isin") or "",limit=5)
                        from .stock_chart import series, panel
                        chart = panel(series(database.parent, report, asset), report, asset, period=query.get("period", "60"), kind=query.get("chart", "candles"))
                        result = stock_html(report, asset, status=status, archived=archived, events=events, chart_html=chart)
                    else:
                        result = today_html(report, status, workflow=workflow, archived=archived)
                    mime = "text/html; charset=utf-8"
                elif path == "/sandbox":
                    from . import demo_trading, demo_view
                    from .market_research import read_research
                    query = parse_qs(parsed_url.query, max_num_fields=4)
                    report = read_research(database.parent)
                    result = demo_view.page(report, demo_trading.state(database.parent), csrf, symbol=query.get("symbol", [""])[0][:50])
                    mime = "text/html; charset=utf-8"
                elif path in ("/coverage", "/api/coverage", "/coverage.csv"):
                    from .coverage import FILTERS, snapshot, select, freshness, csv_export
                    from .coverage_view import coverage_html
                    from .market_research import read_research
                    query = {k:v[0] for k,v in parse_qs(parsed_url.query,max_num_fields=12).items()}
                    ident = query.get("report", "latest")
                    if ident != "latest" and not re.fullmatch(r"[a-f0-9]{64}", ident):
                        self.send_error(400, "Invalid report identifier")
                        return
                    offset = query.get("offset", "0")
                    if not offset.isdigit() or len(offset) > 8:
                        self.send_error(400, "Invalid coverage offset")
                        return
                    if len(query.get("q", "")) > 80 or query.get("filter", "all") not in FILTERS:
                        self.send_error(400, "Invalid coverage search or filter")
                        return
                    report = read_research(database.parent, None if ident == "latest" else ident)
                    data = snapshot(report)
                    result = select(data, query=query.get("q", ""), category=query.get("filter", "all"),
                                    offset=int(offset) if path == "/coverage" else 0,
                                    limit=40 if path == "/coverage" else 10000)
                    if path == "/api/coverage":
                        result, mime = json.dumps(result), "application/json"
                    elif path == "/coverage.csv":
                        result, mime = csv_export(result), "text/csv; charset=utf-8"
                    else:
                        result, mime = coverage_html(result, freshness(report)), "text/html; charset=utf-8"
                elif path == "/api/ai-status":
                    from .research_briefs import status as ai_status
                    result, mime = json.dumps(ai_status(database.parent)), "application/json"
                elif path in ("/research", "/briefs", "/brief", "/api/brief", "/brief.md"):
                    from .ai_store import BriefStore
                    from .briefs_view import overview, detail, markdown
                    from .market_research import read_research
                    from .research_briefs import read_brief, status as ai_status
                    query = {k: v[0] for k, v in parse_qs(parsed_url.query, max_num_fields=12).items()}
                    ident = query.get("report", "latest")
                    if ident != "latest" and not re.fullmatch(r"[a-f0-9]{64}", ident):
                        self.send_error(400, "Invalid report identifier")
                        return
                    report = read_research(database.parent, None if ident == "latest" else ident)
                    if report is None and (ident != "latest" or path not in ("/research", "/briefs")):
                        self.send_error(404)
                        return
                    if path in ("/research", "/briefs"):
                        summaries, error = {}, None
                        try:
                            summaries = BriefStore(database.parent).summaries(report["report_id"]) if report else {}
                        except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
                            error = "Saved briefs unavailable: " + str(exc)[:500]
                        result, mime = overview(report, ai_status(database.parent), summaries, query=query.get("q", "")[:80], error=error), "text/html; charset=utf-8"
                    else:
                        symbol = query.get("symbol", "").upper()
                        if not any(a["symbol"] == symbol for a in report["assets"]):
                            self.send_error(404)
                            return
                        bundle = read_brief(database.parent, report, symbol)
                        if path == "/api/brief":
                            result, mime = json.dumps(bundle), "application/json"
                        elif path == "/brief.md":
                            result, mime = markdown(bundle), "text/markdown; charset=utf-8"
                        else:
                            result, mime = detail(bundle), "text/html; charset=utf-8"
                elif path in ("/news", "/api/news", "/news.csv"):
                    from .event_store import EventStore
                    from .market_events import event_status, report_events
                    from .market_research import read_research
                    from .events_view import news_html, news_csv
                    query = {k:v[0] for k,v in parse_qs(parsed_url.query,max_num_fields=12).items()}
                    offset = query.get("offset","0")
                    if not offset.isdigit() or len(offset) > 8:
                        raise ValidationError("Invalid news offset")
                    filters = {k:query.get(k,"") for k in ("q","symbol","kind","source","match")}
                    filters["symbol"] = filters["symbol"].upper()
                    filters["offset"] = int(offset)
                    ident = query.get("report")
                    if ident and not re.fullmatch(r"[a-f0-9]{64}",ident):
                        raise ValidationError("Invalid report identifier")
                    report = read_research(database.parent,ident)
                    if ident and report is None:
                        self.send_error(404)
                        return
                    status = report.get("event_coverage",{}) if ident else event_status(database.parent)
                    if ident:
                        if filters["symbol"]:
                            asset = next((a for a in report["assets"] if a["symbol"] == filters["symbol"]),None)
                            if asset:
                                filters["isin"] = asset.get("isin") or ""
                        result = report_events(database.parent,report,**filters)
                    else:
                        result = EventStore(database.parent/"events.sqlite3").query(**filters)
                    if path == "/api/news":
                        result, mime = json.dumps({**result,"health":status}), "application/json"
                    elif path == "/news.csv":
                        result, mime = news_csv(result), "text/csv; charset=utf-8"
                    else:
                        result, mime = news_html(result,status,query,report=report,pinned=bool(ident)), "text/html; charset=utf-8"
                elif path in ("/research-history", "/api/research-history", "/history"):
                    from .research_history import ResearchHistory
                    from .workflow_view import history_html
                    offset = parse_qs(parsed_url.query, max_num_fields=12).get("offset", ["0"])[0]
                    if not offset.isdigit() or len(offset) > 9:
                        raise ValidationError("Invalid history offset")
                    history = ResearchHistory(database.parent).list(offset=int(offset))
                    result, mime = (json.dumps(history), "application/json") if path.startswith("/api/") else (history_html(history), "text/html; charset=utf-8")
                elif path in ("/forward", "/api/forward", "/forward.csv"):
                    from .forward_paper import ForwardLedger
                    from .workflow_view import forward_html, forward_csv
                    status = ForwardLedger(database.parent/"forward.sqlite3").status()
                    if path == "/api/forward":
                        result, mime = json.dumps(status), "application/json"
                    elif path == "/forward.csv":
                        result, mime = forward_csv(status), "text/csv; charset=utf-8"
                    else:
                        result, mime = forward_html(status, workflow), "text/html; charset=utf-8"
                elif path == "/api/automation":
                    result, mime = json.dumps(workflow), "application/json"
                elif path == "/advanced":
                    result, mime = home_html(repository, ledger), "text/html; charset=utf-8"
                elif re.fullmatch(r"/(?:api/)?research/(?:latest|[a-f0-9]{64})(?:\.csv)?", path):
                    from .market_research import read_research, research_status, report_csv
                    identity = path.rsplit("/", 1)[1].removesuffix(".csv")
                    report = read_research(database.parent, None if identity == "latest" else identity)
                    if report is None:
                        self.send_error(404)
                        return
                    if path.endswith(".csv"):
                        result, mime = report_csv(report), "text/csv; charset=utf-8"
                    elif path.startswith("/api/"):
                        result, mime = json.dumps(report), "application/json"
                    else:
                        from .dashboard_view import today_html
                        latest = read_research(database.parent)
                        archived = bool(latest is None or latest["report_id"] != report["report_id"])
                        result, mime = today_html(report, research_status(database.parent), workflow=workflow, archived=archived), "text/html; charset=utf-8"
                elif path == "/api/runs":
                    result, mime = json.dumps(repository.history(100) if repository else []), "application/json"
                elif path == "/api/paper":
                    result, mime = json.dumps(ledger.status() if ledger else {"initialized": False}), "application/json"
                elif re.fullmatch(r"/(?:api/)?run/[a-f0-9]{64}", path) and repository:
                    report = repository.get(path.rsplit("/", 1)[1])
                    result, mime = ((json.dumps(report), "application/json") if path.startswith("/api/") else
                                    (report_html(report), "text/html; charset=utf-8"))
                else:
                    self.send_error(404)
                    return
                payload = result.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
                self.end_headers()
                self.wfile.write(payload)
            except FileNotFoundError:
                self.send_error(404, "Saved report not found")
            except (ValidationError, OSError, sqlite3.Error, ValueError) as exc:
                self.send_error(503, "Local data unavailable", str(exc))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(database, ledger, *, port=8765, open_browser=False):
    with make_server(database, ledger, port=port) as server:
        address = f"http://127.0.0.1:{server.server_port}/"
        print(f"Oraculum: {address}  (Ctrl+C to stop)", flush=True)
        if open_browser:
            webbrowser.open(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
