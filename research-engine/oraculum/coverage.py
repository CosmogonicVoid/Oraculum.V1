"""Read-only coverage diagnostics derived from immutable report snapshots."""

from collections import Counter
from datetime import datetime
import csv
import io
import math

from .contracts import UTC, ValidationError, day, timestamp

METRICS = ("revenue_yoy", "net_margin", "borrowings_to_equity", "roce")
FILTERS = (
    "all",
    "incomplete",
    "complete",
    "technical",
    "unsupported_schema",
    "identity_review",
    "ambiguous_filing",
    "no_filing",
    "older_financials",
)
PAGE_SIZE = 40


def metric_gap(metric, cutoff, sources):
    if not isinstance(metric, dict):
        return "Not available in this report"
    value = metric.get("value")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        return "Invalid or non-finite value"
    try:
        if timestamp(metric.get("available_at"), "availability") > cutoff:
            return "Available after report cutoff"
        refs = metric.get("source_ids")
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(ref, str) or ref not in sources for ref in refs)
        ):
            return "Missing source receipt"
        if any(
            timestamp(sources[ref].get("received_at"), "source receipt") > cutoff
            for ref in refs
        ):
            return "Source receipt after report cutoff"
        periods = metric.get("periods")
        if not isinstance(periods, list) or not periods:
            return "Accounting period not recorded"
        if any(day(p.get("end"), "period end") > cutoff.date() for p in periods):
            return "Accounting period after report cutoff"
    except (ValueError, TypeError, AttributeError):
        return "Invalid evidence dates"
    return None


def snapshot(report):
    """No network or cache reads. Ages are measured at this report's cutoff."""
    if report is None:
        return {
            "report_id": None,
            "rows": [],
            "counts": {},
            "metric_counts": {},
            "profile_statuses": {},
            "gap_counts": {},
            "collection": {},
            "event_coverage": {},
            "warnings": [],
        }
    cutoff = timestamp(report["as_of"], "cutoff")
    shared = {
        s["source_id"]: s
        for s in report.get("sources", []) + report.get("evidence_sources", [])
    }
    rows, gap_counts, statuses, metrics_count = [], Counter(), Counter(), Counter()
    for asset in report["assets"]:
        profile = asset.get("fundamentals") or {}
        sources = {**shared, **{s["source_id"]: s for s in profile.get("sources", [])}}
        gaps = {}
        for key in METRICS:
            gap = metric_gap(profile.get("metrics", {}).get(key), cutoff, sources)
            if gap:
                detail = profile.get("missing", {}).get(key)
                gaps[key] = gap + (": " + str(detail) if detail else "")
                gap_counts[key] += 1
            else:
                metrics_count[key] += 1
        age = None
        if profile.get("quarter_end"):
            try:
                age = (cutoff.date() - day(profile["quarter_end"], "quarter end")).days
                if age < 0:
                    age = None
            except (ValueError, TypeError):
                pass
        state = profile.get("status", "unavailable")
        statuses[state] += 1
        flags = ["incomplete" if gaps else "complete"]
        if asset.get("status") != "eligible":
            flags.append("technical")
        if state in FILTERS:
            flags.append(state)
        if age is not None and age > 180:
            flags.append("older_financials")
        rows.append(
            {
                "symbol": asset["symbol"],
                "company_name": asset.get("company_name", asset["symbol"]),
                "profile_status": state,
                "financial_inputs": 4 - len(gaps),
                "gaps": gaps,
                "quarter_end": profile.get("quarter_end"),
                "quarter_age_days": age,
                "technical_pass": asset.get("status") == "eligible",
                "combined_eligible": (asset.get("combined") or {}).get("score")
                is not None,
                "flags": sorted(set(flags)),
                "notes": profile.get("notes", []),
                "blockers": asset.get("blockers", []),
            }
        )
    rows.sort(
        key=lambda r: (r["financial_inputs"] == 4, not r["technical_pass"], r["symbol"])
    )
    counts = {
        "scanned": len(rows),
        "complete": sum(r["financial_inputs"] == 4 for r in rows),
        "technical_passes": sum(r["technical_pass"] for r in rows),
        "combined_eligible": sum(r["combined_eligible"] for r in rows),
        "older_financials": sum("older_financials" in r["flags"] for r in rows),
    }
    counts["incomplete"] = len(rows) - counts["complete"]
    return {
        "report_id": report["report_id"],
        "as_of": report["as_of"],
        "last_session": report["last_session"],
        "rows": rows,
        "counts": counts,
        "metric_counts": {k: metrics_count[k] for k in METRICS},
        "gap_counts": dict(gap_counts),
        "profile_statuses": dict(statuses),
        "collection": report.get("fundamental_coverage", {}),
        "event_coverage": report.get("event_coverage", {}),
        "warnings": report.get("refresh_warnings", []),
        "definitions": "Coverage requires finite values, known dated source receipts and accounting periods by cutoff. It does not certify source truth. Older-financials flags quarters over 180 days old at cutoff for review only; ranking rules are unchanged.",
    }


def select(data, *, query="", category="all", offset=0, limit=PAGE_SIZE):
    if category not in FILTERS:
        raise ValidationError("Unknown coverage filter")
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 10000
    ):
        raise ValidationError("Invalid coverage pagination")
    if not isinstance(query, str) or len(query) > 80:
        raise ValidationError("Coverage search is limited to 80 characters")
    rows = [
        r
        for r in data["rows"]
        if (category == "all" or category in r["flags"])
        and query.casefold() in (r["symbol"] + " " + r["company_name"]).casefold()
    ]
    return {
        **{k: v for k, v in data.items() if k != "rows"},
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "query": query,
        "filter": category,
    }


def csv_export(result):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(
        [
            "report_id",
            "cutoff",
            "symbol",
            "company",
            "financial_inputs",
            "profile_status",
            "quarter_end",
            "quarter_age_days",
            "technical_pass",
            "combined_eligible",
            "missing_inputs",
            "reasons",
        ]
    )

    def cell(value):
        text = str(value) if value is not None else ""
        return (
            "'" + text
            if text.lstrip().startswith(("=", "+", "-", "@"))
            or text.startswith(("\t", "\r", "\n"))
            else text
        )

    for r in result["items"]:
        writer.writerow(
            map(
                cell,
                [
                    result["report_id"],
                    result["as_of"],
                    r["symbol"],
                    r["company_name"],
                    r["financial_inputs"],
                    r["profile_status"],
                    r["quarter_end"],
                    r["quarter_age_days"],
                    r["technical_pass"],
                    r["combined_eligible"],
                    "; ".join(r["gaps"]),
                    "; ".join(r["gaps"].values()),
                ],
            )
        )
    return out.getvalue()


def freshness(report, *, now=None):
    """Current operational freshness, kept separate from frozen report coverage."""
    now = now or datetime.now(UTC)
    if report is None:
        return {"state": "no_report", "message": "Run research.cmd to create a report."}
    try:
        from .contracts import IST

        schedule = report["calendar"]["schedule"]
        today = now.astimezone(IST).date()
        end = day(schedule["coverage_end"], "calendar end")
        if not day(schedule["coverage_start"], "calendar start") <= today <= end:
            return {
                "state": "calendar_review",
                "message": "Outside the saved calendar's coverage. Current market freshness is unknown.",
                "coverage_end": str(end),
            }
        closed = [
            s["session"]
            for s in schedule["sessions"]
            if timestamp(s["close_at"], "session close") <= now
        ]
        expected = max(closed) if closed else None
        lag = sum(s > report["last_session"] for s in closed)
        return {
            "state": "behind" if lag else "current",
            "expected_session": expected,
            "missing_sessions": lag,
            "calendar_days_remaining": (end - today).days,
            "coverage_end": str(end),
            "message": f"{lag} completed sessions newer than this report, according to its saved calendar.",
        }
    except (ValueError, TypeError, KeyError):
        return {
            "state": "unknown",
            "message": "Saved calendar metadata is unavailable or invalid.",
        }
