"""Deterministic report-pinned evidence packets; no downloads or model calls."""

import math
from pathlib import Path
from .contracts import ValidationError, timestamp
from .serialization import digest

FINANCIAL = {
    "revenue_yoy": "Same-quarter revenue growth year on year",
    "net_margin": "Quarter net profit margin",
    "borrowings_to_equity": "Borrowings / equity (excludes leases)",
    "roce": "Annual return on capital employed",
}
TECHNICAL = {
    "close_inr": ("Latest raw close, INR", "money"),
    "momentum_20d": ("Adjusted price change over 20 sessions", "percent"),
    "trend_50d": ("Adjusted close versus 50-session mean", "percent"),
    "volume_ratio_20d": ("Adjusted volume / prior 20-session mean", "ratio"),
    "volatility_20d_annualized": (
        "Annualized historical volatility, 20 sessions",
        "percent",
    ),
    "drawdown_50d": ("Worst peak-to-trough drawdown over 50 sessions", "percent"),
}


def finite(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def compact(text, limit=600):
    return " ".join(str(text or "").split())[:limit]


def verify_report(report):
    if not isinstance(report, dict) or report.get("report_id") != digest(
        {k: v for k, v in report.items() if k != "report_id"}
    ):
        raise ValidationError("AI requires an intact saved research report")
    timestamp(report["as_of"], "report cutoff")


def build_packet(folder, report, symbol, *, events_reader=None):
    verify_report(report)
    asset = next((a for a in report["assets"] if a["symbol"] == symbol), None)
    if asset is None:
        raise ValidationError("Stock is absent from this report")
    cutoff = timestamp(report["as_of"], "report cutoff")
    facts, sources, cautions = [], {}, []
    for source in (
        *report.get("sources", []),
        *report.get("evidence_sources", []),
        *asset.get("fundamentals", {}).get("sources", []),
    ):
        try:
            if (
                timestamp(source["received_at"], "receipt") <= cutoff
                and source.get("source_id")
                and source.get("sha256")
            ):
                sources[source["source_id"]] = dict(source)
        except (ValueError, KeyError, TypeError):
            pass

    def add(kind, role, text, refs=(), **details):
        ident = f"E{len(facts)+1:02d}"
        facts.append(
            {
                "id": ident,
                "kind": kind,
                "role": role,
                "text": compact(text),
                "source_ids": list(dict.fromkeys(refs)),
                **details,
            }
        )
        if role == "limitation":
            cautions.append(ident)

    combined = asset.get("combined", {})
    if finite(combined.get("score")) and combined.get("rank") is not None:
        add(
            "ranking",
            "context",
            f'Saved combined rank {combined["rank"]}; score {combined["score"]:.2f}/100. A rank within available coverage, not a probability, expected return or buy instruction.',
        )
    else:
        add(
            "ranking",
            "limitation",
            "No complete combined score is available; this stock is not a fully evaluated combined candidate.",
        )
    inputs = [
        *report.get("sources", []),
        *[
            s
            for s in report.get("evidence_sources", [])
            if s.get("kind") in ("actions", "renames")
        ],
    ]
    refs = [s.get("source_id") for s in inputs]
    if not report.get("sources") or any(s not in sources for s in refs):
        refs = []
    technical = 0
    for key, (label, form) in TECHNICAL.items():
        value = asset.get("metrics", {}).get(key)
        if not finite(value) or not refs:
            continue
        display = (
            f"{value*100:+.2f}%"
            if form == "percent"
            else f"{value:.2f}" + ("x" if form == "ratio" else "")
        )
        role = (
            ("support" if value > 0 else "caution")
            if key in ("momentum_20d", "trend_50d")
            else (
                "caution"
                if key in ("drawdown_50d", "volatility_20d_annualized")
                else "context"
            )
        )
        add(
            "technical",
            role,
            f'{label}: {display}. Price session: {report["last_session"]}.',
            refs,
        )
        technical += 1
    if not technical:
        add(
            "coverage",
            "limitation",
            "No usable sourced technical metrics are available in this report.",
        )
    fundamental = asset.get("fundamentals", {})
    financial = 0
    for key, label in FINANCIAL.items():
        metric = fundamental.get("metrics", {}).get(key)
        valid = (
            isinstance(metric, dict)
            and finite(metric.get("value"))
            and bool(metric.get("source_ids"))
        )
        if valid:
            try:
                valid = timestamp(
                    metric["available_at"], "financial availability"
                ) <= cutoff and all(s in sources for s in metric["source_ids"])
                valid = valid and all(
                    str(p.get("end", "9999-12-31")) <= cutoff.date().isoformat()
                    for p in metric.get("periods", [])
                )
            except (ValueError, KeyError, TypeError):
                valid = False
        if not valid:
            add(
                "coverage",
                "limitation",
                f"{label} is missing, not timely, or lacks complete source references. Do not estimate it.",
            )
            continue
        value = metric["value"]
        display = (
            f"{value:.2f}x" if key == "borrowings_to_equity" else f"{value*100:.2f}%"
        )
        periods = ", ".join(
            f'{p.get("start") or "as at"} to {p.get("end")}'
            for p in metric.get("periods", [])
        )
        role = (
            "caution"
            if value < 0
            else (
                "support" if key in ("revenue_yoy", "roce") and value > 0 else "context"
            )
        )
        add(
            "financial",
            role,
            f'{label}: {display}. Basis: {fundamental.get("basis") or "unspecified"}. Periods: {periods or "not provided"}. Formula: {metric.get("formula") or "see report"}.',
            metric["source_ids"],
            available_at=metric["available_at"],
        )
        financial += 1
    warnings = list(
        dict.fromkeys(
            [
                *asset.get("warnings", []),
                *asset.get("blockers", []),
                *combined.get("blockers", []),
                *combined.get("candidate_blockers", []),
                *fundamental.get("notes", []),
            ]
        )
    )
    for warning in warnings[:5]:
        add("screen", "limitation", warning)
    if len(warnings) > 5:
        add(
            "coverage",
            "limitation",
            "Additional screen warnings are in the complete stock report.",
        )
    add(
        "coverage",
        "limitation",
        "Financial coverage is incomplete across the market. A high rank within the supported universe does not mean best stock in the whole market.",
    )
    if events_reader is None:
        from .market_events import report_events

        events_reader = report_events
    count, omitted, notices = 0, 0, []
    for kind, cap in (("announcement", 3), ("news", 3), ("board_meeting", 1)):
        result = events_reader(
            Path(folder),
            report,
            symbol=symbol,
            isin=asset.get("isin") or "",
            kind=kind,
            limit=cap,
        )
        if result.get("notice"):
            notices.append(str(result["notice"]))
        omitted += max(0, result.get("total", 0) - cap)
        for event in result.get("items", [])[:cap]:
            matches = [
                m
                for m in event.get("matches", [])
                if m.get("symbol") == symbol and m.get("isin") == asset.get("isin")
            ]
            if event.get("match_state") != "matched" or not matches:
                continue
            try:
                if (
                    timestamp(event["received_at"], "event receipt") > cutoff
                    or not event.get("published_at")
                    or timestamp(event["published_at"], "publication") > cutoff
                    or timestamp(event["receipt"]["received_at"], "feed receipt")
                    > cutoff
                ):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            sid = "event-" + str(event["revision_id"])
            sources[sid] = {
                "source_id": sid,
                "kind": kind,
                "uri": event.get("url"),
                "received_at": event["received_at"],
                "sha256": event["revision_checksum"],
                "receipt": event["receipt"],
                "published_at": event["published_at"],
                "match_methods": [m.get("method") for m in matches],
            }
            title = compact(event.get("title"), 180)
            text = (
                title
                + ". "
                + compact(event.get("excerpt"), 200)
                + f' Source: {event.get("source_name") or kind}; published {event["published_at"]}. Headline/excerpt only; full article/attachment not analyzed.'
            )
            if kind == "news":
                text += " Tentative company mention; not independently verified."
            add(
                "event",
                "context",
                text,
                [sid],
                tentative=kind == "news",
                citation_text=title,
            )
            count += 1
    add(
        "coverage",
        "limitation",
        (
            "No eligible dated company events were captured. This is missing coverage, not neutral sentiment or proof that no event occurred."
            if not count
            else "Event analysis covers selected headlines/excerpts, not full articles or attachments. Publisher company matches are tentative; verify original sources."
        ),
    )
    if omitted:
        add(
            "coverage",
            "limitation",
            "Additional matched events were omitted from this compact packet; inspect this report in News.",
        )
    if notices:
        add(
            "coverage",
            "limitation",
            "Event snapshot unavailable or incomplete: "
            + "; ".join(dict.fromkeys(notices)),
        )
    used = {s for f in facts for s in f["source_ids"]}
    packet = {
        "schema": "research-evidence-v1",
        "report_id": report["report_id"],
        "report_as_of": report["as_of"],
        "price_session": report["last_session"],
        "symbol": symbol,
        "company_name": asset.get("company_name", symbol),
        "isin": asset.get("isin"),
        "facts": facts,
        "sources": [sources[s] for s in sorted(used)],
        "required_cautions": cautions,
        "coverage": {
            "technical_metrics": technical,
            "financial_metrics": financial,
            "events": count,
        },
        "must_abstain": not technical and not financial and not count,
    }
    packet["packet_id"] = digest(packet)
    return packet


def prompt_packet(packet):
    return {
        k: packet[k] for k in ("symbol", "company_name", "report_as_of", "must_abstain")
    } | {
        "evidence": [
            {k: f[k] for k in ("id", "kind", "role", "text")} for f in packet["facts"]
        ]
    }
