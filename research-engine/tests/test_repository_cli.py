from contextlib import closing, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from oraculum.cli import main
from oraculum.contracts import ValidationError
from oraculum.demo import make_demo_bundle
from oraculum.pipeline import build_run
from oraculum.reporting import markdown_report
from oraculum.repository import RunRepository


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="oraculum test ")
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "runs.sqlite3"
        self.repo = RunRepository(self.db)
        self.report = build_run(make_demo_bundle())

    def test_save_and_get_preserve_complete_audit(self):
        self.repo.save(self.report)
        saved = self.repo.get(self.report["run_id"])
        self.assertEqual(saved["input"], self.report["input"])
        self.assertEqual(saved["config"], self.report["config"])
        self.assertEqual(saved["decisions"][0]["score"], 79)

    def test_repeated_runs_are_idempotent(self):
        first = self.repo.save(self.report)
        second = build_run(make_demo_bundle(), generated_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        saved = self.repo.save(second)
        self.assertEqual(saved["generated_at"], first["generated_at"])
        self.assertEqual(len(self.repo.history()), 1)

    def test_database_rejects_update_and_delete(self):
        self.repo.save(self.report)
        # A SQLite transaction context does not close the connection.
        # Close it explicitly before TemporaryDirectory cleanup on Windows.
        with closing(sqlite3.connect(self.db)) as connection, connection:
            for sql in ("UPDATE research_runs SET mode='imported'", "DELETE FROM research_runs"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    connection.execute(sql)

    def test_changed_output_under_same_version_rejected(self):
        self.repo.save(self.report)
        changed = deepcopy(self.report)
        changed["decisions"][0]["score"] = 100
        with self.assertRaisesRegex(ValidationError, "bump the engine version"):
            self.repo.save(changed)

    def test_input_tampering_rejected_before_save(self):
        self.report["input"]["dataset_id"] = "tampered"
        with self.assertRaisesRegex(ValidationError, "checksum"):
            self.repo.save(self.report)
        self.assertEqual(self.repo.history(), [])

    def test_stored_corruption_detected(self):
        self.repo.save(self.report)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DROP TRIGGER runs_no_update")
            connection.execute("UPDATE research_runs SET report_sha256 = 'bad'")
        with self.assertRaisesRegex(ValidationError, "checksum"):
            self.repo.get(self.report["run_id"])

    def test_sql_text_in_run_id_is_data(self):
        self.repo.save(self.report)
        with self.assertRaisesRegex(ValidationError, "Run not found"):
            self.repo.get("' OR 1=1 --")
        self.assertEqual(len(self.repo.history()), 1)

    def test_read_only_history_does_not_create_missing_database(self):
        missing = Path(self.tmp.name) / "missing.sqlite3"
        with self.assertRaises(ValidationError):
            RunRepository(missing, create=False)
        self.assertFalse(missing.exists())

    def test_unrelated_database_is_not_repurposed(self):
        other = Path(self.tmp.name) / "other.sqlite3"
        with closing(sqlite3.connect(other)) as connection, connection:
            connection.execute("CREATE TABLE personal_data (name TEXT)")
        with self.assertRaises(ValidationError):
            RunRepository(other)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="oraculum cli ")
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db = str(self.folder / "runs.sqlite3")

    def call(self, *args):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_demo_export_history_show_replay(self):
        output, markdown = self.folder / "report.json", self.folder / "report.md"
        code, out, err = self.call("demo", "--database", self.db, "--output", str(output),
                                  "--markdown", str(markdown))
        self.assertEqual(code, 0, err)
        self.assertIn("SYNTHETIC", out)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["counts"], {"candidate": 2, "watch": 2, "excluded": 4})
        self.assertIn("Sources", markdown.read_text(encoding="utf-8"))
        for command in ("show", "replay"):
            code, out, err = self.call(command, report["run_id"], "--database", self.db)
            self.assertEqual(code, 0, err)
        self.assertIn("REPLAY VERIFIED", out)
        code, out, err = self.call("history", "--database", self.db)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(json.loads(out)), 1)

    def test_rank_and_validate_canonical_input(self):
        source = self.folder / "input.json"
        source.write_text(json.dumps(make_demo_bundle()), encoding="utf-8")
        self.assertEqual(self.call("validate", "--input", str(source))[0], 0)
        self.assertEqual(self.call("rank", "--input", str(source), "--no-save")[0], 0)

    def test_no_save_leaves_no_database(self):
        self.assertEqual(self.call("demo", "--no-save", "--database", self.db)[0], 0)
        self.assertFalse(Path(self.db).exists())

    def test_output_cannot_overwrite_input_even_with_force(self):
        source = self.folder / "input.json"
        content = json.dumps(make_demo_bundle())
        source.write_text(content, encoding="utf-8")
        code, out, err = self.call("rank", "--input", str(source), "--output", str(source),
                                  "--force", "--no-save")
        self.assertEqual(code, 2)
        self.assertEqual(source.read_text(encoding="utf-8"), content)

    def test_existing_output_needs_explicit_force(self):
        output = self.folder / "report.json"
        output.write_text("keep", encoding="utf-8")
        self.assertEqual(self.call("demo", "--no-save", "--output", str(output))[0], 2)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.call("demo", "--no-save", "--output", str(output), "--force")[0], 0)

    def test_invalid_input_returns_clean_error(self):
        source = self.folder / "bad.json"
        source.write_text("not JSON", encoding="utf-8")
        code, out, err = self.call("rank", "--input", str(source), "--no-save")
        self.assertEqual(code, 2)
        self.assertIn("Oraculum error", err)
        self.assertNotIn("Traceback", err)

    def test_markdown_contains_traceable_factor_sources(self):
        text = markdown_report(build_run(make_demo_bundle()))
        self.assertIn("demo-news", text)
        self.assertIn("Missing or stale factors", text)
