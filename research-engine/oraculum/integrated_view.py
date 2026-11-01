"""Read-only combined evidence report; no JavaScript, network assets or order controls."""
import csv
from datetime import datetime
import io

from .contracts import IST, timestamp
from .financials import METRICS
from .local_web import document, esc
from .research_view import freshness_notice, percent

LABELS = {"revenue_yoy": "Quarter revenue YoY", "net_margin": "Quarter net margin",
          "borrowings_to_equity": "Borrowings / equity", "roce": "Annual ROCE",
          "annual_pe": "Annual-EPS P/E", "peer_pe_ratio": "P/E / cached-peer median"}


def metric_text(name, metric):
    if metric is None:
        return "Unavailable"
    value = metric["value"]
    return f"{value:+.2%}" if name in ("revenue_yoy", "net_margin", "roce") else f"{value:.2f}x"


def integrated_csv(report):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    price_fields = ["close_inr", "raw_return_1d", "return_1d", "momentum_20d", "trend_50d", "volume_ratio_20d", "turnover_20d_inr", "volatility_20d_annualized"]
    writer.writerow(["session", "symbol", "isin", "technical_status", "technical_rank", "technical_score", "technical_highlight",
                     "combined_status", "combined_rank", "combined_score", "combined_coverage", "combined_highlight", "combined_blockers",
                     *price_fields, "adjustment_status", "financial_status", "basis", "quarter_end", "industry", "financial_screen",
                     *METRICS, *[m+"_periods" for m in METRICS], "blockers", "notes", "report_id"])
    for asset in report["assets"]:
        p = asset["fundamentals"]
        values, periods = [], []
        for name in METRICS:
            metric = p["metrics"][name]
            values.append(metric["value"] if metric else "")
            periods.append("; ".join((v["start"]+" to " if v["start"] else "as at ")+v["end"] for v in metric["periods"]) if metric else "")
        combined = asset.get("combined", {})
        writer.writerow([report["last_session"], asset["symbol"], asset["isin"], asset["status"], asset["rank"], asset["score"], asset["highlight"],
                         *[combined.get(k, "") for k in ("status", "rank", "score", "coverage", "highlight")], "; ".join(combined.get("blockers", [])),
                         *[asset["metrics"].get(k) for k in price_fields], asset["adjustment_status"], p["status"], p["basis"], p["quarter_end"], p["industry"], p["financial_screen"],
                         *values, *periods, "; ".join(asset["blockers"]), "; ".join(asset["warnings"]+p["notes"]), report["report_id"]])
    return out.getvalue()


def financial_detail(asset):
    p = asset["fundamentals"]
    content = (f"<p>Financial coverage: <strong>{esc(p['status'])}</strong> · {esc(p['basis'] or 'basis unavailable')} · "
               f"latest catalogue quarter {esc(p['quarter_end'] or 'unavailable')} · industry {esc(p['industry'] or 'unmapped')}</p>")
    content += "<div class='scroll'><table><thead><tr><th>Metric</th><th>Value</th><th>Periods</th></tr></thead><tbody>"
    for name in METRICS:
        metric = p["metrics"][name]
        periods = "; ".join((v["start"]+" to " if v["start"] else "as at ")+v["end"] for v in metric["periods"]) if metric else "Required evidence missing or ineligible"
        content += f"<tr><td>{esc(LABELS[name])}</td><td>{esc(metric_text(name,metric))}</td><td>{esc(periods)}</td></tr>"
    content += f"</tbody></table></div><p>Separate financial screen: <strong>{esc(p['financial_screen'])}</strong>. This is not included in the technical score.</p>"
    if p["notes"]:
        content += "<ul>"+"".join(f"<li>{esc(n)}</li>" for n in p["notes"])+"</ul>"
    for name, metric in p["metrics"].items():
        if metric:
            content += f"<p class='muted'>{esc(LABELS[name])}: {esc(metric['formula'])}. Available to this installation since {esc(metric['available_at'])}.</p>"
    if p["sources"]:
        content += "<p>Financial statement evidence:</p><ul>"+"".join(
            f"<li><a href='{esc(s['uri'])}'>NSE XBRL filing</a> · received {esc(s['received_at'])}<br><small>SHA-256 {esc(s['sha256'])}</small></li>" for s in p["sources"])+"</ul>"
    return content


def combined_section(report):
    if "ranking_policy" not in report:
        return ""
    counts = report["counts"]
    content = ("<h2>Combined research ranking</h2>"
        f"<p>{counts['combined_eligible']:,} stocks have the required technical and financial evidence; "
        f"{counts['combined_candidates']:,} meet the candidate rules. Up to ten are highlighted.</p>"
        "<p>60% technical score + 10% revenue growth + 10% net margin + 10% borrowings/equity + 10% ROCE. "
        "All four financial inputs are required. Missing data withholds the combined score. "
        "Valuation, news and nonfinancial announcements are not scored in this version.</p>")
    ranked = sorted((a for a in report["assets"] if a["combined"]["rank"] is not None),key=lambda a:a["combined"]["rank"])
    if not ranked:
        content += "<div class='notice'>No complete combined ranking yet. More financial filings are needed; the technical ranking remains available below.</div>"
    for a in [a for a in ranked if a["combined"]["highlight"]]:
        c = a["combined"]
        content += (f"<details><summary><strong>{esc(a['symbol'])}</strong> · combined {c['score']:.1f}/100 · "
                    f"technical {a['score']:.1f}/100 · INR {a['metrics']['close_inr']:,.2f}</summary>"
                    "<p>Passed technical filters and the four-metric financial screen, with positive momentum and trend. "
                    "This is a research candidate; the score is not a profit probability.</p>"
                    "<table><tr><th>Factor</th><th>Factor score / 100</th><th>Weight</th><th>Points</th></tr>")
        for f in c["factors"]:
            content += f"<tr><td>{esc(f['name'])}</td><td>{f['normalized']:.2f}</td><td>{f['weight']:.0%}</td><td>{f['points']:.2f}</td></tr>"
        content += "</table>"+financial_detail(a)+"</details>"
    if ranked:
        content += "<div class='scroll'><table><tr><th>Rank</th><th>Stock</th><th>Combined</th><th>Technical</th><th>Candidate</th><th>Candidate blockers</th></tr>"
        for a in ranked[:100]:
            c=a["combined"]
            content += "<tr>"+"".join(f"<td>{esc(x)}</td>" for x in (c["rank"],a["symbol"],f"{c['score']:.2f}",f"{a['score']:.2f}","Yes" if c["candidate"] else "No","; ".join(c["candidate_blockers"])))+"</tr>"
        content += "</table></div>"
    content += "<details><summary>Combined ranking exclusions and formulas</summary><ul>"+"".join(f"<li>{n:,}: {esc(reason)}</li>" for reason,n in sorted(report["combined_exclusion_counts"].items()))+"</ul><ul>"
    content += "".join(f"<li>{esc(name)}: {esc(formula)}</li>" for name,formula in report["ranking_policy"]["normalization"].items())+"</ul></details>"
    return content


def integrated_html(report, status=None, *, standalone=False, now=None):
    if not standalone:
        from .dashboard_view import today_html
        return today_html(report, status, now=now)
    count, coverage = report["counts"], report["fundamental_coverage"]
    ident = report["report_id"]
    csv_link = f"{ident}.csv" if standalone else f"/research/{ident}.csv"
    json_link = f"{ident}.json" if standalone else f"/api/research/{ident}"
    content = freshness_notice(report,status,now=now)
    content += ("<p class='tag'>ORACULUM · ADJUSTED PRICES + SOURCED FINANCIAL STATEMENTS</p>"
                f"<p>Prices through <strong>{esc(report['last_session'])}</strong> · "
                f"Built {esc(timestamp(report['as_of'],'as_of').astimezone(IST).strftime('%d %b %Y, %H:%M IST'))}</p>")
    cards = [(count["scanned"],"stocks inspected"),(count["eligible"],"pass technical filters"),
             (count["adjusted_stocks"],"with applied actions"),(coverage["statuses"].get("available",0),"all four financial screen metrics"),
             (coverage["statuses"].get("partial",0),"partial financial profiles")]
    content += "<div class='row'>"+"".join(f"<div class='card'><strong>{n:,}</strong><br><small>{esc(label)}</small></div>" for n,label in cards)+"</div>"
    content += ("<div class='notice'><strong>How to read this:</strong> the combined ranking uses the disclosed technical and financial factors when present. The separate technical ranking compares adjusted price and volume features. "
                "Financial statements retain their own periods and source links. "
                "Missing figures are unavailable, not zero. A financial-screen pass is a research filter, not a buy recommendation. "
                "News and non-financial announcements still need review. The report itself places no orders.</div>")
    for warning in report["refresh_warnings"]:
        content += f"<div class='notice'>{esc(warning)}</div>"
    content += (f"<p>{report['history_sessions']} price sessions, {esc(report['history_start'])}–{esc(report['last_session'])}. "
                f"Raw latest-session breadth: {count['advanced']:,} up / {count['declined']:,} down / {count['unchanged']:,} unchanged. "
                f"{count['action_blocked']:,} stocks blocked by unresolved actions.</p>"
                f"<p><a href='{csv_link}' download>All stocks and financial metrics (CSV)</a> · <a href='{json_link}'>Full evidence report (JSON)</a></p>")
    content += ("<h2>Financial data coverage</h2>"
                f"<p>This run downloaded {coverage['downloaded_this_run']} filings; {coverage['failed_this_run']} attempts failed. "
                f"{coverage['pending_documents']:,} selected documents are still uncached. Run <code>research.cmd</code> again to continue the next batch. "
                "Each run reuses completed downloads. Failed documents have a 24-hour cooldown; access-denial stops the current batch.</p>"
                "<p>"+" · ".join(f"{esc(LABELS[m])}: {n:,}" for m,n in coverage["metrics"].items())+"</p>"
                "<p>Statuses: "+esc(", ".join(f"{k}: {v:,}" for k,v in coverage["statuses"].items()))+".</p>")
    content += combined_section(report)
    content += "<h2>Technical research highlights</h2><p>Positive adjusted momentum and trend, score at least 55, and all technical filters passed. Up to ten stocks.</p>"
    highlights = [a for a in report["assets"] if a["highlight"]]
    if not highlights:
        content += "<p>No stocks met all technical highlight rules.</p>"
    for a in highlights:
        content += (f"<details><summary><strong>{esc(a['symbol'])}</strong> · {a['score']:.1f}/100 technical score · "
                    f"INR {a['metrics']['close_inr']:,.2f} · financials: {esc(a['fundamentals']['status'])}</summary>"
                    "<ul>"+"".join(f"<li>{esc(r)}</li>" for r in a["reasons"]+a["warnings"])+"</ul>")
        if a["adjustments"]:
            content += "<p>Applied actions: "+esc("; ".join(e["ex_date"]+": "+", ".join(t["subject"] for t in e["actions"]) for e in a["adjustments"]))+".</p>"
        content += financial_detail(a)+"</details>"
    content += "<h2>Technical ranking</h2><p>First 100 eligible stocks. Percentage returns use the adjusted history; the quoted close is the actual raw exchange close.</p><div class='scroll'><table><thead><tr><th>Rank</th><th>Stock</th><th>Score</th><th>Close INR</th><th>20 sessions</th><th>Volume</th><th>Financials</th><th>Revenue YoY</th><th>Borrowings/equity</th></tr></thead><tbody>"
    for a in report["assets"]:
        if a["rank"] is not None and a["rank"] <= 100:
            p,m = a["fundamentals"],a["metrics"]
            cells=[a["rank"],a["symbol"],f"{a['score']:.1f}",f"{m['close_inr']:,.2f}",percent(m["momentum_20d"]),f"{m['volume_ratio_20d']:.2f}x",p["status"],metric_text("revenue_yoy",p["metrics"]["revenue_yoy"]),metric_text("borrowings_to_equity",p["metrics"]["borrowings_to_equity"])]
            content += "<tr>"+"".join(f"<td>{esc(c)}</td>" for c in cells)+"</tr>"
    content += "</tbody></table></div><h2>Other available financial profiles</h2><p>Up to 200 additional profiles with at least one metric. Every profile is included in JSON and CSV.</p>"
    profiles = [a for a in report["assets"] if not a["highlight"] and any(a["fundamentals"]["metrics"].values())]
    for a in profiles[:200]:
        content += f"<details><summary>{esc(a['symbol'])} · {esc(a['fundamentals']['status'])} · technical status: {esc(a['status'])}</summary>"+financial_detail(a)+"</details>"
    content += "<details><summary>Exclusions and methods</summary><ul>"+"".join(f"<li>{n:,}: {esc(reason)}</li>" for reason,n in sorted(report["exclusion_counts"].items(),key=lambda x:(-x[1],x[0])))+"</ul>"
    content += ("<p>Technical score: base 50; momentum ±22.5; trend ±17.5; volume confirms momentum up to ±10; volatility penalty up to 15. "
                "Requires 50 consecutive traded sessions, average turnover at least INR 5 crore/day, annualized volatility at most 80%, "
                "and no adjusted daily move of 20% or more. Unsupported share actions block eligibility.</p>"
                "<p>The separate financial screen requires revenue growth &gt; 0, net margin &gt; 0, borrowings/equity from 0 to 1.5, "
                "and annual ROCE at least 10%. All four must be available; it is an unvalidated heuristic. See docs/DATA_FUNDAMENTALS.md for exact definitions.</p></details>")
    content += "<details><summary>Coverage and limitations</summary><ul>"+"".join(f"<li>{esc(x)}</li>" for x in report["limitations"])+f"</ul><p>{esc(report['calendar']['note'])}</p></details>"
    content += "<details><summary>Price and metadata source receipts</summary><ul>"
    for s in report["sources"]+report["evidence_sources"]:
        label=s.get("session",s.get("kind","source"))
        content += f"<li><a href='{esc(s['uri'])}'>{esc(label)}</a> · received {esc(s['received_at'])}<br><small>SHA-256 {esc(s['sha256'])}</small></li>"
    content += "</ul></details>"
    if not standalone:
        content += "<p><a href='/research-history'>Daily report history</a> · <a href='/forward'>Forward paper evaluation</a> · <a href='/history'>Earlier manual engine</a></p>"
    content += f"<p class='muted'>Report ID: {esc(ident)}</p>"
    return document("Daily market research",content, standalone=standalone)
