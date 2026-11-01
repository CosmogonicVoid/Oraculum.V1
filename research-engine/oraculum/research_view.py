"""Readable real-data report, also usable as an offline HTML file."""
from datetime import datetime

from .contracts import IST, UTC, timestamp
from .local_web import document, esc


def percent(value):
    return "—" if value is None else f"{value:+.2%}"


def freshness_notice(report, status=None, *, now=None):
    now = now or datetime.now(UTC)
    messages = []
    schedule = report["calendar"]["schedule"]
    today = now.astimezone(IST).date().isoformat()
    if not schedule["coverage_start"] <= today <= schedule["coverage_end"]:
        messages.append("CALENDAR UPDATE REQUIRED. This saved report cannot establish current market freshness.")
    else:
        closed = [s["session"] for s in schedule["sessions"] if timestamp(s["close_at"], "close_at") <= now]
        if closed and max(closed) > report["last_session"]:
            messages.append(f"OLDER REPORT: expected completed session {max(closed)}, but these prices are from {report['last_session']}. Run research.cmd to update.")
    if status and status.get("state") == "failed":
        messages.append("LATEST UPDATE FAILED: " + str(status.get("error", "Unknown error")) + ". The last successful report is shown below.")
    elif status and status.get("state") == "running":
        from .activity import activity_message
        messages.append(activity_message(status))
        messages.append(f"Price history: {status.get('completed_sessions', 0)}/{status.get('total_sessions', 60)} sessions prepared. This is not overall completion.")
        if status.get("last_message"):
            from .ui import time_text
            messages.append(str(status["last_message"]) + " · Last progress: " + time_text(status.get("updated_at")))
    return "".join(f"<div class='notice'>{esc(m)}</div>" for m in messages)


def research_html(report, status=None, *, standalone=False, now=None):
    if not standalone:
        from .dashboard_view import today_html
        return today_html(report, status, now=now)
    if report.get("report_schema") in ("oraculum-integrated-research-v1", "oraculum-integrated-research-v2"):
        from .integrated_view import integrated_html
        return integrated_html(report, status, standalone=standalone, now=now)
    count = report["counts"]
    download = (f"{report['report_id']}.csv" if standalone else f"/research/{report['report_id']}.csv")
    json_link = f"{report['report_id']}.json" if standalone else f"/api/research/{report['report_id']}"
    content = freshness_notice(report, status, now=now)
    content += (f"<p class='tag'>REAL NSE END-OF-DAY DATA · PRICE / VOLUME RESEARCH</p>"
                f"<p>Prices through <strong>{esc(report['last_session'])}</strong> · "
                f"Built {esc(timestamp(report['as_of'], 'as_of').astimezone(IST).strftime('%d %b %Y, %H:%M IST'))}</p>"
                "<div class='row'>" + "".join(f"<div class='card'><strong>{value:,}</strong><br><small>{label}</small></div>"
                for value, label in ((count['scanned'], 'stocks inspected'), (count['eligible'], 'pass technical filters'),
                                     (count['highlights'], 'research highlights'), (count['excluded'], 'excluded'))) + "</div>"
                f"<p>{report['history_sessions']} exchange sessions: {esc(report['history_start'])}–{esc(report['last_session'])}. "
                f"Latest breadth: {count['advanced']:,} up / {count['declined']:,} down / {count['unchanged']:,} flat "
                f"among {count['breadth_observations']:,} stocks with consecutive closes.</p>"
                "<div class='notice'><strong>What this answers:</strong> which liquid stocks have stronger recent price trends, "
                "what their volume shows, and which fail the research filters. "
                "<strong>Fundamentals, news and corporate announcements are not assessed.</strong> "
                "These are research leads; no stock is declared a buy and no order is created.</div>")
    highlighted = [a for a in report["assets"] if a["highlight"]]
    content += "<h2>Research highlights</h2><p>Positive 20-session return, above the 50-session average, score at least 55, and all technical filters passed. Up to ten stocks.</p>"
    if not highlighted:
        content += "<div class='notice'>No stocks met all highlight rules for this session. The report has abstained from highlighting a setup.</div>"
    for asset in highlighted:
        m = asset["metrics"]
        reasons = "".join(f"<li>{esc(r)}</li>" for r in asset["reasons"])
        risks = "".join(f"<li>{esc(r)}</li>" for r in asset["warnings"])
        content += (f"<details><summary><strong>{esc(asset['symbol'])}</strong> · score {asset['score']:.1f}/100 · "
                    f"INR {m['close_inr']:,.2f} · 20-session return {percent(m['momentum_20d'])}</summary>"
                    f"<ul>{reasons}</ul><p>Annualized volatility {m['volatility_20d_annualized']:.1%} · "
                    f"50-session maximum drawdown {percent(m['drawdown_50d'])}</p><ul>{risks}"
                    "<li>Financial condition, valuation, announcements and corporate actions still need review.</li></ul>"
                    f"<p class='muted'>Score contributions: {esc(', '.join(k.replace('_', ' ') + ' ' + format(v, '+.2f') for k, v in asset['components'].items()))}; base 50.</p></details>")
    content += (f"<p><a href='{download}' download>Download all stocks as CSV</a> · "
                f"<a href='{json_link}'>Full report and source hashes (JSON)</a></p><h2>Technical ranking</h2>"
                "<p>First 100 eligible stocks. Scores compare this heuristic's inputs; they are not confidence percentages. CSV and JSON include every inspected stock and exclusion.</p>")
    rows = []
    for asset in (a for a in report["assets"] if a["rank"] is not None and a["rank"] <= 100):
        m = asset["metrics"]
        cells = [asset["rank"], asset["symbol"], f"{asset['score']:.1f}", f"{m['close_inr']:,.2f}",
                 percent(m["return_1d"]), percent(m["momentum_20d"]), percent(m["trend_50d"]),
                 f"{m['volume_ratio_20d']:.2f}x", f"{m['turnover_20d_inr'] / 1e7:.2f}",
                 f"{m['volatility_20d_annualized']:.1%}"]
        rows.append("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in cells) + "</tr>")
    content += ("<div class='scroll'><table><thead><tr><th>Rank</th><th>Stock</th><th>Score</th><th>Close INR</th>"
                "<th>1 session</th><th>20 sessions</th><th>Vs 50-session mean</th><th>Volume</th><th>Turnover cr/day</th>"
                f"<th>Volatility</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
    exclusions = sorted(report["exclusion_counts"].items(), key=lambda item: (-item[1], item[0]))
    content += "<details><summary>Why stocks were excluded</summary><p>A stock may fail more than one rule.</p><ul>"
    content += "".join(f"<li>{value:,}: {esc(reason)}</li>" for reason, value in exclusions) + "</ul>"
    content += f"<p>Other rows skipped in the latest exchange file: {esc(report['skipped_latest_rows'])}.</p></details>"
    content += ("<details><summary>How the score works</summary><p>Start at 50. Add up to ±22.5 for 20-session momentum "
                "and ±17.5 for distance from the 50-session mean. Higher volume can add or subtract up to 10 points, "
                "confirming momentum's direction. Subtract up to 15 for volatility. Clip the result to 0–100.</p>"
                "<p>Filters require 50 consecutive traded sessions, average daily turnover of at least INR 5 crore, "
                "annualized volatility no higher than 80%, and no daily raw-price move of 20% or more in the last 50 closes. "
                "A large move may be a corporate action; the filter cannot identify all such events.</p>"
                f"<p>Algorithm: {esc(report['algorithm'])}. Full formulas are in docs/REAL_DATA.md.</p></details>")
    content += "<details><summary>Coverage and limitations</summary><ul>" + "".join(f"<li>{esc(x)}</li>" for x in report["limitations"]) + "</ul>"
    content += f"<p>{esc(report['calendar']['note'])}</p></details>"
    content += "<details><summary>Exchange files and receipt times</summary><ul>" + "".join(
        f"<li><a href='{esc(s['uri'])}'>{esc(s['session'])}</a> · received {esc(s['received_at'])}<br>"
        f"<small>SHA-256 {esc(s['sha256'])}</small></li>" for s in report["sources"]) + "</ul></details>"
    if not standalone:
        content += "<p><a href='/history'>Full-engine runs and virtual portfolio</a> · Run research.cmd to refresh this report.</p>"
    content += f"<p class='muted'>Report ID: {esc(report['report_id'])}</p>"
    return document("Daily market research", content, standalone=standalone)
