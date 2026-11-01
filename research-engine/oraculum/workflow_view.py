"""Read-only history and forward-experiment pages and exports."""
import csv
import json
import io
import math
from decimal import Decimal
from pathlib import Path

from .local_web import document, esc
from .serialization import load_json
from .ui import badge, cards, date_text, empty_state, link, money, number, time_text
from .dashboard_view import table


def automation_status(folder):
    path = Path(folder)/"automation/status.json"
    from .activity import observed_status
    return observed_status(Path(folder)/"automation", load_json(path)) if path.is_file() else {"state":"not_started"}


def workflow_notice(status):
    if status.get("state") not in ("failed","running"):
        return ""
    from .activity import activity_message
    message = (activity_message(status, label="Daily workflow") if status["state"] == "running"
               else f"Daily workflow failed in {status.get('phase', 'unknown')}: {status.get('error', 'Unknown error')}")
    detail = status.get("last_message") or ""
    return f"<div class='notice'>{esc(message)}<br>{esc(detail)}<br>Last progress: {esc(time_text(status.get('updated_at')))}</div>"



def history_html(history):
    labels = {"nse-combined-v1":"Combined research · v1",
              "nse-adjusted-technical-with-filings-v1":"Adjusted technical + filings · v1",
              "nse-price-watchlist-v1":"Price and volume · v1"}
    content = f'<div class="freshness"><span><strong>{history["total"]:,}</strong> archived reports</span><span>Every cutoff and ranking version is preserved.</span></div>'
    rows = []
    for i, r in enumerate(history["items"]):
        highlights = r["combined_highlights"]
        previous = history["items"][i+1] if i+1 < len(history["items"]) else None
        chips = ''.join(f'<span class="chip">{esc(x.removeprefix("NSE:"))}</span>' for x in highlights[:3])
        details = '<details><summary>Shortlist and changes</summary>'
        details += '<p>' + (''.join(f'<a class="chip" href="{link("/stock",report=r["report_id"],symbol=x.removeprefix("NSE:"))}">{esc(x.removeprefix("NSE:"))}</a>' for x in highlights) or 'No combined highlights in this report.') + '</p>'
        if previous and previous["algorithm"] == r["algorithm"]:
            added, removed = sorted(set(highlights)-set(previous["combined_highlights"])), sorted(set(previous["combined_highlights"])-set(highlights))
            details += f'<p>Compared with the previous saved report:<br>Added: {esc(", ".join(added) or "None")}<br>Removed: {esc(", ".join(removed) or "None")}</p>'
        elif previous:
            details += '<p>Ranking version changed; shortlist changes are not directly comparable.</p>'
        else:
            details += '<p>No preceding report is loaded on this page for comparison.</p>'
        details += f'<p class="hash">Algorithm: {esc(r["algorithm"])}<br>Report: {esc(r["report_id"])}</p></details>'
        rows.append(f'<tr><td class="nowrap"><a href="/research/{esc(r["report_id"])}">{esc(date_text(r["session"]))}</a></td>'
                    f'<td class="nowrap">{esc(time_text(r["as_of"]))}</td><td>{esc(labels.get(r["algorithm"],"Other saved ranking"))}</td>'
                    f'<td class="num">{esc(r["counts"].get("combined_eligible","Not computed"))}</td>'
                    f'<td>{chips or badge("No combined highlights")}{f"<small> +{len(highlights)-3}</small>" if len(highlights)>3 else ""}{details}</td></tr>')
    if rows:
        content += '<section class="panel flush">' + table(("Price session", "Report built", "Ranking version", "Combined eligible", "Shortlist"),
                                                         rows, "Archived daily reports") + '</section>'
    if history["next_offset"] is not None:
        content += f'<div class="actions"><a class="button secondary" href="/research-history?offset={history["next_offset"]}">Older reports →</a><a href="/research-history">Newest reports</a></div>'
    if not history["items"]:
        content += empty_state("No daily reports archived yet", "Run research.cmd to create a report and index any preserved reports from earlier versions.",
                               '<a class="button secondary" href="/">Return to Today</a>')
    return document("Research history",content,active="history",subtitle="Revisit what the system knew and how its shortlist changed.")


def forward_csv(status):
    out=io.StringIO(newline="")
    fields=["session","equity_inr","benchmark_equity_inr","return","benchmark_return","excess_return","maximum_drawdown","stale_symbols","benchmark_stale_symbols"]
    writer=csv.DictWriter(out,fieldnames=fields,extrasaction="ignore")
    writer.writeheader()
    for row in status.get("equity_curve",[]):
        writer.writerow(row | {"stale_symbols":"; ".join(row["stale_symbols"]),"benchmark_stale_symbols":"; ".join(row["benchmark_stale_symbols"])})
    return out.getvalue()


def pct(value):
    return "Unavailable" if value is None else f"{value:+.2%}"


def equity_chart(curve):
    """Plot saved returns only; unavailable/stale observations break lines."""
    def valid(value):
        return isinstance(value,(int,float)) and math.isfinite(value)
    usable = [v for row in curve for v in (row.get("return"),row.get("benchmark_return")) if valid(v)]
    if len(curve) < 2 or not usable:
        return empty_state("Performance needs more observations", "The chart appears after at least two recorded sessions with available returns. Pending orders are not executed positions.")
    lo, hi = min(0,min(usable)), max(0,max(usable))
    pad = max((hi-lo)*.15,.002)
    lo,hi = lo-pad,hi+pad
    def xy(i,v):
        return 72+i/(len(curve)-1)*802, 225-(v-lo)/(hi-lo)*190
    content = '<svg class="chart" viewBox="0 0 910 270" role="img" aria-labelledby="performance-title performance-desc">'
    content += '<title id="performance-title">Recorded forward returns</title><desc id="performance-desc">Strategy and NIFTYBEES with residual cash, net of modeled fees and slippage. Gaps indicate unavailable returns. Values are available in the daily records table and CSV.</desc>'
    for value in (lo,0,hi):
        y=xy(0,value)[1]
        content += f'<line x1="72" y1="{y:.2f}" x2="874" y2="{y:.2f}" stroke="#dce2ec"/><text x="62" y="{y+4:.2f}" text-anchor="end" fill="#647080" font-size="11">{value:+.1%}</text>'
    for key,color in (("return","#b9c9ff"),("benchmark_return","#e5c17d")):
        segments,points=[],[]
        for i,row in enumerate(curve):
            value=row.get(key)
            if valid(value):
                points.append(xy(i,value))
            elif points:
                segments.append(points);points=[]
        if points:
            segments.append(points)
        for segment in segments:
            if len(segment)>1:
                content += f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x,y in segment)}" fill="none" stroke="{color}" stroke-width="2.5"/>'
            for x,y in (segment if len(segment)==1 else (segment[-1],)):
                content += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}"/>'
    content += f'<text x="72" y="255" fill="#647080" font-size="11">{esc(date_text(curve[0]["session"]))}</text><text x="874" y="255" text-anchor="end" fill="#647080" font-size="11">{esc(date_text(curve[-1]["session"]))}</text></svg>'
    return '<div class="legend"><span>Strategy</span><span class="benchmark">NIFTYBEES + cash</span></div>'+content


def book_html(book, *, title):
    held = sum(Decimal(str(p["last_close"]))*p["quantity"] for p in book["positions"].values())
    reserved = sum(Decimal(o["maximum_cost_inr"]) for o in book["pending"])
    content = f'<section class="panel flush"><div class="section-heading"><div><h2>{esc(title)}</h2><p>{len(book["positions"])} open holdings · {len(book["pending"])} pending entries · {money(held)} marked holding value</p></div></div>'
    rows = []
    for symbol,p in sorted(book["positions"].items()):
        rows.append(f'<tr><td><strong>{esc(symbol)}</strong></td><td class="num">{p["quantity"]:,}</td><td class="nowrap">{esc(date_text(p["entry_session"]))}</td>'
                    f'<td class="num">{p["holding_sessions"]}</td><td class="num">{money(p["last_close"])}<span class="sub">{esc(date_text(p["mark_session"]))}</span></td>'
                    f'<td class="num">{money(Decimal(str(p["last_close"]))*p["quantity"])}</td></tr>')
    content += table(("Stock","Shares","Entry session","Sessions held","Last mark","Marked value"),rows,title+" holdings") if rows else '<p class="section-foot">No executed holdings. Pending entries are shown separately below.</p>'
    content += '<div class="section-heading"><div><h3>Pending entries</h3><p>Committed for a future session; final exchange files determine whether they filled.</p></div></div>'
    rows = []
    for o in book["pending"]:
        rows.append(f'<tr><td>{esc(o["symbol"])}</td><td class="num">{o["quantity"]:,}</td><td class="nowrap">{esc(date_text(o["execution_session"]))}</td>'
                    f'<td class="num">{money(o["maximum_cost_inr"])}</td><td><a href="/research/{esc(o["report_id"])}">Decision report</a></td></tr>')
    content += table(("Stock","Shares","Entry session","Maximum cost","Evidence"),rows,title+" pending entries") if rows else '<p class="section-foot">No pending entries.</p>'
    content += f'<div class="section-foot">Cash {money(book["cash_inr"])} · reserved for pending entries up to {money(reserved)} · unspendable dividend receivables {money(book["receivable_inr"])}</div></section>'
    content += f'<details><summary>{esc(title)} · costs and closed trades</summary><p>Fees {money(book["fees_inr"])} · modeled slippage {money(book["slippage_inr"])} · closed trades {book["closed_trades"]} · profitable {book["winning_trades"]} · realized P/L including receivables {money(book["realized_inr"])}.</p></details>'
    return content


def forward_html(status, workflow=None):
    content = workflow_notice(workflow or {})
    if not status["initialized"]:
        content += empty_state("Your paper experiment has not started", "Run research.cmd to refresh the evidence and initialize INR 100,000 of virtual cash. New orders must wait for a future market open.",
                               '<a class="button secondary" href="/">View the latest research</a>')
        return document("Paper portfolio",'<div class="research-tabs"><a href="/sandbox">Manual practice</a><a aria-current="page" href="/forward">Automatic strategy</a></div>'+content,active="paper",subtitle="Forward paper evaluation · virtual money only.")
    s=status["state"]
    book=s["strategy"]
    content += f'<div class="freshness"><span>Started <strong>{esc(time_text(s["created_at"]))}</strong></span><span>Last processed prices <strong>{esc(date_text(s["last_session"]))}</strong></span>{badge("Virtual money only")}</div>'
    value = s["latest_valuation"]
    content += cards([
        ("Total marked equity", money(value["equity_inr"]) if value else money(s["initial_cash_inr"]), "Includes cash and dividend receivables"),
        ("Virtual cash",money(book["cash_inr"]), "Pending reservations are shown below"),
        ("Open holdings",str(len(book["positions"])),f'{len(book["pending"])} pending entries'),
        ("Strategy return",pct(value["return"]) if value else "Not available yet", "Net of modeled costs"),
    ])
    if value:
        stale=value["stale_symbols"]+value["benchmark_stale_symbols"]
        if stale:
            content += f"<div class='notice'>Stale quotes: {esc(', '.join(stale))}. Equity includes carried marks; current return comparisons are withheld.</div>"
    else:
        content += "<div class='notice'>No completed forward session yet. Pending entries can only fill after their committed future session closes and its final file is available.</div>"
    content += '<section class="panel"><h2>Recorded performance</h2>'
    content += equity_chart(status["equity_curve"])
    if value:
        content += (f'<p class="muted">Benchmark return {pct(value["benchmark_return"])} · difference {pct(value["excess_return"])} · '
                    f'observed daily maximum drawdown {value["maximum_drawdown"]:.2%}.</p>')
    content += '</section>'
    content += book_html(book,title="Strategy")
    content += '<details><summary>NIFTYBEES benchmark · holdings and cash</summary>'+book_html(s["benchmark"],title="Benchmark")+'</details>'
    content += '<details><summary>Daily equity records · latest 30 sessions</summary><p>The CSV and JSON include all recorded sessions.</p>'
    rows = []
    for v in reversed(status["equity_curve"][-30:]):
        rows.append(f'<tr><td>{esc(date_text(v["session"]))}</td><td class="num">{money(v["equity_inr"])}</td><td class="num">{money(v["benchmark_equity_inr"])}</td><td class="num">{pct(v["excess_return"])}</td></tr>')
    content += table(("Session","Strategy equity","Benchmark equity","Return difference"),rows,"Recorded daily equity") if rows else '<p>No completed forward records.</p>'
    content += '</details><div class="actions"><a class="button secondary" href="/forward.csv" download>Download equity CSV</a><a href="/api/forward">Audited ledger JSON</a></div>'
    content += '<details><summary>Paper rules and limitations</summary>'
    content += (f'<p>Initial virtual cash {money(s["initial_cash_inr"])}. At most five positions; new allocations are capped at 20% of initial cash. '
                'Entries use quantities committed before the next open. Positions exit after 20 completed holding sessions. '
                'Costs are 10 bps fees plus 10 bps slippage per side.</p>')
    content += "<ul>"+"".join(f"<li>{esc(x)}</li>" for x in status["limitations"])+"</ul>"
    content += f'<p class="hash">Policy: {esc(s["policy"]["version"])}</p></details>'
    content += '<details><summary>Recent execution records</summary>'
    for e in reversed(status["recent_events"][-15:]):
        content += f"<details><summary>{esc(e['key'])} · recorded {esc(e['recorded_at'])}</summary><pre>{esc(json.dumps(e['details'],indent=2))}</pre></details>"
    content += '</details>'
    return document("Paper portfolio",'<div class="research-tabs"><a href="/sandbox">Manual practice</a><a aria-current="page" href="/forward">Automatic strategy</a></div>'+content,active="paper",subtitle="Forward paper evaluation · actual recorded decisions, virtual money only.")
