"""Public integration entry point. Revalidates external objects before calculation."""

from datetime import datetime
from typing import Any

from . import ALGORITHM_VERSION, SCHEMA_VERSION, __version__
from .config import EngineConfig
from .contracts import ResearchBundle, UTC, ValidationError, iso, parse_bundle
from .scoring import rank_bundle
from .serialization import digest

LIMITATIONS = [
    "This is an untrained research baseline, not a probability or expected-return forecast.",
    "Candidates are paper-research signals; no trading or brokerage integration exists.",
    "Source timestamps are checked as supplied; vendor truth and historical vintages require independent verification.",
    "The exchange session calendar and universe membership must come from the provider.",
    "Correlated factors can double-count information; weights and thresholds are research hypotheses.",
    "Missing data is penalized; coverage measures completeness, not predictive confidence.",
]


def build_run(
    raw_bundle: dict | ResearchBundle, raw_config: dict | EngineConfig | None = None,
    *, generated_at: datetime | None = None,
) -> dict[str, Any]:
    bundle = parse_bundle(raw_bundle.to_dict() if isinstance(raw_bundle, ResearchBundle) else raw_bundle)
    if raw_config is None:
        raw_config = EngineConfig()
    config = EngineConfig.from_dict(raw_config.to_dict() if isinstance(raw_config, EngineConfig) else raw_config)
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationError("generated_at must include a timezone")
    input_data = bundle.to_dict()
    config_data = config.to_dict()
    identity = {
        "input_sha256": digest(input_data), "config_sha256": digest(config_data),
        "engine_version": __version__, "algorithm_version": ALGORITHM_VERSION,
    }
    decisions = rank_bundle(bundle, config)
    shortlist = [d.instrument_id for d in decisions if d.status == "candidate"][:config.top_n]
    counts = {status: sum(d.status == status for d in decisions)
              for status in ("candidate", "watch", "excluded")}
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": digest(identity),
        **identity,
        "generated_at": iso(now),
        "as_of": iso(bundle.as_of),
        "last_session": bundle.last_session.isoformat(),
        "mode": bundle.mode,
        "dataset_id": bundle.dataset_id,
        "score_kind": "dimensionless_unvalidated_baseline",
        "counts": counts,
        "shortlist": shortlist,
        "abstained": len(shortlist) == 0,
        "decisions": [d.to_dict() for d in decisions],
        "limitations": LIMITATIONS + (["All instruments and figures in this run are fictional fixtures."]
                                      if bundle.mode == "synthetic" else []),
        "input": input_data,
        "config": config_data,
    }
