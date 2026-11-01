"""Transparent dimensionless baseline. Scores are not return forecasts."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import EngineConfig, FACTOR_NAMES
from .contracts import AssetSnapshot, DAILY_METRICS, FUNDAMENTAL_METRICS, ResearchBundle

DEPENDENCIES = {
    "momentum": ("momentum_20d",),
    "trend": ("trend_50d",),
    "volume_confirmation": ("volume_ratio_20d", "momentum_20d"),
    "profitability": ("roce",),
    "growth": ("revenue_growth_yoy",),
    "leverage": ("debt_to_equity",),
    "valuation": ("pe_to_sector_median",),
    "news": ("news_sentiment",),
    "announcements": ("announcement_impact",),
}


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


@dataclass(frozen=True)
class FactorEvidence:
    factor: str
    weight: float
    normalized: float | None
    points: float
    values: dict[str, float | None]
    source_ids: tuple[str, ...]
    unavailable_reason: str | None


@dataclass(frozen=True)
class Decision:
    instrument_id: str
    sector: str
    score: float
    coverage: float
    status: str
    factors: tuple[FactorEvidence, ...]
    missing_penalty: float
    risk_penalty: float
    reasons: tuple[str, ...]
    counterarguments: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _usable(
    asset: AssetSnapshot, name: str, bundle: ResearchBundle, config: EngineConfig,
) -> tuple[float | None, str | None]:
    metric = asset.metrics.get(name)
    if metric is None or metric.value is None:
        return None, f"{name}: missing"
    observation_age = (bundle.as_of - metric.observed_at).total_seconds() / 86400
    available_age = (bundle.as_of - metric.available_at).total_seconds() / 86400
    if name in DAILY_METRICS:
        if asset.session != bundle.last_session:
            return None, f"{name}: stale session"
        if observation_age > config.maximum_price_age_days:
            return None, f"{name}: observation too old"
    elif name in FUNDAMENTAL_METRICS:
        if observation_age > config.maximum_fundamental_observation_age_days:
            return None, f"{name}: reporting period too old"
        if available_age > config.maximum_fundamental_available_age_days:
            return None, f"{name}: filing too old"
    else:
        limit = (config.maximum_news_age_days if name == "news_sentiment"
                 else config.maximum_announcement_age_days)
        if observation_age > limit:
            return None, f"{name}: event window too old"
    return metric.value, None


def _normalize(factor: str, v: dict[str, float]) -> float:
    if factor == "momentum":
        return clamp(v["momentum_20d"] / .10)
    if factor == "trend":
        return clamp(v["trend_50d"] / .10)
    if factor == "volume_confirmation":
        direction = (v["momentum_20d"] > 0) - (v["momentum_20d"] < 0)
        return direction * clamp((v["volume_ratio_20d"] - 1) / 2, 0, 1)
    if factor == "profitability":
        return clamp((v["roce"] - .20) / .10)
    if factor == "growth":
        return clamp((v["revenue_growth_yoy"] - .10) / .20)
    if factor == "leverage":
        return clamp(1 - v["debt_to_equity"])
    if factor == "valuation":
        return clamp((1 - v["pe_to_sector_median"]) / .50)
    if factor == "news":
        return v["news_sentiment"]
    if factor == "announcements":
        return v["announcement_impact"]
    raise AssertionError(f"Unrecognized factor: {factor}")


def score_asset(asset: AssetSnapshot, bundle: ResearchBundle, config: EngineConfig) -> Decision:
    factors: list[FactorEvidence] = []
    warnings: list[str] = []
    for factor in FACTOR_NAMES:
        values: dict[str, float | None] = {}
        sources: set[str] = set()
        problems: list[str] = []
        for name in DEPENDENCIES[factor]:
            value, issue = _usable(asset, name, bundle, config)
            values[name] = value
            if name in asset.metrics:
                sources.update(asset.metrics[name].source_ids)
            if issue:
                problems.append(issue)
        weight = config.weights[factor]
        normalized = None if problems else _normalize(factor, values)
        contribution = 0.0 if normalized is None else 50 * weight * normalized
        issue_text = "; ".join(problems) if problems else None
        if issue_text and weight > 0:
            warnings.append(f"{factor}: {issue_text}")
        factors.append(FactorEvidence(
            factor, weight, normalized, contribution, values, tuple(sorted(sources)), issue_text,
        ))
    coverage = min(1.0, sum(f.weight for f in factors if f.normalized is not None))
    missing_penalty = config.missing_data_penalty * (1 - coverage)
    controls = {}
    blockers = []
    for name in ("close_inr", "turnover_20d_inr", "volatility_20d_annualized", "debt_to_equity"):
        value, issue = _usable(asset, name, bundle, config)
        controls[name] = value
        if issue:
            blockers.append(f"Required risk input unavailable: {issue}")
    if asset.sector == "financials":
        blockers.append("Financial-sector accounting requires a separate quality model")
    turnover = controls["turnover_20d_inr"]
    if turnover is not None and turnover < config.minimum_turnover_inr:
        blockers.append("Average daily turnover below the configured liquidity floor")
    debt = controls["debt_to_equity"]
    if debt is not None and debt > config.maximum_debt_to_equity:
        blockers.append("Debt-to-equity exceeds the configured ceiling")
    volatility = controls["volatility_20d_annualized"]
    if volatility is not None and volatility > config.maximum_volatility:
        blockers.append("Volatility exceeds the configured ceiling")
    if coverage + 1e-12 < config.minimum_coverage:
        blockers.append("Factor coverage below the configured minimum")
    risk_penalty = 0.0 if volatility is None else config.volatility_penalty * clamp(
        (volatility - config.volatility_penalty_starts) /
        (config.volatility_penalty_full - config.volatility_penalty_starts), 0, 1,
    )
    score = clamp(50 + sum(f.points for f in factors) - missing_penalty - risk_penalty, 0, 100)
    status = "excluded" if blockers else ("candidate" if score >= config.candidate_threshold else "watch")
    positive = sorted((f for f in factors if f.points > 1e-12), key=lambda f: (-f.points, f.factor))
    negative = sorted((f for f in factors if f.points < -1e-12), key=lambda f: (f.points, f.factor))

    def reason(f: FactorEvidence) -> str:
        values_text = ", ".join(f"{k}={v:.4g}" for k, v in f.values.items())
        return f"{f.factor}: {f.points:+.2f} score points ({values_text})"

    reasons = [reason(f) for f in positive[:3]]
    counterarguments = [reason(f) for f in negative[:3]]
    if missing_penalty > 1e-12:
        counterarguments.append(f"Missing or stale factors: -{missing_penalty:.2f} points")
    if risk_penalty > 1e-12:
        counterarguments.append(f"Volatility penalty: -{risk_penalty:.2f} points")
    counterarguments.extend(blockers)
    if not reasons:
        reasons.append("No positively contributing factors")
    return Decision(
        asset.instrument_id, asset.sector, score, coverage, status, tuple(factors),
        missing_penalty, risk_penalty, tuple(reasons), tuple(counterarguments),
        tuple(blockers), tuple(warnings),
    )


def rank_bundle(bundle: ResearchBundle, config: EngineConfig) -> list[Decision]:
    """Stable ordering: candidate, watch, excluded; score descending; identifier ascending."""
    status_order = {"candidate": 0, "watch": 1, "excluded": 2}
    return sorted(
        (score_asset(asset, bundle, config) for asset in bundle.assets),
        key=lambda decision: (status_order[decision.status], -decision.score, decision.instrument_id),
    )
