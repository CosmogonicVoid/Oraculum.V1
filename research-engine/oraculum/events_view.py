"""Source-linked news and announcement views; remote text is always escaped."""
import csv
from io import StringIO

from .event_sources import FEEDS
from .ui import badge, cards, document, empty_state, esc, link, source_link, time_text


def source_health(status):
    content = '<section class="panel"><h2>Collection health</h2>'
    if status.get("error"):
        content += '<div class="notice">'+esc(status["error"])+ '</div>'
    for source in status.get("sources", []):
        state = source.get("state", "not_started")
        label = "Never collected" if state == "not_started" else "Refresh failed" if state == "failed" else "Interrupted refresh" if state == "refreshing" else "Stale cache" if source.get("stale") else "Collected"
        content += '<details><summary>' + esc(source["name"]) + ' · ' + esc(label) + '</summary>'
        content += '<p>Last successful collection: ' + esc(time_text(source.get("last_success_at"))) + '</p>'
        counts = source.get("counts", {})
        if counts:
            content += f'<p>Last successful response: {counts.get("accepted",0):,} valid items; {counts.get("matched_items",0):,} matched; {counts.get("skipped",0):,} skipped. Missing publication times: {counts.get("unknown_publication",0):,}; future dates at collection: {counts.get("future_publication",0):,}; identity conflicts: {counts.get("identity_conflicts",0):,}.</p>'
            if not counts.get("accepted"):
                content += '<p class="muted">An empty feed is not proof that no company events occurred. RSS feeds may reset or contain only a short rolling window.</p>'
        if source.get("error"):
            content += '<div class="notice">' + esc(source["error"]) + '</div>'
        content += '<p>Next permitted refresh: ' + esc(time_text(source.get("next_attempt_at"))) + '</p>'
        content += source_link(source.get("request_url") or source["home"], "Feed source") + '</details>'
    content += '<p class="muted">'+esc(status.get("coverage", "Feed coverage is partial."))+'</p></section>'
    return content


def event_cards(result, *, report=None):
    content = ''
    if result.get("notice"):
        content += '<div class="notice">'+esc(result["notice"])+'</div>'
    for item in result["items"]:
        content += '<article class="panel event-card">'
        content += '<div class="actions">' + badge({"news":"Publisher news","announcement":"Official announcement","board_meeting":"Board meeting"}[item["kind"]]) + badge(item["category"]) + '</div>'
        content += '<h3>' + source_link(item["url"],item["title"]) + '</h3>'
        content += '<p class="muted">' + esc(item["source_name"]) + ' · Published ' + esc(time_text(item["published_at"])) + '</p>'
        if item["excerpt"]:
            content += '<p>'+esc(item["excerpt"])+'</p>'
        if not item["published_at"]:
            content += '<p class="notice">Publication time is missing or could not be parsed. Collection time is not publication time.</p>'
        if item["timing"] == "future_publication":
            content += '<p class="notice">The publisher date was in the future when collected; review its timestamp.</p>'
        content += '<div class="actions">'
        for match in item["matches"]:
            # Only link to a report stock if its identity still agrees with this event.
            asset = next((a for a in report["assets"] if a["symbol"] == match["symbol"] and a.get("isin") == match.get("isin")),None) if report else None
            label = esc(match["symbol"])
            content += (f'<a href="{link("/stock",report=report["report_id"],symbol=match["symbol"])}">{label}</a>' if asset else '<span>'+label+'</span>')
        if not item["matches"]:
            content += badge("Identity conflict — unassigned", "warn") if item["match_state"] == "identity_conflict" else badge("Company unassigned")
        content += '</div><details><summary>Collection & matching evidence</summary>'
        content += '<p>First seen here: '+esc(time_text(item["first_seen_at"]))+' · This revision collected: '+esc(time_text(item["received_at"]))+'</p>'
        if item.get("reported_symbol") or item.get("reported_isin"):
            content += '<p>Exchange-reported identity: '+esc(item.get("reported_symbol") or "Symbol unavailable")+' · '+esc(item.get("reported_isin") or "ISIN unavailable")+'</p>'
        if item["matches"]:
            content += '<ul>' + ''.join('<li>'+esc(m["symbol"]+' · '+m["method"].replace('_',' ')+' · '+str(m.get("isin") or 'ISIN unavailable'))+'</li>' for m in item["matches"]) + '</ul>'
        content += '<p>Company-name mentions are tentative text matches; they do not establish which company a story materially affects. Categories use keywords, with no sentiment or impact score.</p>'
        receipt = item["receipt"]
        content += source_link(receipt["url"],"Original feed") + '<p class="hash">Feed SHA-256: '+esc(receipt["sha256"])+ '</p>'
        content += '<p class="hash">Event '+esc(item["event_id"])+f' · revision {item["revision_id"]}</p></details></article>'
    if not result["items"]:
        content += empty_state("No items in this view", "No matching collected items are available within the selected 30-day window and cutoff. This is not evidence that no news exists.")
    return content


def stock_events(result, report, asset):
    content = '<section aria-labelledby="events-heading"><h2 id="events-heading">News & announcements</h2>'
    content += '<p class="muted">Evidence known by this report’s cutoff, limited to the preceding 30 days. These items do not affect the combined score or paper orders.</p>'
    content += event_cards(result,report=report)
    content += f'<p><a href="{link("/news",report=report["report_id"],symbol=asset["symbol"])}">All collected items for this report and stock ({result["total"]}) →</a> · <a href="/news">Current news collection</a></p></section>'
    return content


def news_html(result, status, query, *, report=None, pinned=False):
    from .ui import research_tabs
    content = research_tabs("news", report["report_id"] if pinned and report else None) + '<div class="notice">' + (f'Report snapshot: items known by {esc(time_text(result["as_of"]))}. <a href="/news">Open the current collection</a>.' if pinned else 'Current local collection. Article dates and collection times are shown separately; opening this page does not fetch data.') + '</div>'
    content += '<p>Headlines and exchange disclosures for review. No AI sentiment, materiality judgement or ranking adjustment is applied.</p>'
    content += cards([("Matching items",f'{result["total"]:,}',"Last 30 days at this view’s cutoff"),
                      ("Collection", "Partial coverage", "Three public feeds"),
                      ("Score effect", "None", "Price/financial rules are unchanged")])
    content += '<form class="filters news-filters" method="get" action="/news"><label class="filter-search">Search headlines or symbol<input name="q" maxlength="200" value="'+esc(query.get("q",""))+'"></label>'
    content += '<label>Exact symbol<input name="symbol" maxlength="50" value="'+esc(query.get("symbol",""))+'"></label>'
    for key,label,options in (
        ("kind","Type",(("","All types"),("news","Publisher news"),("announcement","Announcements"),("board_meeting","Board meetings"))),
        ("source","Source",(("","All sources"),*((f["id"],f["name"]) for f in FEEDS))),
        ("match","Company match",(("","All items"),("matched","Matched"),("unmatched","Unassigned"),("conflict","Identity conflict"))),
    ):
        content += '<label>'+label+'<select name="'+key+'">'+''.join('<option value="'+esc(value)+'"'+(' selected' if query.get(key,"") == value else '')+'>'+esc(text)+'</option>' for value,text in options)+'</select></label>'
    if pinned:
        content += '<input type="hidden" name="report" value="'+esc(report["report_id"])+'">'
    content += '<button type="submit">Filter</button></form>'
    args = {k:v for k,v in query.items() if k in ("q","symbol","kind","source","match","report","offset")}
    content += '<div class="actions"><a href="'+link("/api/news",**args)+'">JSON</a><a href="'+link("/news.csv",**args)+'">CSV (this page)</a></div>'
    content += event_cards(result,report=report)
    content += '<div class="pagination">'
    if result["offset"]:
        content += '<a href="'+link("/news",**{**args,"offset":max(0,result["offset"]-30)})+'">← Previous</a>'
    content += '<span>'+str(result["offset"]+1 if result["total"] else 0)+'–'+str(result["offset"]+len(result["items"]))+' of '+str(result["total"])+'</span>'
    if result["next_offset"] is not None:
        content += '<a href="'+link("/news",**{**args,"offset":result["next_offset"]})+'">Next →</a>'
    content += '</div>' + source_health(status)
    content += '<details><summary>Refresh and coverage limits</summary><p>Run research.cmd for the daily workflow, or refresh just these feeds from the project folder:</p><pre>.\\run.cmd news-refresh</pre><p>Successful feeds are reused for two hours; failed requests cool down. HTTP 401, 403 and 429 wait at least 24 hours. No login, paid API or cookie workaround is used.</p><p>NSE announcements request the preceding seven calendar dates; the board and publisher RSS feeds are rolling windows. Offline periods can leave permanent gaps. Data is saved for personal local research; publisher articles and filing PDFs are linked, not scraped. The source export excludes collected feed data.</p></details>'
    return document("News & announcements",content,active="news",subtitle="Original sources, company matches and a visible collection history.")


def news_csv(result):
    out = StringIO(newline="")
    writer = csv.writer(out)
    fields = ("event_id","source_name","kind","category","title","published_at","first_seen_at","received_at","url","symbols","match_state","revision_checksum")
    writer.writerow(fields)
    for item in result["items"]:
        row = {**item,"symbols":", ".join(m["symbol"] for m in item["matches"])}
        # Spreadsheet formula injection protection for all untrusted text cells.
        writer.writerow(("'"+str(row.get(k,"")) if str(row.get(k,"")).lstrip().startswith(("=","+","-","@")) else row.get(k,"") or "") for k in fields)
    return out.getvalue()
