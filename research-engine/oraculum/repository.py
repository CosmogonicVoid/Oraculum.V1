"""Append-only audit history. An administrator can still replace the database."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from .contracts import ValidationError
from .serialization import canonical_json, digest

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY, as_of TEXT NOT NULL, generated_at TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('synthetic', 'imported')),
    report_json TEXT NOT NULL, report_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_as_of ON research_runs(as_of DESC);
CREATE TRIGGER IF NOT EXISTS runs_no_update BEFORE UPDATE ON research_runs
BEGIN SELECT RAISE(ABORT, 'research runs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON research_runs
BEGIN SELECT RAISE(ABORT, 'research runs are immutable'); END;
PRAGMA user_version = 1;
"""


def _verify_identity(report: dict) -> None:
    identity = {k: report[k] for k in (
        "input_sha256", "config_sha256", "engine_version", "algorithm_version",
    )}
    if digest(identity) != report["run_id"]:
        raise ValidationError("Audit integrity error: run identity does not match")
    if digest(report["input"]) != report["input_sha256"]:
        raise ValidationError("Audit integrity error: input checksum does not match")
    if digest(report["config"]) != report["config_sha256"]:
        raise ValidationError("Audit integrity error: config checksum does not match")


class RunRepository:
    def __init__(self, path: str | Path, *, create: bool = True):
        self.path, self.read_only = Path(path), not create
        if not create:
            if not self.path.is_file():
                raise ValidationError(f"No run database at {self.path}; run demo or rank first")
            with self._connection() as connection:
                self._check_schema(connection)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            if version not in (0, 1) or (tables and "research_runs" not in tables):
                raise ValidationError("This is not a supported Oraculum database")
            connection.executescript(SCHEMA_SQL)
            self._check_schema(connection)

    @staticmethod
    def _check_schema(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValidationError("Unsupported Oraculum database version")
        columns = {r[1] for r in connection.execute("PRAGMA table_info(research_runs)")}
        if columns != {"run_id", "as_of", "generated_at", "mode", "report_json", "report_sha256"}:
            raise ValidationError("Unexpected Oraculum database schema")

    @contextmanager
    def _connection(self):
        connection = (sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
                      if self.read_only else sqlite3.connect(self.path, timeout=10))
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _decode(row: tuple) -> dict:
        try:
            report = json.loads(row[0])
            if digest(report) != row[1]:
                raise ValidationError("Audit integrity error: report checksum does not match")
            _verify_identity(report)
            return report
        except (ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError("Audit integrity error: malformed saved report") from exc

    def save(self, report: dict) -> dict:
        """Identical input/config/version returns the first saved report."""
        if self.read_only:
            raise ValidationError("Repository opened read-only")
        _verify_identity(report)
        with self._connection() as connection, connection:
            connection.execute(
                "INSERT INTO research_runs VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO NOTHING",
                (report["run_id"], report["as_of"], report["generated_at"], report["mode"],
                 canonical_json(report), digest(report)),
            )
            saved = self._decode(connection.execute(
                "SELECT report_json, report_sha256 FROM research_runs WHERE run_id = ?",
                (report["run_id"],),
            ).fetchone())
            new = {k: v for k, v in report.items() if k != "generated_at"}
            old = {k: v for k, v in saved.items() if k != "generated_at"}
            if digest(new) != digest(old):
                raise ValidationError("Identical run identity has different output; bump the engine version")
            return saved

    def get(self, run_id: str) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT report_json, report_sha256 FROM research_runs WHERE run_id = ?", (run_id,),
            ).fetchone()
        if row is None:
            raise ValidationError(f"Run not found: {run_id}")
        return self._decode(row)

    def history(self, limit: int = 20) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValidationError("History limit must be an integer from 1 to 1000")
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT report_json, report_sha256 FROM research_runs
                   ORDER BY as_of DESC, run_id ASC LIMIT ?""", (limit,),
            ).fetchall()
        return [{k: r[k] for k in ("run_id", "as_of", "mode", "dataset_id", "counts", "abstained")}
                for r in (self._decode(row) for row in rows)]
