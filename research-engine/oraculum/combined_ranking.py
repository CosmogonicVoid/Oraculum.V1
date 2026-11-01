"""Versioned, fully disclosed technical + financial research baseline.

All four financial inputs are required. Missing values never receive a score
and available weights are never renormalized. This is not a trained forecast.
"""
from collections import Counter
import math

from .contracts import ValidationError, timestamp
from .serialization import digest

SCHEMA = "oraculum-integrated-research-v2"
ALGORITHM = "nse-combined-v1"
FINANCIAL_WEIGHTS = {"revenue_yoy": .10, "net_margin": .10,
                     "borrowings_to_equity": .10, "roce": .10}
POLICY = {
    "version": ALGORITHM, "technical_weight": .60,
    "financial_weights": FINANCIAL_WEIGHTS,
    "minimum_score": 60, "maximum_highlights": 10,
    "normalization": {
        "revenue_yoy": "100 * clip((growth + 0.10) / 0.40, 0, 1)",
        "net_margin": "100 * clip(margin / 0.20, 0, 1)",
        "borrowings_to_equity": "100 * clip(1 - borrowings/equity / 2, 0, 1)",
        "roce": "100 * clip(ROCE / 0.30, 0, 1)"},
    "requirements": "Technical filters, all four timely financial metrics; candidates additionally pass the financial screen, positive momentum and trend, and score >= 60.",
    "unscored_inputs": ["annual_pe", "peer_pe_ratio", "news", "nonfinancial_announcements"],
}


def normalized(name, value):
    mapped = {"revenue_yoy": lambda x: (x + .10) / .40,
              "net_margin": lambda x: x / .20,
              "borrowings_to_equity": lambda x: 1 - x / 2,
              "roce": lambda x: x / .30}[name](value)
    return 100 * min(1, max(0, mapped))


def combine_asset(asset, *, as_of):
    blockers, factors = [], []
    technical = asset.get("score")
    if asset.get("status") != "eligible" or technical is None:
        blockers.append("Technical data/liquidity/risk filters did not pass")
    elif not isinstance(technical, (int, float)) or not math.isfinite(technical) or not 0 <= technical <= 100:
        raise ValidationError("Invalid technical score for combined ranking")
    factors.append({"name": "technical", "weight": .60, "value": technical,
                    "normalized": technical, "points": .60 * technical if technical is not None else None,
                    "source_ids": [], "unavailable_reason": blockers[0] if blockers else None})
    metrics = asset.get("fundamentals", {}).get("metrics", {})
    for name, weight in FINANCIAL_WEIGHTS.items():
        metric = metrics.get(name)
        reason, value = None, None
        if metric is None:
            reason = "Required financial metric unavailable"
        else:
            value = metric.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                reason = "Financial value is not finite"
            elif timestamp(metric["available_at"], "financial availability") > as_of:
                reason = "Financial evidence arrived after the report cutoff"
            elif not metric.get("source_ids"):
                reason = "Financial evidence references missing"
            elif name == "borrowings_to_equity" and value < 0:
                reason = "Negative borrowings ratio requires review"
        score = None if reason else normalized(name, value)
        factors.append({"name": name, "weight": weight, "value": value,
                        "normalized": score, "points": None if reason else weight * score,
                        "source_ids": metric.get("source_ids", []) if metric else [],
                        "unavailable_reason": reason})
        if reason:
            blockers.append(f"{name}: {reason}")
    coverage = round(sum(f["weight"] for f in factors if f["points"] is not None), 8)
    score = None if blockers else sum(f["points"] for f in factors)
    candidate_reasons = []
    if not blockers:
        m = asset["metrics"]
        if asset["fundamentals"].get("financial_screen") != "passes":
            candidate_reasons.append("Separate financial screen did not pass")
        if m["momentum_20d"] <= 0 or m["trend_50d"] <= 0:
            candidate_reasons.append("Positive momentum and trend are both required")
        if score < POLICY["minimum_score"]:
            candidate_reasons.append("Combined score is below 60")
    return {"algorithm": ALGORITHM, "status": "excluded" if blockers else "eligible",
            "score": score, "rank": None, "highlight": False,
            "candidate": not blockers and not candidate_reasons, "coverage": coverage,
            "factors": factors, "blockers": blockers, "candidate_blockers": candidate_reasons}


def apply_combined_ranking(report):
    cutoff = timestamp(report["as_of"], "report cutoff")
    for asset in report["assets"]:
        asset["combined"] = combine_asset(asset, as_of=cutoff)
    ranked = sorted((a for a in report["assets"] if a["combined"]["score"] is not None),
                    key=lambda a: (-a["combined"]["score"], a["symbol"]))
    for index, asset in enumerate(ranked, 1):
        asset["combined"]["rank"] = index
    candidates = [a for a in ranked if a["combined"]["candidate"]]
    for asset in candidates[:POLICY["maximum_highlights"]]:
        asset["combined"]["highlight"] = True
    report.update(report_schema=SCHEMA, algorithm=ALGORITHM, ranking_policy=POLICY,
                  combined_highlights=[a["instrument_id"] for a in candidates[:10]],
                  combined_exclusion_counts=dict(Counter(b for a in report["assets"] for b in a["combined"]["blockers"])))
    report["counts"].update(combined_eligible=len(ranked), combined_candidates=len(candidates),
                            combined_highlights=min(10, len(candidates)))
    report["limitations"][:2] = [
        "Combined ranking uses 60% technical score and four financial factors at 10% each. All four financial metrics are required; weights and thresholds are unvalidated research choices.",
        "Scores are not probabilities or return forecasts. Only the separate forward experiment may create virtual orders after a decision is durably recorded; the manual paper ledger remains separate."]
    note = "Annual and peer P/E are displayed but not scored: reliable matched peer coverage is too sparse. Missing news and announcement analysis are disclosed, not assigned neutral values."
    if note not in report["limitations"]:
        report["limitations"].append(note)
    report["report_id"] = digest({k: v for k, v in report.items() if k != "report_id"})
    return report
