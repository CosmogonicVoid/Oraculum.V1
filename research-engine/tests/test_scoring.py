from copy import deepcopy
import unittest

from oraculum.config import EngineConfig
from oraculum.contracts import DAILY_METRICS
from oraculum.demo import make_demo_bundle
from oraculum.pipeline import build_run


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.raw = make_demo_bundle()

    def first(self, raw=None, config=None):
        raw = deepcopy(raw or self.raw)
        raw["assets"] = [raw["assets"][0]]
        return build_run(raw, config)["decisions"][0]

    def test_hand_calculated_baseline(self):
        # +6 momentum +3 trend +2 volume +4.5 profitability +3 growth
        # +3 leverage +2 valuation +3 news +3.5 announcement -1 volatility.
        d = self.first()
        self.assertAlmostEqual(d["score"], 79.0)
        self.assertAlmostEqual(d["coverage"], 1.0)
        self.assertEqual(d["status"], "candidate")

    def test_neutral_inputs_score_50(self):
        report = build_run(self.raw)
        d = next(d for d in report["decisions"] if d["instrument_id"] == "NSE:SIM-CEDAR")
        self.assertAlmostEqual(d["score"], 50.0)
        self.assertEqual(d["status"], "watch")

    def test_missing_positive_news_is_not_invented_or_reweighted(self):
        metric = self.raw["assets"][0]["metrics"]["news_sentiment"]
        metric["value"], metric["source_ids"] = None, []
        d = self.first()
        self.assertAlmostEqual(d["coverage"], .9)
        self.assertAlmostEqual(d["score"], 74.5)  # remove +3, subtract 1.5 completeness penalty
        f = next(f for f in d["factors"] if f["factor"] == "news")
        self.assertIsNone(f["normalized"])

    def test_volume_on_falling_prices_is_negative(self):
        self.raw["assets"][0]["metrics"]["momentum_20d"]["value"] = -.1
        self.raw["assets"][0]["metrics"]["volume_ratio_20d"]["value"] = 3
        d = self.first()
        f = next(f for f in d["factors"] if f["factor"] == "volume_confirmation")
        self.assertAlmostEqual(f["points"], -5)

    def test_flat_price_has_no_directional_volume_bonus(self):
        self.raw["assets"][0]["metrics"]["momentum_20d"]["value"] = 0
        self.raw["assets"][0]["metrics"]["volume_ratio_20d"]["value"] = 10
        f = next(f for f in self.first()["factors"] if f["factor"] == "volume_confirmation")
        self.assertEqual(f["points"], 0)

    def test_more_volatility_reduces_score(self):
        initial = self.first()["score"]
        self.raw["assets"][0]["metrics"]["volatility_20d_annualized"]["value"] = .4
        self.assertAlmostEqual(self.first()["score"], initial - 4)

    def test_risk_gates_cannot_be_overridden_by_high_score(self):
        for name, value in (
            ("turnover_20d_inr", 100), ("volatility_20d_annualized", 1),
            ("debt_to_equity", 3),
        ):
            raw = deepcopy(self.raw)
            raw["assets"][0]["metrics"][name]["value"] = value
            with self.subTest(metric=name):
                self.assertEqual(self.first(raw)["status"], "excluded")

    def test_missing_risk_input_excludes(self):
        del self.raw["assets"][0]["metrics"]["turnover_20d_inr"]
        self.assertEqual(self.first()["status"], "excluded")

    def test_stale_price_session_excludes(self):
        asset = self.raw["assets"][0]
        asset["session"] = "2026-10-08"
        for name in DAILY_METRICS:
            asset["metrics"][name]["observed_at"] = "2026-10-08T10:00:00Z"
        self.assertEqual(self.first()["status"], "excluded")

    def test_stale_filing_is_missing_instead_of_current(self):
        self.raw["sources"][1]["published_at"] = "2025-08-12T04:30:00Z"
        self.raw["sources"][1]["available_at"] = "2025-08-12T04:30:00Z"
        m = self.raw["assets"][0]["metrics"]["roce"]
        m["observed_at"], m["available_at"] = "2025-06-30T10:00:00Z", "2025-08-12T04:30:00Z"
        d = self.first()
        self.assertAlmostEqual(d["coverage"], .85)
        self.assertTrue(any("filing too old" in warning for warning in d["warnings"]))

    def test_financial_sector_is_excluded(self):
        self.raw["assets"][0]["sector"] = "financials"
        self.assertEqual(self.first()["status"], "excluded")

    def test_abstains_instead_of_filling_top_list(self):
        config = EngineConfig().to_dict()
        config["candidate_threshold"] = 100
        report = build_run(self.raw, config)
        self.assertTrue(report["abstained"])
        self.assertEqual(report["shortlist"], [])

    def test_top_n_only_limits_shortlist(self):
        config = EngineConfig().to_dict()
        config["top_n"] = 1
        report = build_run(self.raw, config)
        self.assertEqual(report["shortlist"], ["NSE:SIM-ASTER"])
        self.assertEqual(len(report["decisions"]), 8)

    def test_ties_and_reordered_input_are_deterministic(self):
        twin = deepcopy(self.raw["assets"][0])
        twin["symbol"] = "SIM-ZETA"
        self.raw["assets"] = [twin, self.raw["assets"][0]]
        first = build_run(self.raw)
        self.raw["assets"].reverse()
        self.raw["sources"].reverse()
        second = build_run(self.raw)
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["shortlist"], ["NSE:SIM-ASTER", "NSE:SIM-ZETA"])

    def test_formula_reconciles_exactly(self):
        for d in build_run(self.raw)["decisions"]:
            expected = min(100, max(0, 50 + sum(f["points"] for f in d["factors"])
                                   - d["missing_penalty"] - d["risk_penalty"]))
            self.assertAlmostEqual(d["score"], expected)

    def test_empty_universe_abstains(self):
        self.raw["assets"] = []
        self.assertTrue(build_run(self.raw)["abstained"])

    def test_changes_to_config_and_inputs_create_new_identity(self):
        first = build_run(self.raw)["run_id"]
        config = EngineConfig().to_dict()
        config["candidate_threshold"] = 70
        self.assertNotEqual(first, build_run(self.raw, config)["run_id"])
        self.raw["assets"][0]["metrics"]["roce"]["value"] = .28
        self.assertNotEqual(first, build_run(self.raw)["run_id"])
