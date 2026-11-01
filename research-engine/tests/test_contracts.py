from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest

from oraculum.config import EngineConfig
from oraculum.contracts import ValidationError, parse_bundle
from oraculum.demo import make_demo_bundle
from oraculum.serialization import load_json


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.raw = make_demo_bundle()

    def test_round_trip_normalizes_and_preserves_bundle(self):
        bundle = parse_bundle(self.raw)
        self.assertEqual(parse_bundle(bundle.to_dict()), bundle)

    def test_future_source_rejected(self):
        self.raw["sources"][0]["available_at"] = "2026-10-10T10:00:00Z"
        with self.assertRaisesRegex(ValidationError, "available_at"):
            parse_bundle(self.raw)

    def test_future_metric_rejected(self):
        self.raw["assets"][0]["metrics"]["roce"]["available_at"] = "2026-10-10T10:00:00Z"
        with self.assertRaisesRegex(ValidationError, "available_at"):
            parse_bundle(self.raw)

    def test_metric_cannot_precede_its_source(self):
        self.raw["assets"][0]["metrics"]["roce"]["available_at"] = "2026-07-01T10:00:00Z"
        with self.assertRaisesRegex(ValidationError, "before its source"):
            parse_bundle(self.raw)

    def test_observation_cannot_follow_availability(self):
        self.raw["assets"][0]["metrics"]["roce"]["observed_at"] = "2026-10-01T10:00:00Z"
        with self.assertRaises(ValidationError):
            parse_bundle(self.raw)

    def test_timezone_required(self):
        self.raw["as_of"] = "2026-10-09T12:00:00"
        with self.assertRaisesRegex(ValidationError, "timezone"):
            parse_bundle(self.raw)

    def test_intraday_snapshot_cannot_masquerade_as_daily_close(self):
        self.raw["assets"][0]["metrics"]["close_inr"]["observed_at"] = "2026-10-09T08:00:00Z"
        with self.assertRaisesRegex(ValidationError, "session_close_at"):
            parse_bundle(self.raw)

    def test_session_must_have_closed(self):
        self.raw["as_of"] = "2026-10-09T09:59:00Z"
        with self.assertRaisesRegex(ValidationError, "session_close_at"):
            parse_bundle(self.raw)

    def test_unknown_fields_and_misspelled_metrics_rejected(self):
        for where, key in ((self.raw, "extra"), (self.raw["assets"][0]["metrics"], "momentum20")):
            where[key] = 0
            with self.assertRaisesRegex(ValidationError, "unknown fields"):
                parse_bundle(self.raw)
            del where[key]

    def test_duplicate_instrument_rejected(self):
        self.raw["assets"].append(deepcopy(self.raw["assets"][0]))
        with self.assertRaisesRegex(ValidationError, "duplicate instrument"):
            parse_bundle(self.raw)

    def test_duplicate_source_rejected(self):
        self.raw["sources"].append(deepcopy(self.raw["sources"][0]))
        with self.assertRaisesRegex(ValidationError, "duplicate source"):
            parse_bundle(self.raw)

    def test_unknown_source_rejected(self):
        self.raw["assets"][0]["metrics"]["roce"]["source_ids"] = ["missing-source"]
        with self.assertRaisesRegex(ValidationError, "unknown source"):
            parse_bundle(self.raw)

    def test_non_null_metric_needs_evidence(self):
        self.raw["assets"][0]["metrics"]["roce"]["source_ids"] = []
        with self.assertRaisesRegex(ValidationError, "require a source"):
            parse_bundle(self.raw)

    def test_numeric_types_and_ranges(self):
        metric = self.raw["assets"][0]["metrics"]["close_inr"]
        for value in (0, -1, True, "100", math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                metric["value"] = value
                with self.assertRaises(ValidationError):
                    parse_bundle(self.raw)

    def test_enum_containers_get_clean_validation_errors(self):
        self.raw["assets"][0]["sector"] = []
        with self.assertRaises(ValidationError):
            parse_bundle(self.raw)
        self.raw["assets"][0]["sector"] = "industrials"
        self.raw["sources"][0]["kind"] = {}
        with self.assertRaises(ValidationError):
            parse_bundle(self.raw)

    def test_imported_bundle_cannot_use_fixture_uris(self):
        self.raw["mode"] = "imported"
        with self.assertRaisesRegex(ValidationError, "URI"):
            parse_bundle(self.raw)

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "duplicate"):
                load_json(path)

    def test_nan_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "non-finite"):
                load_json(path)


class ConfigTests(unittest.TestCase):
    def test_default_config_round_trip(self):
        self.assertEqual(EngineConfig.from_dict(EngineConfig().to_dict()), EngineConfig())

    def test_invalid_weights(self):
        for weight in (-1, .9, math.nan, True):
            raw = EngineConfig().to_dict()
            raw["weights"]["momentum"] = weight
            with self.subTest(weight=weight), self.assertRaises(ValidationError):
                EngineConfig.from_dict(raw)

    def test_invalid_volatility_range(self):
        raw = EngineConfig().to_dict()
        raw["volatility_penalty_full"] = raw["volatility_penalty_starts"]
        with self.assertRaises(ValidationError):
            EngineConfig.from_dict(raw)

    def test_missing_config_field_is_not_silently_defaulted(self):
        raw = EngineConfig().to_dict()
        del raw["minimum_coverage"]
        with self.assertRaises(ValidationError):
            EngineConfig.from_dict(raw)
