"""Regression coverage for workspace separation and Windows file locking."""
from contextlib import closing, redirect_stdout
from datetime import date, datetime, timedelta
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from oraculum.contracts import IST, ValidationError
from oraculum.local import main, parser
from oraculum.local_data import MarketStore
from oraculum.local_paths import data_directory, recover_market_cache
from oraculum.market_research import atomic_text


def fixture(day, price=100):
    return ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TtlTrfVal,SsnId\n"
            f"{day},{day},CM,NSE,STK,EXAMPLE,EQ,{price},{price+1},{price-1},{price},1000000,{price*1000000},F1\n").encode()


class WorkspaceRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = {"LOCALAPPDATA": str(self.root / "Local App Data")}

    def windows_directory(self, command, override=None):
        return data_directory(command, override, platform="nt", environment=self.environment)

    def test_default_commands_resolve_to_real_data_except_demo(self):
        expected = Path(self.environment["LOCALAPPDATA"]) / "Oraculum/data"
        for name in ("research", "serve", "doctor", "repair-local", "paper-status", "init"):
            args = parser().parse_args([name])
            self.assertEqual(self.windows_directory(args.command, args.data_dir), expected)
        args = parser().parse_args(["demo"])
        self.assertEqual(self.windows_directory(args.command, args.data_dir), expected.parent / "demo")

    def test_cli_research_and_viewer_use_same_actual_default(self):
        expected = self.windows_directory("research")
        with patch("oraculum.local.data_directory", side_effect=self.windows_directory), redirect_stdout(io.StringIO()):
            with patch("oraculum.market_research.run_research") as run:
                self.assertEqual(main(["research"]), 0)
                self.assertEqual(run.call_args.args[0], expected)
            with patch("oraculum.local.serve") as serve:
                self.assertEqual(main(["serve"]), 0)
                self.assertEqual(serve.call_args.args[0], expected / "runs.sqlite3")
            with patch("oraculum.local.persisted_demo") as demo:
                self.assertEqual(main(["demo"]), 0)
                self.assertEqual(demo.call_args.args[0], expected.parent / "demo")

    def test_explicit_path_wins_and_posix_defaults_stay_separate(self):
        explicit = self.root / "my chosen workspace"
        args = parser().parse_args(["research", "--data-dir", str(explicit)])
        self.assertEqual(self.windows_directory(args.command, args.data_dir), explicit)
        self.assertEqual(data_directory("research", platform="posix", project=self.root), self.root/"data/local")
        self.assertEqual(data_directory("demo", platform="posix", project=self.root), self.root/"data/demo")
        with self.assertRaisesRegex(ValidationError, "LOCALAPPDATA"):
            data_directory("research", platform="nt", environment={})

    def seed(self, folder, session, price=100, received=None):
        return MarketStore(folder/"market.sqlite3").ingest(fixture(session, price), session,
            "https://example.test/fixture.csv", received_at=received or datetime(2026, 10, 15, 18, tzinfo=IST))

    def test_repair_preserves_receipts_originals_and_target_and_ignores_demo_ledger(self):
        old, target = self.root/"old/data/demo", self.root/"new"
        first = self.seed(old, date(2026, 10, 14))
        second = self.seed(target, date(2026, 10, 15))
        (old/"paper.sqlite3").write_bytes(b"Synthetic ledger must stay here")
        original = (old/"market.sqlite3").read_bytes()
        result = recover_market_cache(target, [old], progress=lambda message: None)
        self.assertEqual(result["copied_sessions"], 1)
        self.assertEqual(MarketStore(target/"market.sqlite3").snapshots(), [first, second])
        self.assertEqual((old/"market.sqlite3").read_bytes(), original)
        self.assertFalse((target/"paper.sqlite3").exists())
        result = recover_market_cache(target, [old, old, target], progress=lambda message: None)
        self.assertEqual(result["copied_sessions"], 0)
        self.assertEqual(len(MarketStore(target/"market.sqlite3").snapshots()), 2)

    def test_two_old_caches_keep_earliest_receipt_for_same_file(self):
        a, b, target = self.root/"a", self.root/"b", self.root/"target"
        early = datetime(2026, 10, 14, 18, tzinfo=IST)
        first = self.seed(a, date(2026, 10, 14), received=early)
        self.seed(b, date(2026, 10, 14), received=early+timedelta(days=1))
        recover_market_cache(target, [b,a], progress=lambda message: None)
        self.assertEqual(MarketStore(target/"market.sqlite3").snapshots(), [first])

    def test_revision_conflict_does_not_overwrite_or_import_other_sessions(self):
        old, target = self.root/"old", self.root/"target"
        self.seed(old, date(2026, 10, 14))
        self.seed(old, date(2026, 10, 15), price=101)
        expected = self.seed(target, date(2026, 10, 15), price=100)
        with self.assertRaisesRegex(ValidationError, "conflict"):
            recover_market_cache(target, [old], progress=lambda message: None)
        self.assertEqual(MarketStore(target/"market.sqlite3").snapshots(), [expected])

    def test_corrupt_source_does_not_import_unverified_cache(self):
        old, target = self.root/"old", self.root/"target"
        self.seed(old, date(2026, 10, 14))
        with closing(sqlite3.connect(old/"market.sqlite3")) as conn, conn:
            conn.execute("DROP TRIGGER market_no_update")
            conn.execute("UPDATE market_snapshots SET raw=?", (b"corrupt",))
        with self.assertRaisesRegex(ValidationError, "integrity"):
            recover_market_cache(target, [old], progress=lambda message: None)
        self.assertFalse((target/"market.sqlite3").exists())

    def test_missing_old_cache_is_safe_and_reports_zero(self):
        result = recover_market_cache(self.root/"target", [self.root/"missing"], progress=lambda message: None)
        self.assertEqual(result["copied_sessions"], 0)
        self.assertEqual(result["source_caches"], [])

    def test_transient_replace_lock_retries_with_original_kept_until_success(self):
        target = self.root/"status.json"
        target.write_text("original")
        actual = Path.replace
        attempts = []
        def replace(source, destination):
            self.assertEqual(target.read_text(), "original")
            attempts.append(source)
            if len(attempts) < 3:
                raise PermissionError("simulated Windows handle lock")
            return actual(source, destination)
        with patch.object(Path, "replace", replace), patch("oraculum.market_research.time.sleep"):
            atomic_text(target, "complete new content")
        self.assertEqual(target.read_text(), "complete new content")
        self.assertEqual(len(attempts), 3)
        self.assertFalse(list(self.root.glob(".oraculum-*.tmp")))

    def test_permanent_lock_preserves_original_and_cleanup_does_not_mask_error(self):
        target = self.root/"latest.json"
        target.write_text("original")
        with patch.object(Path, "replace", side_effect=PermissionError("actual write failure")), \
                patch.object(Path, "unlink", side_effect=PermissionError("cleanup failure")), \
                patch("oraculum.market_research.time.sleep"):
            with self.assertRaisesRegex(PermissionError, "actual write failure"):
                atomic_text(target, "new")
        self.assertEqual(target.read_text(), "original")
