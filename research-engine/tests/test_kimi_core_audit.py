"""Independent audit of the Oraculum core (Kimi's Part A).

Every expected score is re-derived from docs/ALGORITHM.md by this file's own
code -- the production scoring helpers are never used to produce expected
values. Where Qwen's implementation is unavailable, nothing is substituted.
"""

from dataclasses import replace
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta

from oraculum.config import EngineConfig
from oraculum.contracts import (
    AssetSnapshot,
    Metric,
    ResearchBundle,
    Source,
    UTC,
    ValidationError,
)
from oraculum.pipeline import build_run
from oraculum.repository import RunRepository

AS_OF = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)
SESSION = date(2024, 3, 14)
OBSERVED = AS_OF - timedelta(days=1)

SOURCES = (
    Source(id="src_prices", kind="prices", title="Fixture prices",
           uri="fixture://prices", published_at=OBSERVED,
           available_at=OBSERVED, content_sha256=None),
    Source(id="src_derived", kind="derived", title="Fixture derived",
           uri="fixture://derived", published_at=OBSERVED,
           available_at=OBSERVED, content_sha256=None),
    Source(id="src_fund", kind="fundamentals", title="Fixture fundamentals",
           uri="fixture://fundamentals", published_at=OBSERVED,
           available_at=OBSERVED, content_sha256=None),
    Source(id="src_news", kind="news", title="Fixture news",
           uri="fixture://news", published_at=OBSERVED,
           available_at=OBSERVED, content_sha256=None),
    Source(id="src_ann", kind="announcement", title="Fixture announcements",
           uri="fixture://announcements", published_at=OBSERVED,
           available_at=OBSERVED, content_sha256=None),
)

_SOURCE_FOR = {
    "close_inr": ("src_prices",), "turnover_20d_inr": ("src_prices",),
    "momentum_20d": ("src_prices",), "trend_50d": ("src_prices",),
    "volume_ratio_20d": ("src_prices",),
    "volatility_20d_annualized": ("src_derived",),
    "roce": ("src_fund",), "revenue_growth_yoy": ("src_fund",),
    "debt_to_equity": ("src_fund",), "pe_to_sector_median": ("src_fund",),
    "news_sentiment": ("src_news",),
    "announcement_impact": ("src_ann",),
}

BASE_VALUES = {
    "close_inr": 100.0, "turnover_20d_inr": 50_000_000.0,
    "volatility_20d_annualized": 0.24, "momentum_20d": 0.08,
    "trend_50d": 0.06, "volume_ratio_20d": 1.8, "roce": 0.26,
    "revenue_growth_yoy": 0.22, "debt_to_equity": 0.4,
    "pe_to_sector_median": 0.8, "news_sentiment": 0.6,
    "announcement_impact": 0.7,
}

# Independently transcribed from the docs/ALGORITHM.md weight table.
WEIGHTS = {"momentum": 0.15, "trend": 0.10, "volume_confirmation": 0.10,
           "profitability": 0.15, "growth": 0.10, "leverage": 0.10,
           "valuation": 0.10, "news": 0.10, "announcements": 0.10}
DEPENDENCIES = {
    "momentum": ("momentum_20d",), "trend": ("trend_50d",),
    "volume_confirmation": ("volume_ratio_20d", "momentum_20d"),
    "profitability": ("roce",), "growth": ("revenue_growth_yoy",),
    "leverage": ("debt_to_equity",), "valuation": ("pe_to_sector_median",),
    "news": ("news_sentiment",), "announcements": ("announcement_impact",),
}


def clip(value, low=-1.0, high=1.0):
    return min(high, max(low, value))


def independent_norm(factor, values):
    if factor == "momentum":
        return clip(values["momentum_20d"] / 0.10)
    if factor == "trend":
        return clip(values["trend_50d"] / 0.10)
    if factor == "volume_confirmation":
        direction = (values["momentum_20d"] > 0) - (values["momentum_20d"] < 0)
        return direction * clip((values["volume_ratio_20d"] - 1) / 2, 0, 1)
    if factor == "profitability":
        return clip((values["roce"] - 0.20) / 0.10)
    if factor == "growth":
        return clip((values["revenue_growth_yoy"] - 0.10) / 0.20)
    if factor == "leverage":
        return clip(1 - values["debt_to_equity"])
    if factor == "valuation":
        return clip((1 - values["pe_to_sector_median"]) / 0.50)
    if factor == "news":
        return clip(values["news_sentiment"])
    if factor == "announcements":
        return clip(values["announcement_impact"])
    raise AssertionError(factor)


def independent_score(values):
    """Re-derive (score, coverage) from docs/ALGORITHM.md, from scratch."""
    coverage = sum(w for f, w in WEIGHTS.items()
                   if all(k in values for k in DEPENDENCIES[f]))
    points = 0.0
    for factor, weight in WEIGHTS.items():
        if all(k in values for k in DEPENDENCIES[factor]):
            points += 50 * weight * independent_norm(factor, values)
    missing_penalty = 15.0 * (1 - coverage)
    volatility = values.get("volatility_20d_annualized")
    volatility_penalty = (0.0 if volatility is None
                          else 10.0 * clip((volatility - 0.20) / 0.40, 0, 1))
    score = clip(50 + points - missing_penalty - volatility_penalty, 0, 100)
    return score, coverage


def make_metric(name, value, observed=OBSERVED, available=OBSERVED):
    return Metric(value=value, observed_at=observed, available_at=available,
                  source_ids=_SOURCE_FOR[name])


def build_asset(symbol, sector="technology", session=SESSION, omit=(),
                overrides=None, observed=OBSERVED, available=OBSERVED):
    values = dict(BASE_VALUES)
    values.update(overrides or {})
    metrics = {}
    for name, value in values.items():
        if name in omit:
            continue
        metrics[name] = make_metric(name, value, observed=observed,
                                    available=available)
    return AssetSnapshot(symbol=symbol, exchange="NSE", sector=sector,
                         session=session, metrics=metrics)


def make_bundle(assets):
    return ResearchBundle(dataset_id="kimi-audit-fixture", mode="synthetic",
                          as_of=AS_OF, last_session=SESSION,
                          session_close_at=OBSERVED, sources=SOURCES,
                          assets=tuple(assets))


def decision_of(report, instrument_id):
    for decision in report["decisions"]:
        if decision["instrument_id"] == instrument_id:
            return decision
    raise AssertionError(f"{instrument_id} not in report decisions")


def factor_of(decision, factor):
    for evidence in decision["factors"]:
        if evidence["factor"] == factor:
            return evidence
    raise AssertionError(f"factor {factor} missing")


class CoreAuditEquationTests(unittest.TestCase):
    def run_assets(self, assets, config=None, generated_at=AS_OF):
        bundle = make_bundle(assets)
        report = build_run(bundle.to_dict(), config, generated_at=generated_at)
        return report

    def test_worked_fixture_matches_documentation_and_independent_calc(self):
        report = self.run_assets([build_asset("ALPHA")])
        decision = decision_of(report, "NSE:ALPHA")
        # Documented fixture arithmetic: 50 + 30 - 0 - 1 = 79.
        self.assertAlmostEqual(decision["score"], 79.0, places=9)
        self.assertAlmostEqual(decision["coverage"], 1.0, places=12)
        self.assertAlmostEqual(decision["missing_penalty"], 0.0, places=12)
        self.assertAlmostEqual(decision["risk_penalty"], 1.0, places=12)
        self.assertEqual(decision["status"], "candidate")
        expected, coverage = independent_score(BASE_VALUES)
        self.assertAlmostEqual(decision["score"], expected, places=9)
        self.assertAlmostEqual(decision["coverage"], coverage, places=12)
        self.assertEqual(report["shortlist"], ["NSE:ALPHA"])
        self.assertFalse(report["abstained"])
        self.assertEqual(report["score_kind"],
                         "dimensionless_unvalidated_baseline")
        # Synthetic runs must carry the fictional-fixtures disclaimer.
        self.assertTrue(any("fictional" in line
                            for line in report["limitations"]))

    def test_missing_data_penalty_and_weighted_coverage(self):
        values = {k: v for k, v in BASE_VALUES.items()
                  if k not in ("news_sentiment", "announcement_impact")}
        report = self.run_assets([build_asset(
            "BETA", omit=("news_sentiment", "announcement_impact"))])
        decision = decision_of(report, "NSE:BETA")
        # Coverage is weighted completeness (0.8), not a count of factors.
        self.assertAlmostEqual(decision["coverage"], 0.8, places=12)
        self.assertAlmostEqual(decision["missing_penalty"], 3.0, places=12)
        expected, coverage = independent_score(values)
        self.assertAlmostEqual(decision["score"], expected, places=9)
        self.assertAlmostEqual(decision["coverage"], coverage, places=12)

    def test_volume_confirmation_direction(self):
        falling = self.run_assets([build_asset(
            "FALL", overrides={"momentum_20d": -0.08,
                               "volume_ratio_20d": 3.0})])
        evidence = factor_of(decision_of(falling, "NSE:FALL"),
                             "volume_confirmation")
        # Surge on falling prices contributes -5.0 points.
        self.assertAlmostEqual(evidence["normalized"], -1.0, places=12)
        self.assertAlmostEqual(evidence["points"], -5.0, places=12)
        flat = self.run_assets([build_asset(
            "FLAT", overrides={"momentum_20d": 0.0,
                               "volume_ratio_20d": 5.0})])
        evidence = factor_of(decision_of(flat, "NSE:FLAT"),
                             "volume_confirmation")
        self.assertAlmostEqual(evidence["normalized"], 0.0, places=12)
        self.assertAlmostEqual(evidence["points"], 0.0, places=12)

    def test_score_clamps_at_bounds(self):
        high = self.run_assets([build_asset(
            "HIGH", overrides={"volatility_20d_annualized": 0.20, "momentum_20d": 5.0, "trend_50d": 1.0,
                               "volume_ratio_20d": 10.0, "roce": 1.0,
                               "revenue_growth_yoy": 1.0, "debt_to_equity": 0.0,
                               "pe_to_sector_median": 0.1,
                               "news_sentiment": 1.0,
                               "announcement_impact": 1.0})])
        self.assertAlmostEqual(decision_of(high, "NSE:HIGH")["score"],
                               100.0, places=9)
        low = self.run_assets([build_asset(
            "LOW", overrides={"momentum_20d": -0.5, "trend_50d": -0.5,
                              "volume_ratio_20d": 5.0, "roce": -1.0,
                              "revenue_growth_yoy": -1.0, "debt_to_equity": 2.0,
                              "pe_to_sector_median": 3.0,
                              "news_sentiment": -1.0,
                              "announcement_impact": -1.0})])
        decision = decision_of(low, "NSE:LOW")
        self.assertAlmostEqual(decision["score"], 0.0, places=9)
        self.assertEqual(decision["status"], "watch")


class CoreAuditExclusionTests(unittest.TestCase):
    def run_one(self, **kwargs):
        bundle = make_bundle([build_asset("GAMMA", **kwargs)])
        return build_run(bundle.to_dict(), generated_at=AS_OF)

    def test_low_turnover_excluded_despite_high_score(self):
        report = self.run_one(overrides={"turnover_20d_inr": 5_000_000.0})
        decision = decision_of(report, "NSE:GAMMA")
        self.assertEqual(decision["status"], "excluded")
        self.assertGreaterEqual(decision["score"], 65.0)  # high diagnostic score
        self.assertNotIn("NSE:GAMMA", report["shortlist"])
        self.assertTrue(any("liquidity floor" in b
                            for b in decision["blockers"]))

    def test_financial_sector_excluded(self):
        report = self.run_one(sector="financials")
        decision = decision_of(report, "NSE:GAMMA")
        self.assertEqual(decision["status"], "excluded")
        self.assertTrue(any("quality model" in b
                            for b in decision["blockers"]))

    def test_high_volatility_excluded(self):
        report = self.run_one(overrides={"volatility_20d_annualized": 0.90})
        decision = decision_of(report, "NSE:GAMMA")
        self.assertEqual(decision["status"], "excluded")
        self.assertTrue(any("Volatility exceeds" in b
                            for b in decision["blockers"]))

    def test_high_debt_excluded(self):
        report = self.run_one(overrides={"debt_to_equity": 3.0})
        decision = decision_of(report, "NSE:GAMMA")
        self.assertEqual(decision["status"], "excluded")
        self.assertTrue(any("Debt-to-equity exceeds" in b
                            for b in decision["blockers"]))

    def test_low_coverage_excluded(self):
        report = self.run_one(omit=("roce", "revenue_growth_yoy", "pe_to_sector_median",
                                    "news_sentiment", "announcement_impact"))
        decision = decision_of(report, "NSE:GAMMA")
        self.assertLess(decision["coverage"], 0.70)
        self.assertEqual(decision["status"], "excluded")
        self.assertTrue(any("coverage" in b for b in decision["blockers"]))

    def test_stale_price_session_excluded(self):
        report = self.run_one(session=SESSION - timedelta(days=1),
                              observed=OBSERVED - timedelta(days=1))
        decision = decision_of(report, "NSE:GAMMA")
        self.assertEqual(decision["status"], "excluded")
        self.assertTrue(any("stale session" in b
                            for b in decision["blockers"]))


class CoreAuditFreshnessTests(unittest.TestCase):
    def test_news_observation_cutoff(self):
        asset = build_asset("DELTA", observed=OBSERVED)
        stale_news = make_metric("news_sentiment", 0.6,
                                 observed=AS_OF - timedelta(days=8))
        metrics = dict(asset.metrics)
        metrics["news_sentiment"] = stale_news
        asset = AssetSnapshot(symbol="DELTA", exchange="NSE",
                              sector="technology", session=SESSION,
                              metrics=metrics)
        report = build_run(make_bundle([asset]).to_dict(), generated_at=AS_OF)
        decision = decision_of(report, "NSE:DELTA")
        evidence = factor_of(decision, "news")
        self.assertIsNone(evidence["normalized"])
        self.assertIn("event window too old",
                      evidence["unavailable_reason"])
        self.assertTrue(any("news" in w and "event window too old" in w
                            for w in decision["warnings"]))

    def test_fundamental_availability_cutoff_blocks_debt_control(self):
        old = AS_OF - timedelta(days=201)
        asset = build_asset("EPSI")
        metrics = dict(asset.metrics)
        metrics["debt_to_equity"] = make_metric("debt_to_equity", 0.4,
                                                observed=old, available=old)
        sources = tuple(replace(s, published_at=old, available_at=old)
                        if s.id == "src_fund" else s for s in SOURCES)
        bundle = replace(make_bundle([replace(asset, metrics=metrics)]), sources=sources)
        report = build_run(bundle.to_dict(), generated_at=AS_OF)
        decision = decision_of(report, "NSE:EPSI")
        self.assertEqual(decision["status"], "excluded")
        self.assertTrue(any("debt_to_equity" in b and "filing too old" in b
                            for b in decision["blockers"]))

    def test_daily_observation_cutoff_blocks_close_control(self):
        # Keep a valid latest-session snapshot and advance the research cutoff.
        # This isolates age from the separate stale-session check.
        asset = build_asset("ZETA")
        later = AS_OF + timedelta(days=8)
        bundle = replace(make_bundle([asset]), as_of=later)
        report = build_run(bundle.to_dict(), generated_at=later)
        decision = decision_of(report, "NSE:ZETA")
        self.assertEqual(decision["status"], "excluded")
        self.assertTrue(any("close_inr" in b and "observation too old" in b
                            for b in decision["blockers"]))


class CoreAuditValidationAndReplayTests(unittest.TestCase):
    def test_invalid_inputs_rejected(self):
        bundle = make_bundle([build_asset("ALPHA")]).to_dict()
        with self.assertRaises(ValidationError):
            build_run({"dataset_id": "x"})  # missing fields
        extra = dict(bundle)
        extra["bogus"] = 1
        with self.assertRaises(ValidationError):
            build_run(extra)  # unknown field
        naive = dict(bundle)
        naive["as_of"] = "2024-03-15T10:00:00"  # no timezone
        with self.assertRaises(ValidationError):
            build_run(naive)
        bad_sector = make_bundle([build_asset("ALPHA", sector="not_a_sector")])
        with self.assertRaises(ValidationError):
            build_run(bad_sector.to_dict())
        bad_metric = make_bundle([build_asset("ALPHA")]).to_dict()
        bad_metric["assets"][0]["metrics"]["roce"]["value"] = "high"
        with self.assertRaises(ValidationError):
            build_run(bad_metric)
        config = EngineConfig().to_dict()
        config["weights"] = {name: 0.1 for name in config["weights"]}
        with self.assertRaises(ValidationError):
            build_run(bundle, config)  # weights sum to 0.9
        with self.assertRaises(ValidationError):
            build_run(bundle, generated_at=datetime(2024, 3, 15, 10, 0))

    def test_replay_consistency(self):
        bundle = make_bundle([build_asset("ALPHA")]).to_dict()
        run1 = build_run(bundle, generated_at=AS_OF)
        run2 = build_run(bundle, generated_at=AS_OF + timedelta(days=1))
        self.assertEqual(run1["run_id"], run2["run_id"])
        self.assertEqual(run1["input_sha256"], run2["input_sha256"])
        self.assertEqual(run1["config_sha256"], run2["config_sha256"])
        self.assertEqual(run1["decisions"], run2["decisions"])
        self.assertEqual(run1["shortlist"], run2["shortlist"])
        # Any input change must change the run identity.
        changed = make_bundle([build_asset(
            "ALPHA", overrides={"momentum_20d": 0.09})]).to_dict()
        run3 = build_run(changed, generated_at=AS_OF)
        self.assertNotEqual(run1["run_id"], run3["run_id"])

    def test_shortlist_top_n_and_abstain(self):
        assets = [build_asset("A1"), build_asset("A2"), build_asset("A3")]
        bundle = make_bundle(assets).to_dict()
        report = build_run(bundle, EngineConfig(top_n=2),
                           generated_at=AS_OF)
        self.assertEqual(len(report["shortlist"]), 2)
        self.assertEqual(report["counts"]["candidate"], 3)
        excluded = make_bundle([build_asset("F1", sector="financials"),
                                build_asset("F2", sector="financials")])
        report2 = build_run(excluded.to_dict(), generated_at=AS_OF)
        self.assertTrue(report2["abstained"])
        self.assertEqual(report2["shortlist"], [])
        self.assertEqual(report2["counts"]["excluded"], 2)

    def test_persisted_report_and_replay_from_snapshot(self):
        report = build_run(make_bundle([build_asset("ALPHA")]).to_dict(),
                           generated_at=AS_OF)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "audit.sqlite3")
            repo = RunRepository(db_path)
            saved = repo.save(report)
            saved_again = repo.save(report)
            # Read through a fresh repository to verify the stored snapshot.
            self.assertEqual(RunRepository(db_path).get(saved["run_id"]), saved)
            self.assertEqual(saved["run_id"], report["run_id"])
            self.assertEqual(saved_again["run_id"], report["run_id"])
            # Replay purely from the persisted snapshot: the run identity must
            # reproduce even though generated_at is not part of it.
            replay = build_run(saved["input"], saved["config"],
                               generated_at=AS_OF + timedelta(days=3))
            self.assertEqual(replay["run_id"], saved["run_id"])
            # The database really persisted content.
            con = sqlite3.connect(db_path)
            try:
                tables = {row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
            self.assertTrue(tables)


if __name__ == "__main__":
    unittest.main()
