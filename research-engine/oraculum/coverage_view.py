"""Coverage notebook and operational guidance; no inference or writes."""

from .coverage import FILTERS
from .dashboard_view import LABELS, PROFILE_LABELS, table
from .ui import badge, cards, document, empty_state, esc, link, time_text


def coverage_html(result, health):
    content = '<p>Coverage describes the saved report. Current workflow activity is shown separately on <a href="/system">System</a>. Refresh this page to read the latest saved state.</p>'
    if not result["report_id"]:
        return document(
            "Data coverage",
            content
            + empty_state(
                "No saved report",
                "Run research.cmd first. No data is created by opening this page.",
            ),
            active="coverage",
        )
    ident = result["report_id"]
    count, collection = result["counts"], result["collection"]
    content += f'<p>Prices: <strong>{esc(result["last_session"])}</strong> · Evidence cutoff: {esc(time_text(result["as_of"]))}</p>'
    content += cards(
        [
            (
                "Universe inspected",
                str(count["scanned"]),
                "Current report only; not every listed stock",
            ),
            (
                "Four evidenced inputs",
                str(count["complete"]),
                f'{count["incomplete"]} incomplete profiles',
            ),
            (
                "Combined eligible",
                str(count["combined_eligible"]),
                "Also requires technical eligibility",
            ),
        ]
    )
    content += f'<div class="notice">{esc(health["message"])}'
    if "calendar_days_remaining" in health:
        content += f' Calendar coverage ends {esc(health["coverage_end"])} ({health["calendar_days_remaining"]} days remaining).'
    content += "</div><p>Missing data is not a failed business and is never filled with zero. A complete profile is not a buy recommendation.</p>"
    rows = [
        f'<tr><td>{esc(LABELS[key])}</td><td>{n} / {count["scanned"]}</td><td>{count["scanned"]-n}</td></tr>'
        for key, n in result["metric_counts"].items()
    ]
    content += (
        '<section class="panel"><h2>Financial input coverage</h2>'
        + table(
            ("Input", "Evidenced", "Missing / needs review"), rows, "Financial coverage"
        )
        + "</section>"
    )
    content += '<section class="panel"><h2>Last report’s filing batch</h2>' + cards(
        [
            (
                "Downloaded",
                str(collection.get("downloaded_this_run", "Not recorded")),
                "Successful documents in this batch",
            ),
            (
                "Pending documents",
                str(collection.get("pending_documents", "Not recorded")),
                "May include unavailable or unsupported documents",
            ),
            (
                "Failed",
                str(collection.get("failed_this_run", "Not recorded")),
                "Failures have bounded retry cooldowns",
            ),
        ]
    )
    if collection.get("provider_retry_at"):
        content += (
            '<div class="notice">Filing provider paused until '
            + esc(time_text(collection["provider_retry_at"]))
            + " when this report was built. Repeated runs do not bypass this cooldown.</div>"
        )
    content += "<p>To collect another bounded batch, run <code>.\\research.cmd</code>. Completed documents are reused. Unsupported bank/insurance schemas and missing catalogue filings need different source/parser support; rerunning cannot manufacture them.</p></section>"
    for warning in result["warnings"]:
        content += '<div class="notice">' + esc(warning) + "</div>"
    content += f'<form class="panel" method="get" action="/coverage"><input type="hidden" name="report" value="{esc(ident)}"><label for="coverage-search">Company or symbol</label><input id="coverage-search" name="q" maxlength="80" value="{esc(result["query"])}"><label for="coverage-filter">Coverage filter</label><select id="coverage-filter" name="filter">'
    for key in FILTERS:
        label = {
            "technical": "Technical exclusions",
            "older_financials": "Quarter over 180 days old",
            "incomplete": "Missing financial inputs",
            "complete": "Four evidenced financial inputs",
        }.get(key, PROFILE_LABELS.get(key, key.replace("_", " ").title()))
        content += f'<option value="{key}"{" selected" if key == result["filter"] else ""}>{esc(label)}</option>'
    content += '</select><button type="submit">Inspect coverage</button></form>'
    rows = []
    for r in result["items"]:
        reasons = (
            [LABELS[k] + ": " + v for k, v in r["gaps"].items()]
            + r["blockers"]
            + r["notes"]
        )
        detail = (
            "<details><summary>Why / what to check</summary><ul>"
            + "".join("<li>" + esc(x) + "</li>" for x in reasons)
            + "</ul></details>"
            if reasons
            else "Inputs available; source truth still requires review."
        )
        age = (
            str(r["quarter_age_days"]) + " days at cutoff"
            if r["quarter_age_days"] is not None
            else "Period not recorded"
        )
        rows.append(
            f'<tr><td><a href="{link("/stock", report=ident, symbol=r["symbol"])}">{esc(r["symbol"])}</a><div class="company">{esc(r["company_name"])}</div></td><td>{r["financial_inputs"]}/4 · {esc(PROFILE_LABELS.get(r["profile_status"],r["profile_status"]))}</td><td>{esc(age)}</td><td>{detail}</td></tr>'
        )
    content += f'<p>{result["total"]} matches; showing {len(rows)} from offset {result["offset"]}. Export links include all matches.</p>'
    content += (
        table(
            (
                "Stock",
                "Financials",
                "Latest quarter age",
                "Missing evidence and exclusions",
            ),
            rows,
            "Coverage details",
        )
        if rows
        else empty_state("No matches", "Try another symbol or filter.")
    )
    params = {"report": ident, "q": result["query"], "filter": result["filter"]}
    content += '<div class="actions">'
    if result["offset"]:
        content += f'<a href="{link("/coverage", **params, offset=max(0,result["offset"]-40))}">Previous page</a>'
    if result["next_offset"] is not None:
        content += f'<a href="{link("/coverage", **params, offset=result["next_offset"])}">Next page</a>'
    content += f'<a href="{link("/coverage.csv", **params)}">Export matching CSV</a><a href="{link("/api/coverage", **params)}">Coverage JSON</a></div>'
    content += (
        "<details><summary>Definitions and limits</summary><p>"
        + esc(result["definitions"])
        + "</p><p>Financial ages use the report cutoff, not today. This page does not rescore stocks. News coverage remains partial; no headline is not proof of no event. See News for its source health.</p></details>"
    )
    return document(
        "Data coverage",
        content,
        active="coverage",
        subtitle="See what is known, what is missing, and why a stock cannot be ranked.",
    )
