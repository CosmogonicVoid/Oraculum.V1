"""Read-only dashboard views. Every displayed metric comes from a saved report."""
from .contracts import ValidationError
from .ui import (badge, cards, date_text, document, empty_state, esc, link, money,
                 number, percent, source_link, time_text)

LABELS = {
    "technical": "Price and volume", "revenue_yoy": "Revenue growth YoY",
    "net_margin": "Net margin", "borrowings_to_equity": "Borrowings / equity",
    "roce": "Annual ROCE", "annual_pe": "Annual P/E (not TTM)",
    "peer_pe_ratio": "P/E / cached-peer median",
}
PROFILE_LABELS = {
    "available": "Complete", "partial": "Partial", "pending": "Awaiting filings",
    "unsupported_schema": "Unsupported filing", "identity_review": "Identity review",
    "ambiguous_filing": "Filing review", "no_filing": "No filing", "unavailable": "Unavailable",
}
FILTERS = (("all", "All scanned stocks"), ("combined", "Combined eligible"),
           ("candidates", "Combined candidates"), ("technical", "Technical passes"),
           ("partial", "Partial financials"), ("incomplete", "Incomplete financials"),
           ("excluded", "Technical exclusions"))
SORTS = (("combined", "Combined rank"), ("technical", "Technical rank"),
         ("symbol", "Stock A–Z"), ("momentum", "20-session return"))
PAGE_SIZE = 40


def table(headers, rows, caption, *, tall=False):
    return (f'<div class="scroll{" tall" if tall else ""}" role="region" aria-label="{esc(caption)}" tabindex="0">'
            f'<table><caption class="sr-only">{esc(caption)}</caption><thead><tr>'
            + ''.join(f'<th scope="col">{esc(h)}</th>' for h in headers)
            + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def profile_badge(asset):
    state = asset.get("fundamentals", {}).get("status", "unavailable")
    return badge(PROFILE_LABELS.get(state, state.replace("_", " ").capitalize()),
                 "good" if state == "available" else "warn" if state == "partial" else "neutral")


def stock_link(report, asset, label=None):
    return f'<a class="stock" href="{link("/stock", report=report["report_id"], symbol=asset["symbol"])}">{esc(label or asset["symbol"])}</a>'


def stock_cell(report, asset):
    return stock_link(report, asset) + f'<div class="company">{esc(asset.get("company_name") or asset.get("instrument_id", ""))}</div>'


def score_cell(value):
    if value is None:
        return '<span class="muted">Unavailable</span>'
    return f'<span class="score">{number(value)}<small> /100</small></span>'


def freshness(report):
    return (f'<div class="freshness"><span>Prices through <strong>{esc(date_text(report["last_session"]))}</strong></span>'
            f'<span>Report built <strong>{esc(time_text(report["as_of"]))}</strong></span>'
            '<span>End-of-day data</span></div>')


def report_notices(report, status=None, *, now=None, archived=False):
    from .research_view import freshness_notice
    content = ''
    if archived:
        content += '<div class="notice">Archived report: rankings and evidence retain their original cutoff. <a href="/">Open the latest report</a>.</div>'
    else:
        content += freshness_notice(report, status, now=now)
    for warning in report.get("refresh_warnings", []):
        content += f'<div class="notice">{esc(warning)}</div>'
    return ('<details class="status-panel" open><summary>Report status · review required</summary>' + content + '</details>') if content else ""


def export_links(report):
    ident = report["report_id"]
    return (f'<a class="button secondary" href="/research/{esc(ident)}.csv" download>Download CSV</a>'
            f'<a href="/api/research/{esc(ident)}">Evidence JSON</a>')


def coverage_notice(report):
    coverage = report.get("fundamental_coverage", {})
    statuses = coverage.get("statuses", {})
    complete, partial = statuses.get("available", 0), statuses.get("partial", 0)
    return (f'<div class="notice"><strong>Financial coverage is still building.</strong> '
            f'{complete:,} complete and {partial:,} partial profiles in this report. '
            'A combined score requires technical eligibility and all four timely financial inputs. '
            'Unavailable figures are not treated as zero. '
            f'<a href="{link("/coverage", report=report["report_id"])}">View coverage</a>.</div>')


def candidate_rows(report, assets):
    rows = []
    for a in assets:
        c, metrics = a["combined"], a.get("metrics", {})
        fm = a.get("fundamentals", {}).get("metrics", {})
        growth = fm.get("revenue_yoy")
        reason = f'{percent(metrics.get("momentum_20d"))} over 20 sessions'
        support = f'Revenue YoY {percent(growth["value"])}' if growth else 'Financial inputs unavailable'
        warnings = a.get("warnings", []) + a.get("fundamentals", {}).get("notes", [])
        caution = warnings[0] if warnings else "News and valuation need review."
        rows.append(
            f'<tr><td class="num">{esc(c["rank"])}</td><td>{stock_cell(report, a)}</td>'
            f'<td class="nowrap">{score_cell(c["score"])}</td>'
            f'<td class="reason">{esc(reason)}<span class="sub">{esc(support)}</span></td>'
            f'<td class="caution">{esc(caution)}</td>'
            f'<td>{profile_badge(a)}<span class="sub"><a href="{link("/stock", report=report["report_id"], symbol=a["symbol"])}" aria-label="View analysis for {esc(a["symbol"])}">Analysis →</a></span></td></tr>')
    return rows


def market_context(report):
    """Descriptive counts from this report, never a fabricated time series."""
    import math
    values = []
    for asset in report["assets"]:
        value = asset.get("combined", {}).get("score")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100:
            values.append(value)
    bins = [sum(low <= x < high for x in values) for low, high in ((0,20),(20,40),(40,60),(60,80),(80,101))]
    scale = max(bins, default=0) or 1
    body = '<aside class="market-rail" aria-label="Report analytics"><section class="panel"><span class="eyebrow">Report analytics</span><h2>Combined score distribution</h2>'
    if values:
        body += '<div class="distribution" role="img" aria-label="' + esc('; '.join(f'{label}: {n} stocks' for label, n in zip(('0–<20','20–<40','40–<60','60–<80','80–100'),bins))) + '">'
        for label, count in zip(('0–<20','20–<40','40–<60','60–<80','80–100'),bins):
            body += f'<div class="dist-row"><span>{esc(label)}</span><div class="dist-track"><div class="dist-bar" style="width:{count / scale * 100:.2f}%"></div></div><span class="dist-value">{count:,}</span></div>'
        body += '</div>'
    else:
        body += '<p class="rail-note">No complete combined scores in this report.</p>'
    body += f'<p class="rail-note">{len(values):,} scored · {len(report["assets"])-len(values):,} without a valid combined score. Score ranges are descriptive, not return probabilities.</p>'
    body += f'<a class="rail-link" href="{link("/coverage",report=report["report_id"])}">Inspect data coverage →</a></section>'
    eligible = [a for a in report['assets'] if a.get('status') == 'eligible' and isinstance(a.get('metrics',{}).get('momentum_20d'), (int,float)) and math.isfinite(a['metrics']['momentum_20d'])]
    leaders = sorted(eligible, key=lambda a: (-a['metrics']['momentum_20d'], a['symbol']))[:5]
    body += '<section class="panel"><span class="eyebrow">Technical watch</span><h2>20-session momentum leaders</h2><p class="rail-note">Among technical passes; these are not combined recommendations.</p>'
    for asset in leaders:
        value = asset['metrics']['momentum_20d']
        body += f'<div class="rail-stock"><div>{stock_link(report,asset)}<span class="sub">{esc(asset.get("company_name") or asset["symbol"])}</span></div><span class="num {"positive" if value >= 0 else "negative"}">{percent(value)}</span></div>'
    if not leaders:
        body += '<p class="rail-note">No eligible momentum observations are available.</p>'
    return body + f'<a class="rail-link" href="{link("/explore",report=report["report_id"],filter="technical",sort="momentum")}">Open technical screener →</a></section></aside>'


def today_html(report, status=None, *, workflow=None, now=None, archived=False):
    from .workflow_view import workflow_notice
    counts = report["counts"]
    content = freshness(report)
    content += report_notices(report, status, now=now, archived=archived)
    if not archived and not (status and status.get("state") == "running" and (workflow or {}).get("phase") == "research" and (workflow or {}).get("state") == "running"):
        content += workflow_notice(workflow or {})
    content += cards([
        ("Stocks scanned", f'{counts.get("scanned", len(report["assets"])):,}', "Supported traded instruments"),
        ("Technical passes", f'{counts.get("eligible", 0):,}', "Price, volume and action filters"),
        ("Combined eligible", f'{counts.get("combined_eligible", 0):,}', "Complete inputs + technical eligibility"),
    ])
    assets = sorted((a for a in report["assets"] if a.get("combined", {}).get("highlight")),
                    key=lambda a: (a["combined"]["rank"], a["symbol"]))
    content += '<div class="terminal-grid"><div class="terminal-main"><section class="panel flush" aria-labelledby="shortlist-heading"><div class="section-heading"><div><h2 id="shortlist-heading">Ranked shortlist</h2>'
    content += f'<p>{len(assets)} highlighted · {counts.get("combined_candidates", 0):,} candidates pass the combined rules</p></div>'
    content += f'<a class="button secondary" href="{link("/explore", report=report["report_id"], filter="combined")}">All combined scores →</a></div>'
    content += '<div class="view-tabs">' + ''.join(f'<a href="{link("/explore",report=report["report_id"],filter=key)}">{label}</a>' for key,label in (("combined","Combined scores"),("technical","Technical passes"),("incomplete","Coverage gaps"))) + '</div>'
    if assets:
        content += table(("Rank", "Stock", "Combined score", "Supporting signals", "Key caution", "Coverage / details"),
                         candidate_rows(report, assets), "Ranked research shortlist")
    else:
        message = ("This report predates combined ranking. Its technical results are available in Explore."
                   if "ranking_policy" not in report else
                   "No stocks meet every combined shortlist rule in this report. Technical-only results remain available in Explore.")
        content += empty_state("No combined candidates to highlight", message,
                               f'<a class="button secondary" href="{link("/explore", report=report["report_id"], filter="technical", sort="technical")}">Explore technical results</a>')
    content += '<div class="section-foot">Combined score: 60% technical + 10% each for revenue growth, net margin, borrowings/equity and ROCE. Scores are not profit probabilities.</div></section>'
    content += "</div>" + market_context(report) + "</div>"
    content += '<details class="status-panel"><summary>Coverage &amp; collection details</summary>' + coverage_notice(report)
    if report.get("event_coverage"):
        events = report["event_coverage"]
        content += f'<p class="muted">News collection: {esc(events["state"])} · {events.get("matched_items_30d",0):,} matched items in the preceding 30 days. <a href="{link("/news",report=report["report_id"])}">Review this report’s news evidence →</a></p>'

    content += "</details>"
    content += (f'<div class="actions">{export_links(report)}'
                f'<a class="button secondary" href="{link("/briefs", report=report["report_id"])}">Read research briefs</a>'
                f'<a href="{link("/explore", report=report["report_id"])}">Explore all stocks →</a></div>')
    content += '<details><summary>How to read this shortlist</summary><p>Complete combined scores are ranked before the additional candidate rules are applied. A gap in displayed ranks is possible. Candidates must also pass the financial screen, have positive momentum and trend, and score at least 60.</p><p>These are research leads. News, general announcements and valuation are not scored. Financial metrics retain their own reporting periods; inspect a stock for dates, calculations and evidence.</p></details>'
    return document("Archived shortlist" if archived else "Market overview", content,
                    active="history" if archived else "today",
                    subtitle="Price and financial evidence, ranked for closer review.")


def no_report_html(status=None, workflow=None, *, active="today"):
    from .workflow_view import workflow_notice
    content = workflow_notice(workflow or {})
    if status and status.get("state") in ("failed", "running"):
        content += f'<div class="notice">Research update {esc(status["state"])}: {esc(status.get("error") or "No completed report has been published yet.")}</div>'
    content += empty_state("Your first report is not ready yet",
                           "Run research.cmd from your project folder to collect market data and build the first shortlist.",
                           '<a class="button secondary" href="/system">Check data and workflow status</a>')
    content += '<p class="muted">If you have only run the fictional demo or imported a manual dataset, those results are available under <a href="/advanced">Advanced</a>.</p>'
    return document("Explore stocks" if active == "explore" else "Market overview", content, active=active)


def select_assets(report, query):
    q = query.get("q", "").strip()
    kind, sort = query.get("filter", "all"), query.get("sort", "combined")
    raw_page = query.get("page", "1")
    if len(q) > 100 or kind not in dict(FILTERS) or sort not in dict(SORTS):
        raise ValidationError("Invalid stock search or filter")
    if not raw_page.isdigit() or len(raw_page) > 6 or int(raw_page) < 1:
        raise ValidationError("Invalid stock page")
    checks = {
        "all": lambda a: True,
        "combined": lambda a: a.get("combined", {}).get("rank") is not None,
        "candidates": lambda a: bool(a.get("combined", {}).get("candidate")),
        "technical": lambda a: a.get("status") == "eligible",
        "partial": lambda a: a.get("fundamentals", {}).get("status") == "partial",
        "incomplete": lambda a: a.get("fundamentals", {}).get("status") != "available",
        "excluded": lambda a: a.get("status") != "eligible",
    }
    selected = [a for a in report["assets"] if checks[kind](a) and q.casefold() in
                " ".join(str(a.get(k, "")) for k in ("symbol", "company_name", "isin", "instrument_id")).casefold()]
    def sort_key(a):
        if sort == "symbol":
            return (a["symbol"],)
        v = (a.get("combined", {}).get("rank") if sort == "combined" else
             a.get("rank") if sort == "technical" else a.get("metrics", {}).get("momentum_20d"))
        return (v is None, -v if v is not None and sort == "momentum" else v or 0, a["symbol"])
    selected.sort(key=sort_key)
    pages = max(1, (len(selected) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(int(raw_page), pages)
    start = (page - 1) * PAGE_SIZE
    return selected[start:start + PAGE_SIZE], len(selected), page, pages


def explore_html(report, query, *, status=None, now=None, archived=False):
    assets, total, page, pages = select_assets(report, query)
    q, kind, sort = query.get("q", "").strip(), query.get("filter", "all"), query.get("sort", "combined")
    content = freshness(report) + report_notices(report, status, now=now, archived=archived)
    content += '<section class="panel flush"><form method="get" action="/explore" class="filters" role="search">'
    content += f'<input type="hidden" name="report" value="{esc(report["report_id"])}">'
    content += f'<div class="filter-search"><label for="stock-search">Stock, company or ISIN</label><input id="stock-search" name="q" type="search" maxlength="100" value="{esc(q)}" placeholder="Search all scanned stocks"></div>'
    for name, label, options, selected in (("filter", "Show", FILTERS, kind), ("sort", "Order by", SORTS, sort)):
        content += f'<div><label for="{name}">{label}</label><select name="{name}" id="{name}">'
        content += ''.join(f'<option value="{key}"'+(' selected' if key == selected else '')+f'>{esc(text)}</option>' for key, text in options)
        content += '</select></div>'
    content += f'<button type="submit">Apply</button><a class="button secondary" href="{link("/explore", report=report["report_id"])}">Reset</a></form>'
    start = (page - 1) * PAGE_SIZE + 1 if total else 0
    content += f'<div class="section-heading"><div><h2>{total:,} matching stocks</h2><p>Showing {start:,}–{min(page * PAGE_SIZE, total):,} · search covers the entire scanned universe</p></div>{export_links(report)}</div>'
    rows = []
    for a in assets:
        c, metrics = a.get("combined", {}), a.get("metrics", {})
        status_badge = badge("Technical pass", "good") if a.get("status") == "eligible" else badge("Excluded", "warn")
        if c.get("candidate"):
            status_badge = badge("Combined candidate", "good")
        rows.append(f'<tr><td>{stock_cell(report,a)}</td><td>{score_cell(c.get("score"))}</td>'
                    f'<td class="num">{number(a.get("score"))}</td><td class="num">{money(metrics.get("close_inr"))}</td>'
                    f'<td class="num {"positive" if (metrics.get("momentum_20d") or 0) >= 0 else "negative"}">{percent(metrics.get("momentum_20d"))}</td>'
                    f'<td class="num">{percent(metrics.get("trend_50d"))}</td><td class="num">{number(metrics.get("volume_ratio_20d"),2,"x")}</td>'
                    f'<td class="num">{percent(metrics.get("volatility_20d_annualized"))}</td><td>{profile_badge(a)}</td><td>{status_badge}</td></tr>')
    if rows:
        content += table(("Stock", "Combined /100", "Technical /100", "Raw close", "20 sessions", "Vs 50-session mean", "Relative volume", "Ann. volatility", "Financials", "Screen status"),
                         rows, "Searchable stock results", tall=True)
    else:
        content += empty_state("No matching stocks", "Try a shorter company name, a different filter, or reset the search.")
    content += '<div class="pagination">'
    params = {"report": report["report_id"], "q": q, "filter": kind, "sort": sort}
    content += (f'<a class="button secondary" href="{link("/explore", **params, page=page-1)}">← Previous</a>' if page > 1 else '<span></span>')
    content += f'<span class="muted">Page {page} of {pages}</span>'
    content += (f'<a class="button secondary" href="{link("/explore", **params, page=page+1)}">Next →</a>' if page < pages else '<span></span>') + '</div></section>'
    content += '<p class="muted">Technical scores and combined scores use different inputs. An unavailable combined score does not mean zero. Open a stock to see its exact exclusions and evidence dates.</p>'
    return document("Explore stocks", content, active="explore", subtitle="Search the full universe, including incomplete profiles and excluded stocks.")


def metric_value(name, metric):
    if metric is None:
        return "Unavailable"
    return percent(metric.get("value")) if name in ("revenue_yoy", "net_margin", "roce") else number(metric.get("value"), 2, "x")


def stock_html(report, asset, *, status=None, now=None, archived=False, events=None, chart_html=""):
    c, m, p = asset.get("combined", {}), asset.get("metrics", {}), asset.get("fundamentals", {})
    content = f'<p><a href="{link("/explore", report=report["report_id"])}">← Explore this report</a></p>' + freshness(report)
    content += f'<p><a class="button secondary" href="{link("/brief", report=report["report_id"], symbol=asset["symbol"])}">Read evidence &amp; AI brief →</a></p>'
    content += report_notices(report, status, now=now, archived=archived)
    content += '<div class="actions">' + profile_badge(asset)
    if c.get("candidate"):
        content += badge("Combined candidate", "good")
    content += badge("Technical pass" if asset.get("status") == "eligible" else "Technical exclusion") + '</div>'
    content += cards([
        ("Combined score /100", number(c.get("score")), f'Rank {c["rank"]}' if c.get("rank") else "Complete inputs required"),
        ("Technical score /100", number(asset.get("score")), "Adjusted price and volume"),
        ("Raw exchange close", money(m.get("close_inr")), date_text(report["last_session"])),
    ])
    content += chart_html
    content += f'<p><a class="button" href="{link("/sandbox", symbol=asset["symbol"])}">Practice Buy / Sell →</a> <span class="muted">Uses the latest saved report, even when viewing an archive.</span></p>'
    reasons = asset.get("reasons", [])
    cautions = list(dict.fromkeys(c.get("blockers", []) + c.get("candidate_blockers", []) +
                                 asset.get("blockers", []) + asset.get("warnings", []) + p.get("notes", [])))
    cautions += ["News, general announcements and valuation are not included in the combined score."]
    content += '<div class="stock-layout"><div class="stock-main"><section class="panel"><h2>What supports this result?</h2><ul>'
    content += ''.join(f'<li>{esc(r)}</li>' for r in reasons) or '<li>Technical supporting signals are unavailable.</li>'
    content += "</ul></section>"
    risk_panel = '<section class="panel"><h2>What needs attention?</h2><ul>' + ''.join(f'<li>{esc(r)}</li>' for r in cautions) + "</ul></section>"
    content += '<section class="panel flush"><div class="section-heading"><div><h2>Score breakdown</h2><p>Weighted contributions to the combined score; these are not probabilities.</p></div></div>'
    rows = []
    for f in c.get("factors", []):
        rows.append(f'<tr><td>{esc(LABELS.get(f["name"], f["name"]))}</td><td class="num">{number(f.get("normalized"),2)}</td>'
                    f'<td class="num">{number(f.get("weight",0)*100,0)}%</td><td class="num">{number(f.get("points"),2)}</td>'
                    f'<td>{esc(f.get("unavailable_reason") or "Available at report cutoff")}</td></tr>')
    content += table(("Factor", "Factor /100", "Weight", "Points", "Availability"), rows, "Combined score contributions") if rows else '<p class="section-foot">This report has no combined factor breakdown.</p>'
    content += '</section>'
    metrics = p.get("metrics", {})
    content += '<section class="panel flush"><div class="section-heading"><div><h2>Financial evidence</h2>'
    content += f'<p>{esc(p.get("basis") or "Reporting basis unavailable")} · screen: {esc(p.get("financial_screen", "unavailable"))} · {esc(p.get("industry") or "Industry unavailable")}</p></div></div>'
    rows = []
    for name, label in LABELS.items():
        if name == "technical":
            continue
        metric = metrics.get(name)
        periods = ('; '.join((date_text(x.get("start")) + " – " if x.get("start") else "As at ") + date_text(x.get("end")) for x in metric.get("periods", [])) if metric else '')
        rows.append(f'<tr><td>{esc(label)}</td><td class="num">{metric_value(name, metric)}</td><td>{esc(periods or "Unavailable")}</td>'
                    f'<td>{esc(time_text(metric.get("available_at"))) if metric else "Unavailable"}</td></tr>')
    content += table(("Metric", "Value", "Reporting periods", "Available to this installation"), rows, "Financial metrics and reporting dates") + '</section>'
    if events is not None:
        from .events_view import stock_events
        content += stock_events(events,report,asset)
    content += '<details><summary>Financial calculations and missing evidence</summary>'
    for name, label in LABELS.items():
        if name == "technical":
            continue
        metric = metrics.get(name)
        content += f'<p><strong>{esc(label)}:</strong> {esc(metric.get("formula", "Formula unavailable") if metric else p.get("missing", {}).get(name, "Required evidence missing or ineligible"))}</p>'
        if metric and metric.get("source_ids"):
            content += '<p class="hash">Source IDs: ' + esc(', '.join(metric["source_ids"])) + '</p>'
    content += '</details>'
    content += '<details><summary>Price diagnostics and corporate actions</summary><dl class="facts">'
    for label, value in (("20-session momentum", percent(m.get("momentum_20d"))),
                         ("Versus 50-session mean", percent(m.get("trend_50d"))),
                         ("Volume / prior 20-session mean", number(m.get("volume_ratio_20d"),2,"x")),
                         ("Annualized volatility", percent(m.get("volatility_20d_annualized"))),
                         ("50-session drawdown", percent(m.get("drawdown_50d"))),
                         ("Average daily turnover", money(m.get("turnover_20d_inr")))):
        content += f'<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>'
    content += f'</dl><p>Action status: {esc(asset.get("adjustment_status","unavailable").replace("_"," "))}.</p>'
    for event in asset.get("adjustments", []):
        content += f'<p>{esc(date_text(event["ex_date"]))}: {esc("; ".join(a["subject"] for a in event["actions"]))}</p>'
    content += '<p class="muted">Return and trend metrics use the adjusted history. The displayed close is the raw exchange close.</p></details>'
    content += '<details><summary>Source filings and audit references</summary><ul>'
    for s in p.get("sources", []):
        content += (f'<li>{source_link(s["uri"],"NSE financial filing")} · received {esc(time_text(s["received_at"]))}'
                    f'<div class="hash">SHA-256 {esc(s["sha256"])} · {esc(s.get("source_id",""))}</div></li>')
    if not p.get("sources"):
        content += '<li>No eligible financial filings are attached to this profile.</li>'
    content += f'</ul><p>ISIN: {esc(asset.get("isin","unavailable"))}</p><p class="hash">Report: {esc(report["report_id"])}</p>{export_links(report)}</details>'
    content += '</div><aside class="stock-aside" aria-label="Review checklist">' + risk_panel + '<section class="panel"><h2>Evidence brief</h2><p>Review saved facts, supporting sources and any model-selected draft at this report’s cutoff.</p>' + f'<a class="button" href="{link("/brief", report=report["report_id"], symbol=asset["symbol"])}">Open evidence brief →</a>' + '</section></aside></div>'
    return document(asset["symbol"], content, active="explore", subtitle=asset.get("company_name") or asset.get("instrument_id","Stock evidence"))


def system_html(report, status, workflow, *, archived=False, events_status=None, ai_status=None):
    from .workflow_view import workflow_notice
    state = workflow.get("state", "not_started")
    labels = {"ready":"Last workflow completed", "running":"Workflow in progress", "failed":"Workflow needs attention", "not_started":"No daily workflow recorded"}
    content = workflow_notice(workflow)
    if state == "running" and workflow.get("activity", {}).get("state") != "active":
        labels["running"] = "Completion unconfirmed; inspect terminal"
    content += '<p><a class="button secondary" href="/coverage">Inspect data coverage and missing inputs</a></p>'
    content += cards([
        ("Daily workflow", labels.get(state,state.replace("_"," ")), time_text(workflow.get("finished_at") or workflow.get("started_at"))),
        ("Report price session", date_text(report.get("last_session")) if report else "No report", "Selected saved report"),
        ("Windows schedule", "Not checked here", "A successful scan does not confirm task installation"),
    ])
    if report:
        content += report_notices(report,status,archived=archived) + freshness(report)
        cov = report.get("fundamental_coverage", {})
        content += '<section class="panel"><h2>Financial download progress</h2>'
        content += f'<p><strong>{cov.get("pending_documents",0):,}</strong> selected documents still uncached · <strong>{cov.get("downloaded_this_run",0):,}</strong> downloaded in this report’s run · <strong>{cov.get("failed_this_run",0):,}</strong> failed attempts.</p>'
        content += '<p class="muted">Run research.cmd to continue the next batch. Completed downloads are reused; failed documents have a cooldown. Unsupported filings and identity checks can still prevent complete coverage after downloading.</p></section>'
        content += '<div class="two-col"><section class="panel"><h2>Financial profile coverage</h2><ul class="compact-list">'
        for key, n in sorted(cov.get("statuses", {}).items(),key=lambda x:(-x[1],x[0])):
            content += f'<li>{esc(PROFILE_LABELS.get(key,key.replace("_"," ")))} <strong>{n:,}</strong></li>'
        content += '</ul></section><section class="panel"><h2>Available financial metrics</h2><ul class="compact-list">'
        for key,n in cov.get("metrics", {}).items():
            content += f'<li>{esc(LABELS.get(key,key))} <strong>{n:,}</strong></li>'
        content += '</ul></section></div>'
        counts = report["counts"]
        content += '<section class="panel"><h2>Market and calendar coverage</h2>'
        content += f'<p>{report.get("history_sessions",0)} completed price sessions · {esc(date_text(report.get("history_start")))}–{esc(date_text(report["last_session"]))}.</p>'
        content += f'<p>{counts.get("advanced",0):,} up · {counts.get("declined",0):,} down · {counts.get("unchanged",0):,} unchanged. {counts.get("action_blocked",0):,} blocked by unresolved corporate actions.</p>'
        schedule = report.get("calendar", {}).get("schedule", {})
        content += f'<p>Reviewed calendar: {esc(date_text(schedule.get("coverage_start")))}–{esc(date_text(schedule.get("coverage_end")))}.</p>'
        content += f'<p class="muted">{esc(report.get("calendar",{}).get("note",""))}</p></section>'
        content += '<details><summary>Exclusions, ranking rules and limitations</summary><ul>'
        for key,n in sorted(report.get("combined_exclusion_counts", {}).items(),key=lambda x:(-x[1],x[0])):
            content += f'<li>{n:,}: {esc(key)}</li>'
        content += '</ul><h3>Technical exclusions</h3><ul>'
        for key,n in sorted(report.get("exclusion_counts", {}).items(),key=lambda x:(-x[1],x[0])):
            content += f'<li>{n:,}: {esc(key)}</li>'
        content += '</ul><p>' + esc(report.get("ranking_policy", {}).get("requirements", "This report uses technical screening only.")) + '</p><ul>'
        content += ''.join(f'<li>{esc(v)}</li>' for v in report.get("limitations",[])) + '</ul></details>'
        content += '<details><summary>Price and metadata source receipts</summary><ul>'
        for s in report.get("sources", []) + report.get("evidence_sources", []):
            content += f'<li>{source_link(s["uri"], s.get("session",s.get("kind","Source")))} · received {esc(time_text(s["received_at"]))}<div class="hash">SHA-256 {esc(s["sha256"])}</div></li>'
        content += '</ul></details>'
    else:
        content += empty_state("No published daily report", "Start research.cmd in your project folder. If an update failed, its status is shown above.")
        if status:
            content += f'<div class="notice">Research phase: {esc(status.get("state","unknown"))}. {esc(status.get("error") or "")}</div>'
    if events_status is not None:
        from .events_view import source_health
        content += source_health(events_status)
    if ai_status is not None:
        from .briefs_view import ai_health
        content += ai_health(ai_status)
    content += '<details><summary>Check automation or refresh data</summary><p>In PowerShell, from the project folder containing run.cmd:</p><pre>.\\run.cmd schedule-status</pre><p>To install the daily task:</p><pre>.\\run.cmd schedule-install</pre><p>To refresh research and advance the virtual experiment:</p><pre>.\\research.cmd</pre><p>Scheduled runs are at 19:00 and 21:00 computer-local time and at sign-in. The PC must be awake, plugged in, online and signed in.</p></details>'
    content += f'<details><summary>Workflow details</summary><p>Phase: {esc(workflow.get("phase","not started"))}</p><p>Started: {esc(time_text(workflow.get("started_at")))}</p><p>Finished: {esc(time_text(workflow.get("finished_at")))}</p><a href="/api/automation">Workflow JSON</a></details>'
    return document("Data & system", content, active="system", subtitle="Data coverage, update health and the checks needed to keep research current.")
