"""All tunable baseline parameters; no trained or 'optimal' coefficients."""

from dataclasses import asdict, dataclass, field
import math
from typing import Any

from .contracts import ValidationError, integer, number, obj

FACTOR_NAMES = (
    "momentum", "trend", "volume_confirmation", "profitability", "growth",
    "leverage", "valuation", "news", "announcements",
)
DEFAULT_WEIGHTS = dict(zip(FACTOR_NAMES, (.15, .10, .10, .15, .10, .10, .10, .10, .10)))


@dataclass(frozen=True)
class EngineConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    candidate_threshold: float = 65.0
    minimum_coverage: float = .70
    missing_data_penalty: float = 15.0
    volatility_penalty: float = 10.0
    volatility_penalty_starts: float = .20
    volatility_penalty_full: float = .60
    maximum_volatility: float = .80
    minimum_turnover_inr: float = 10_000_000.0
    maximum_debt_to_equity: float = 2.0
    maximum_price_age_days: int = 7
    maximum_fundamental_available_age_days: int = 200
    maximum_fundamental_observation_age_days: int = 550
    maximum_news_age_days: int = 7
    maximum_announcement_age_days: int = 14
    top_n: int = 10

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> "EngineConfig":
        defaults = cls().to_dict()
        c = obj(raw, "config", set(defaults))
        weights = obj(c["weights"], "config.weights", set(FACTOR_NAMES))
        checked = {k: number(v, f"config.weights.{k}", 0, 1) for k, v in weights.items()}
        if not math.isclose(sum(checked.values()), 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValidationError("config.weights: must sum to 1")
        values: dict[str, Any] = {"weights": checked}
        for name in ("candidate_threshold", "missing_data_penalty", "volatility_penalty"):
            values[name] = number(c[name], f"config.{name}", 0, 100)
        values["minimum_coverage"] = number(c["minimum_coverage"], "config.minimum_coverage", 0, 1)
        for name in ("volatility_penalty_starts", "volatility_penalty_full",
                     "maximum_volatility", "minimum_turnover_inr", "maximum_debt_to_equity"):
            values[name] = number(c[name], f"config.{name}", 0)
        for name in ("maximum_price_age_days", "maximum_fundamental_available_age_days",
                     "maximum_fundamental_observation_age_days", "maximum_news_age_days",
                     "maximum_announcement_age_days"):
            values[name] = integer(c[name], f"config.{name}", 1, 3650)
        values["top_n"] = integer(c["top_n"], "config.top_n", 1, 5000)
        if values["volatility_penalty_full"] <= values["volatility_penalty_starts"]:
            raise ValidationError("config: full volatility penalty must be above its starting point")
        if values["maximum_volatility"] < values["volatility_penalty_full"]:
            raise ValidationError("config: maximum_volatility must be >= volatility_penalty_full")
        return cls(**values)
