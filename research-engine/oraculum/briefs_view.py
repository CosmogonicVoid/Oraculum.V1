"""Read-only evidence notebooks and explicitly labelled AI-selected briefs."""

from .research_briefs import select_assets
from .ui import badge, cards, document, empty_state, esc, link, source_link, time_text


def ai_health(status):
    config, last = status.get("config") or {}, status.get("last_batch") or {}
    body = '<section class="panel"><h2>Local AI</h2>' + cards(
        [
            (
                "Setup",
                status.get("state", "unavailable").replace("_", " "),
                config.get("model", "Evidence notebooks work without a model"),
            ),
            (
                "Last batch",
                last.get("state", "Not run").replace("_", " "),
                time_text(last.get("finished_at")),
            ),
            (
                "Daily limit",
                str(config.get("limit", 3)) + " stocks",
                "Runs after research and virtual paper records are saved",
            ),
        ]
    )
    if status.get("error") or last.get("error"):
        body += (
            '<div class="notice">'
            + esc(status.get("error") or last["error"])
            + "</div>"
        )
    evaluation = status.get("evaluation")
    if evaluation:
        body += (
            f'<p>Development checks: {esc(evaluation.get("passed"))}/{esc(evaluation.get("total"))} passed. '
            + (
                "Current model/instructions."
                if status.get("evaluation_current")
                else "Earlier model/instructions; rerun checks."
            )
            + " This does not measure investment accuracy.</p>"
        )
    body += "<p>The model selects facts and interprets captured event tone. Application code assembles the text. Selection and tone still require review; neither changes scores or virtual trades.</p>"
    body += '<details><summary>Setup and commands</summary><p>Install and start <a href="https://ollama.com/download/windows" rel="noreferrer">Ollama</a>, then run these from the project folder:</p><pre>.\\ai-setup.cmd\n.\\run.cmd ai-refresh\n.\\start.cmd</pre><p>The one-time setup downloads local weights and runs three fictional checks. Existing local model? Use ai-configure --model YOUR_EXACT_MODEL_NAME and ai-evaluate instead of downloading another model. Run ai-evaluate --extended for eight development cases. Opening a page never starts generation.</p><pre>.\\run.cmd ai-doctor\n.\\run.cmd ai-status --audit\n.\\run.cmd ai-disable</pre>'
    if config:
        body += f'<p>Per-stock timeout: {esc(config["timeout"])} seconds. Batch budget: {esc(config["budget"])} seconds.</p><p class="hash">Pinned model: {esc(config["model_digest"])}</p>'
    return body + '</details><a href="/api/ai-status">Status JSON</a></section>'


def overview(report, status, summaries, *, query="", error=None):
    if not report:
        return document(
            "Research briefs",
            empty_state(
                "No saved report",
                "Run research.cmd to collect evidence; AI setup is optional.",
            )
            + ai_health(status),
            active="briefs",
        )
    ident = report["report_id"]
    body = f'<p>Evidence cutoff: {esc(time_text(report["as_of"]))}. Search any stock captured in this report.</p>'
    from .ui import research_tabs
    body = research_tabs("briefs", ident) + body
    body += f'<form class="panel" method="get" action="/research"><input type="hidden" name="report" value="{esc(ident)}"><label for="brief-search">Company or exchange symbol</label><div class="actions"><input id="brief-search" name="q" maxlength="80" value="{esc(query)}"><button type="submit">Find evidence</button></div></form>'
    if query:
        chosen = [
            a
            for a in report["assets"]
            if query.casefold()
            in (a["symbol"] + " " + (a.get("company_name") or "")).casefold()
        ][:40]
        body += '<p class="muted">Up to 40 matches; refine the search if needed.</p>'
    else:
        selected = {a["symbol"] for a in select_assets(report, 10)} | set(summaries)
        chosen = [
            a
            for a in select_assets(report, len(report["assets"]))
            if a["symbol"] in selected
        ]
        body += '<p class="muted">Leading research stocks and saved briefs. AI runs cover a bounded subset, not the whole market.</p>'
    if error:
        body += '<div class="notice">' + esc(error) + "</div>"
    rows = []
    for asset in chosen:
        item = summaries.get(asset["symbol"])
        label = (
            "AI-selected draft · review"
            if item and item["state"] == "accepted"
            else "Evidence only"
        )
        rows.append(
            f'<tr><td><a class="stock" href="{link("/brief", report=ident, symbol=asset["symbol"])}">{esc(asset["symbol"])}</a><div class="company">{esc(asset.get("company_name") or "")}</div></td><td>{badge(label)}</td><td>{esc(time_text(item.get("generated_at"))) if item else "—"}</td></tr>'
        )
    body += (
        '<div class="scroll" role="region" aria-label="Research briefs" tabindex="0"><table><thead><tr><th>Stock</th><th>Research available</th><th>Generated at</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
        if rows
        else empty_state(
            "No matching stock", "Try its exchange symbol or part of the company name."
        )
    )
    return document(
        "Research briefs",
        body + '<details><summary>Local AI status &amp; setup</summary>' + ai_health(status) + "</details>",
        active="briefs",
        subtitle="Saved facts, model-selected comparisons and captured event tone.",
    )


def citations(values, *, show_quotes=False):
    return (
        '<ul class="compact-list">'
        + "".join(
            f'<li><a href="#{esc(c["id"])}">{esc(c["id"])}</a>'
            + (" <small>“" + esc(c["quote"]) + "”</small>" if show_quotes else "")
            + "</li>"
            for c in values
        )
        + "</ul>"
    )


def detail(bundle):
    packet, attempt = bundle["packet"], bundle.get("attempt")
    ident, symbol = packet["report_id"], packet["symbol"]
    body = f'<div class="research-document"><p><a href="{link("/briefs", report=ident)}">← Briefs</a> · <a href="{link("/stock", report=ident, symbol=symbol)}">Stock metrics</a></p>'
    body += '<div class="document-masthead"><span>Oraculum / Evidence notebook</span><span>Saved research</span></div>'
    body += f'<div class="freshness"><span>Evidence cutoff <strong>{esc(time_text(packet["report_as_of"]))}</strong></span><span>Price session <strong>{esc(packet["price_session"])}</strong></span></div>'
    facts = {f["id"]: f for f in packet["facts"]}
    body += (
        '<section class="notice"><strong>Required context</strong><ul>'
        + "".join(
            "<li>" + esc(facts[key]["text"]) + "</li>"
            for key in packet["required_cautions"]
        )
        + "</ul></section>"
    )
    if attempt and attempt["state"] == "accepted":
        brief = attempt["brief"]
        body += '<section class="panel"><h2>AI-selected evidence · review required</h2>'
        body += f'<p>Selected {esc(time_text(attempt["generated_at"]))} using {esc(attempt["model"]["name"])}.</p><p class="muted">The app copies source facts and uses fixed comparison/question templates. This is not a freely written analyst report. The model’s selection and tone can still be wrong or omit important evidence.</p>'
        if not bundle["current_configuration"]:
            body += '<div class="notice">Saved under an earlier or unconfigured model/instruction version.</div>'
        if brief["abstain"]:
            body += badge("Insufficient evidence · abstained", "warn")
        for key, title in (
            ("summary", "Selected overview"),
            ("supports", "Supporting observations"),
            ("risks", "Concerns and limitations"),
            ("tensions", "Observations to compare"),
            ("questions", "Information to resolve"),
        ):
            if brief[key]:
                body += "<h3>" + title + "</h3>"
                for claim in brief[key]:
                    body += (
                        "<p>"
                        + esc(claim["text"])
                        + "</p>"
                        + citations(
                            claim["citations"],
                            show_quotes=key in ("tensions", "questions"),
                        )
                    )
        body += (
            "<h3>Captured event tone</h3>"
            + badge(brief["event_tone"]["label"])
            + '<p class="muted">AI interpretation of selected headlines/excerpts only; not overall sentiment or a return forecast.</p>'
            + citations(brief["event_tone"]["citations"], show_quotes=True)
            + "</section>"
        )
    else:
        body += empty_state(
            "Evidence notebook",
            bundle.get("error")
            or (attempt.get("error") if attempt else None)
            or "No accepted AI selection is saved for this report and stock. Captured evidence is available below.",
        )
        command = f".\\run.cmd ai-refresh --symbol {symbol} --report {ident}" + (
            " --retry" if attempt else ""
        )
        body += (
            "<details><summary>Generate a local brief</summary><p>After ai-setup.cmd succeeds, run this from your project folder:</p><pre>"
            + esc(command)
            + "</pre><p>Rejected output is retained in the audit record, not shown as an accepted brief.</p></details>"
        )
    body += '<section class="panel"><h2>Complete evidence notebook</h2><p class="muted">All captured facts and cautions, including those the model did not select. Snippets above may be shortened; full captured text is here.</p>'
    for fact in packet["facts"]:
        body += f'<article id="{esc(fact["id"])}"><h3>{esc(fact["id"])} · {esc(fact["kind"])}</h3><p>{esc(fact["text"])}</p><p class="hash">Sources: {esc(", ".join(fact["source_ids"])) or "Report context"}</p></article>'
    body += "</section><details><summary>Source receipts and provenance</summary><ul>"
    for source in packet["sources"]:
        body += (
            "<li>"
            + source_link(
                source.get("uri", ""), source.get("kind") or source["source_id"]
            )
            + " · received "
            + esc(time_text(source.get("received_at")))
            + '<div class="hash">'
            + esc(source["source_id"] + " · SHA-256 " + source["sha256"])
            + "</div></li>"
        )
    body += f'</ul><p class="hash">Report: {esc(ident)}<br>Packet: {esc(packet["packet_id"])}</p>'
    if attempt:
        body += (
            '<p class="hash">Model digest: '
            + esc(attempt["model"]["digest"])
            + "<br>Attempt: "
            + esc(attempt["attempt_id"])
            + "</p>"
        )
    body += f'</details><div class="actions"><a class="button secondary" href="{link("/brief.md", report=ident, symbol=symbol)}">Export Markdown</a><a href="{link("/api/brief", report=ident, symbol=symbol)}">Full audit JSON</a></div>'
    return document(
        symbol + " · research brief",
        body + "</div>",
        active="briefs",
        subtitle=packet.get("company_name") or "Captured stock evidence",
    )


def markdown(bundle):
    def safe(value):
        value = esc(value)
        for character in ("\\", "`", "*", "_", "[", "]", "#"):
            value = value.replace(character, "\\" + character)
        return value

    packet, attempt = bundle["packet"], bundle.get("attempt")
    lines = [
        "# " + safe(packet["symbol"]) + " · research brief",
        "",
        "Evidence cutoff: " + safe(packet["report_as_of"]),
        "",
        "AI selects evidence and tone. Application code assembles source snippets and fixed templates. Review selection and tone; no return forecast is implied.",
        "",
        "## Required context",
        "",
    ]
    facts = {f["id"]: f for f in packet["facts"]}
    lines += ["- " + safe(facts[key]["text"]) for key in packet["required_cautions"]]
    if attempt and attempt["state"] == "accepted":
        lines += [
            "",
            "## AI-selected draft",
            "",
            "Generated: " + safe(attempt["generated_at"]),
            "Model: " + safe(attempt["model"]["name"]),
            "Model digest: " + attempt["model"]["digest"],
            "Abstained: " + str(attempt["brief"]["abstain"]),
        ]
        for key in ("summary", "supports", "risks", "tensions", "questions"):
            if attempt["brief"][key]:
                lines += ["", "### " + key.title(), ""]
                for claim in attempt["brief"][key]:
                    lines += ["- " + safe(claim["text"])] + [
                        "  - " + safe(c["id"] + ": " + c["quote"])
                        for c in claim["citations"]
                    ]
        lines += [
            "",
            "Captured event tone: " + safe(attempt["brief"]["event_tone"]["label"]),
        ]
        lines += [
            "- " + safe(c["id"] + ": " + c["quote"])
            for c in attempt["brief"]["event_tone"]["citations"]
        ]
    else:
        lines += ["", "No accepted AI selection; evidence only."]
    lines += ["", "## Complete captured evidence", ""]
    for fact in packet["facts"]:
        lines += [
            "### " + fact["id"],
            "",
            safe(fact["text"]),
            "",
            "Sources: " + safe(", ".join(fact["source_ids"])),
        ]
    lines += ["", "## Source receipts", ""]
    for source in packet["sources"]:
        lines += [
            "- "
            + safe(
                source["source_id"]
                + " | "
                + str(source.get("uri") or "")
                + " | received "
                + source["received_at"]
                + " | SHA-256 "
                + source["sha256"]
            )
        ]
    return "\n".join(
        lines
        + ["", "Report: " + packet["report_id"], "Packet: " + packet["packet_id"], ""]
    )
