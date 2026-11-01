"""Conservative NSE IndAS XBRL extraction and sourced, period-matched ratios.

Numeric XBRL facts are already in their declared units. 'decimals' describes
rounding precision; it is never a multiplier. No external schema is fetched.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import io
import re
import statistics
import xml.etree.ElementTree as ET

from .contracts import IST, ValidationError, day, iso, timestamp
from .nse_evidence import MAX_BYTES, csv_rows, evidence_reference

X = "{http://www.xbrl.org/2003/instance}"
NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
INR = "{http://www.xbrl.org/2003/iso4217}INR"
SHARES = X + "shares"
MONEY = {"RevenueFromOperations", "ProfitLossForPeriod", "ProfitOrLossAttributableToOwnersOfParent",
         "ProfitBeforeTax", "FinanceCosts", "BorrowingsCurrent", "BorrowingsNoncurrent", "Equity",
         "EquityAttributableToOwnersOfParent", "Assets", "CurrentLiabilities"}
EPS = "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"
IDENTITY = {"Symbol", "ISIN", "NatureOfReportStandaloneConsolidated", "DateOfStartOfFinancialYear",
            "DateOfEndOfFinancialYear", "DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod"}
METRICS = ("revenue_yoy", "net_margin", "borrowings_to_equity", "roce", "annual_pe", "peer_pe_ratio")
INDUSTRY_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"


def supported(record):
    # NBFC_INDAS, banking and insurance schemas are deliberately separate.
    return "/INTEGRATED_FILING_INDAS_" in record["url"].upper()


def filing_key(record):
    # The exchange may reuse a URL for a revision; publication is part of identity.
    return record["url"] + "|" + iso(timestamp(record["published_at"], "publication"))


def parse_xbrl(raw):
    if not raw or len(raw) > MAX_BYTES or re.search(br"<!\s*(DOCTYPE|ENTITY)\b", raw, re.I) or b"\x00" in raw:
        raise ValidationError("Unsafe/oversized XBRL or unsupported XML encoding")
    try:
        namespaces = {}
        for _, pair in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
            prefix, uri = pair
            if prefix in namespaces and namespaces[prefix] != uri:
                raise ValidationError("Rebound namespace prefix in XBRL")
            namespaces[prefix] = uri
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValidationError("Invalid XBRL XML; no financial facts imported") from exc
    if root.tag != X + "xbrl" or sum(1 for _ in root.iter()) > 100_000:
        raise ValidationError("Not a bounded XBRL instance")

    def qname(text):
        parts = (text or "").strip().split(":")
        prefix, name = (parts if len(parts) == 2 else ("", parts[0]))
        return "{" + namespaces.get(prefix, "UNKNOWN") + "}" + name

    contexts, units = {}, {}
    for ctx in root.findall(X + "context"):
        key = ctx.get("id")
        if not key or key in contexts:
            raise ValidationError("Duplicate/missing XBRL context ID")
        # Even unknown scenario/segment contents disqualify a context from totals.
        dimensional = ctx.find(X + "scenario") is not None or ctx.find(X + "entity/" + X + "segment") is not None
        period = ctx.find(X + "period")
        if period is None:
            raise ValidationError("Missing XBRL period")
        instant = period.findtext(X + "instant")
        start, end = period.findtext(X + "startDate"), period.findtext(X + "endDate")
        if instant:
            start, end, kind = None, str(day(instant.strip(), "instant")), "instant"
        else:
            start, end, kind = str(day((start or "").strip(), "start")), str(day((end or "").strip(), "end")), "duration"
            if start > end:
                raise ValidationError("Reversed XBRL period")
        contexts[key] = {"start": start, "end": end, "kind": kind, "dimensional": dimensional}
    for unit in root.findall(X + "unit"):
        key = unit.get("id")
        if not key or key in units:
            raise ValidationError("Duplicate/missing XBRL unit ID")
        measures = unit.findall(X + "measure")
        if len(measures) == 1 and qname(measures[0].text) == INR:
            units[key] = "INR"
        else:
            num = unit.findall(X + "divide/" + X + "unitNumerator/" + X + "measure")
            den = unit.findall(X + "divide/" + X + "unitDenominator/" + X + "measure")
            units[key] = "INR/share" if len(num) == len(den) == 1 and qname(num[0].text) == INR and qname(den[0].text) == SHARES else "unsupported"
    periods, identities = {}, defaultdict(set)
    for fact in root:
        if not re.fullmatch(r"\{https?://www\.sebi\.gov\.in/xbrl/[^{}]+/in-capmkt\}[^{}]+", fact.tag):
            continue
        tag = fact.tag.rsplit("}", 1)[-1]
        if tag not in MONEY | IDENTITY | {EPS}:
            continue
        ctx = contexts.get(fact.get("contextRef"))
        if ctx is None:
            raise ValidationError("Financial fact references unknown context")
        if ctx["dimensional"] or fact.get(NIL) in ("true", "1"):
            continue
        text = (fact.text or "").strip()
        if tag in IDENTITY:
            if text:
                identities[tag].add(text)
            continue
        if units.get(fact.get("unitRef")) != ("INR/share" if tag == EPS else "INR"):
            raise ValidationError(f"Unexpected unit for {tag}")
        if list(fact) or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
            raise ValidationError(f"Invalid numeric financial fact: {tag}")
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ValidationError("Invalid decimal financial fact") from exc
        if not value.is_finite() or abs(value) > Decimal("1e20") or len(text) > 100 or (value and value.adjusted() < -20):
            raise ValidationError("Financial fact outside supported range")
        # Inline-XBRL scaled facts are not part of this instance format.
        if fact.get("scale") is not None or fact.get("sign") is not None:
            raise ValidationError("Scaled inline-XBRL facts need a separate parser")
        key = (ctx["kind"], ctx["start"], ctx["end"])
        period = periods.setdefault(key, {k: ctx[k] for k in ("kind", "start", "end")} | {"facts": {}})
        previous = period["facts"].get(tag)
        if previous is not None and Decimal(previous) != value:
            raise ValidationError(f"Conflicting {tag} facts for one reporting period")
        period["facts"][tag] = str(value)
    reporting_starts = sorted(identities.pop("DateOfStartOfReportingPeriod", set()))
    if not reporting_starts:
        raise ValidationError("Missing reporting-period start")
    for value in reporting_starts:
        day(value, "reporting start")
    for tag in IDENTITY - {"DateOfStartOfReportingPeriod"}:
        if len(identities[tag]) != 1:
            raise ValidationError(f"Missing or inconsistent filing identity: {tag}")
    identity = {k: next(iter(v)) for k, v in identities.items()}
    if identity["NatureOfReportStandaloneConsolidated"].lower() not in ("standalone", "consolidated"):
        raise ValidationError("Unknown financial reporting basis")
    for tag in IDENTITY - {"Symbol", "ISIN", "NatureOfReportStandaloneConsolidated", "DateOfStartOfReportingPeriod"}:
        day(identity[tag], tag)
    if not periods:
        raise ValidationError("No supported financial totals in filing")
    return {"parser": "nse-indas-totals-v1", "identity": identity, "reporting_starts": reporting_starts,
            "periods": sorted(periods.values(), key=lambda p: (p["end"], p["start"] or ""))}


def validate_filing(data, record, expected_isin, *, allowed_symbols=()):
    identity = data["identity"]
    if identity["Symbol"] not in {record["symbol"], *allowed_symbols}:
        raise ValidationError("Filing symbol does not match exchange catalogue")
    if identity["ISIN"] != expected_isin:
        raise ValidationError("Filing ISIN differs from current security; manual identity review required")
    if identity["NatureOfReportStandaloneConsolidated"].lower() != record["basis"]:
        raise ValidationError("Filing reporting basis differs from catalogue")
    if identity["DateOfEndOfReportingPeriod"] != record["period_end"]:
        raise ValidationError("Filing reporting period differs from catalogue")


def parse_industries(raw):
    rows = csv_rows(raw, {"Symbol", "Industry", "ISIN Code"})
    result = {}
    for row in rows:
        symbol = row["Symbol"]
        if symbol in result:
            raise ValidationError("Duplicate symbol in industry mapping")
        result[symbol] = {"industry": row["Industry"], "isin": row["ISIN Code"]}
    return result


def filing_plan(catalogue, symbols, *, as_of):
    rows = [r for r in catalogue if r["symbol"] in symbols and timestamp(r["published_at"], "publication") <= as_of]
    if not rows:
        return {"status": "no_filing", "records": {}, "notes": ["No usable dated XBRL filing in catalogue"]}
    latest_end = max(r["period_end"] for r in rows)
    latest_rows = [r for r in rows if r["period_end"] == latest_end]
    basis = "consolidated" if any(r["basis"] == "consolidated" for r in latest_rows) else "standalone"
    selected = {}
    ambiguous = set()
    for r in rows:
        if r["basis"] != basis:
            continue
        old = selected.get(r["period_end"])
        if old is None or timestamp(r["published_at"], "publication") > timestamp(old["published_at"], "publication"):
            selected[r["period_end"]] = r
            ambiguous.discard(r["period_end"])
        elif timestamp(r["published_at"], "publication") == timestamp(old["published_at"], "publication") and r["url"] != old["url"]:
            ambiguous.add(r["period_end"])
    if latest_end in ambiguous:
        return {"status": "ambiguous_filing", "basis": basis, "period_end": latest_end, "records": {},
                "notes": ["Conflicting latest filings have the same publication time; automatic choice withheld"]}
    latest = selected[latest_end]
    if not supported(latest):
        return {"status": "unsupported_schema", "basis": basis, "records": {},
                "notes": ["Bank/NBFC/insurance or other XBRL schema is not supported by this industrial-ratio parser"]}
    end = day(latest_end, "period_end")
    prior = end.replace(year=end.year-1, day=min(end.day, 28) if end.month == 2 else end.day)
    annual = date(end.year if (end.month, end.day) >= (3, 31) else end.year-1, 3, 31)
    dates = {"quarter": end, "year_ago_quarter": prior, "annual": annual, "prior_annual": annual.replace(year=annual.year-1)}
    records = {role: selected[str(d)] for role, d in dates.items() if str(d) in selected and str(d) not in ambiguous and supported(selected[str(d)])}
    return {"status": "pending", "basis": basis, "period_end": latest_end, "records": records,
            "notes": ["Conflicting filing timestamps: " + ", ".join(sorted(ambiguous))] if ambiguous else []}


def empty_profile(plan):
    return {"status": plan["status"], "basis": plan.get("basis"), "quarter_end": plan.get("period_end"),
            "metrics": {m: None for m in METRICS}, "missing": {}, "notes": list(plan["notes"]),
            "sources": [], "industry": None, "financial_screen": "not_assessed"}


def profile_from_filings(plan, available, *, close, today, symbol, actions, action_start, aliases):
    """available maps role to validated evidence. Missing revised documents stay missing."""
    profile = empty_profile(plan)
    profile["sources"] = sorted({e["source_id"]: evidence_reference(e) for e in available.values()}.values(), key=lambda s: s["source_id"])

    def period(role, kind, end=None):
        e = available.get(role)
        if not e:
            return None
        end = end or plan["records"][role]["period_end"]
        candidates = []
        for p in e["data"]["periods"]:
            if p["end"] != end:
                continue
            length = (day(p["end"], "end") - day(p["start"], "start")).days + 1 if p["start"] else 0
            if (kind == "instant" and p["kind"] == "instant" or
                    kind == "quarter" and p["kind"] == "duration" and 75 <= length <= 105 or
                    kind == "annual" and p["kind"] == "duration" and 330 <= length <= 380):
                candidates.append(p)
        if len(candidates) != 1:
            return None
        return candidates[0]

    def value(p, tag):
        return Decimal(p["facts"][tag]) if p and tag in p["facts"] else None

    def add(name, result, periods, roles, formula):
        sources = [available[r] for r in set(roles) if r in available]
        stamps = [timestamp(s["received_at"], "receipt") for s in sources]
        stamps += [timestamp(plan["records"][r]["published_at"], "publication") for r in set(roles)]
        profile["metrics"][name] = {"value": float(result), "periods": [{k: p[k] for k in ("start", "end", "kind")} for p in periods],
                                     "formula": formula, "source_ids": sorted(s["source_id"] for s in sources),
                                     "available_at": iso(max(stamps))}

    q, py, annual = period("quarter", "quarter"), period("year_ago_quarter", "quarter"), period("annual", "annual")
    revenue, prior_revenue, profit = value(q, "RevenueFromOperations"), value(py, "RevenueFromOperations"), value(q, "ProfitLossForPeriod")
    fresh_q = q and 0 <= (today - day(q["end"], "end")).days <= 180
    if fresh_q and revenue is not None and prior_revenue is not None and prior_revenue > 0 and py and q["start"][5:] == py["start"][5:] and q["end"][5:] == py["end"][5:]:
        add("revenue_yoy", revenue / prior_revenue - 1, [q, py], ["quarter", "year_ago_quarter"], "Same-quarter revenue / prior-year revenue - 1; consistent reporting basis")
    if fresh_q and revenue is not None and revenue > 0 and profit is not None:
        add("net_margin", profit / revenue, [q], ["quarter"], "Quarter group profit/loss for period / revenue from operations")
    bs_role = "quarter" if period("quarter", "instant") else "annual"
    bs = period(bs_role, "instant")
    current, noncurrent, equity = value(bs, "BorrowingsCurrent"), value(bs, "BorrowingsNoncurrent"), value(bs, "Equity")
    if bs and 0 <= (today-day(bs["end"], "end")).days <= 240 and None not in (current, noncurrent, equity) and current >= 0 and noncurrent >= 0 and equity > 0:
        add("borrowings_to_equity", (current + noncurrent) / equity, [bs], [bs_role], "(Current + noncurrent borrowings) / total equity; excludes lease liabilities")
    fresh_annual = annual and 0 <= (today-day(annual["end"], "end")).days <= 450
    if fresh_annual:
        end_bs = period("annual", "instant")
        previous_end = str(day(annual["start"], "start") - timedelta(days=1))
        start_bs = period("annual", "instant", previous_end)
        start_role = "annual"
        if not start_bs or value(start_bs, "Assets") is None or value(start_bs, "CurrentLiabilities") is None:
            start_bs, start_role = period("prior_annual", "instant", previous_end), "prior_annual"
        pbt, finance = value(annual, "ProfitBeforeTax"), value(annual, "FinanceCosts")
        a0, l0, a1, l1 = value(start_bs, "Assets"), value(start_bs, "CurrentLiabilities"), value(end_bs, "Assets"), value(end_bs, "CurrentLiabilities")
        if None not in (pbt, finance, a0, l0, a1, l1) and min(a0-l0, a1-l1) > 0 and finance >= 0:
            add("roce", (pbt + finance) / ((a0-l0+a1-l1)/2), [annual, start_bs, end_bs], ["annual", start_role], "Annual (profit before tax + finance costs) / average opening and closing (assets - current liabilities)")
        eps = value(annual, EPS)
        share_events = [a for a in actions if a["symbol"] in aliases and annual["end"] < a["ex_date"] <= str(today) and a["kind"] not in ("meeting", "dividend")]
        if eps is not None and eps > 0 and action_start <= day(annual["end"], "end") and not share_events:
            add("annual_pe", Decimal(str(close)) / eps, [annual], ["annual"], "Latest raw close / positive basic EPS for latest supported full fiscal year; NOT trailing-twelve-month P/E")
        elif share_events:
            profile["notes"].append("Annual P/E withheld: a share action after fiscal year-end requires EPS comparability review")
    for name in METRICS:
        if profile["metrics"][name] is None:
            profile["missing"][name] = "Required consistent, fresh periods/units/positive denominator or sufficient peers are unavailable"
    if available:
        profile["status"] = "available" if all(profile["metrics"][m] is not None for m in METRICS[:4]) else "partial"
    required = [profile["metrics"][m] for m in METRICS[:4]]
    if all(required):
        growth, margin, debt, roce = [m["value"] for m in required]
        profile["financial_screen"] = "passes" if growth > 0 and margin > 0 and 0 <= debt <= 1.5 and roce >= .10 else "does_not_pass"
    return profile


def attach_peer_comparisons(assets):
    groups = defaultdict(list)
    for asset in assets:
        p = asset["fundamentals"]
        pe = p["metrics"]["annual_pe"]
        if p["industry"] and pe:
            groups[(p["industry"], p["basis"], pe["periods"][0]["end"])].append(asset)
    for group in groups.values():
        for asset in group:
            peers = [a for a in group if a["symbol"] != asset["symbol"]]
            if len(peers) < 5:
                continue
            median = statistics.median(a["fundamentals"]["metrics"]["annual_pe"]["value"] for a in peers)
            own = asset["fundamentals"]["metrics"]["annual_pe"]
            all_metrics = [own] + [a["fundamentals"]["metrics"]["annual_pe"] for a in peers]
            asset["fundamentals"]["metrics"]["peer_pe_ratio"] = {"value": own["value"]/median, "peer_median": median,
                "peer_symbols": sorted(a["symbol"] for a in peers), "peer_count": len(peers),
                "periods": own["periods"], "source_ids": sorted({s for m in all_metrics for s in m["source_ids"]}),
                "available_at": iso(max([timestamp(m["available_at"], "availability") for m in all_metrics] +
                    [timestamp(a["fundamentals"]["industry_available_at"], "industry availability") for a in group if "industry_available_at" in a["fundamentals"]])),
                "formula": "Annual P/E / median of other cached, positive-P/E stocks with same industry, basis and fiscal-year-end; incomplete peer sample"}
            asset["fundamentals"]["missing"].pop("peer_pe_ratio", None)
            extra = {a["fundamentals"]["industry_source_id"] for a in group if "industry_source_id" in a["fundamentals"]}
            metric = asset["fundamentals"]["metrics"]["peer_pe_ratio"]
            metric["source_ids"] = sorted(set(metric["source_ids"]) | extra)
