"""Local-only CLI. No brokerage, AI-service or data-download calls."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .contracts import ValidationError, parse_bundle
from .demo import make_demo_bundle
from .pipeline import build_run
from .reporting import terminal_report, write_report
from .repository import RunRepository
from .serialization import digest, load_json

DEFAULT_DATABASE = "data/oraculum.sqlite3"


def _exports(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", help="Write full JSON report, including inputs and config")
    parser.add_argument("--markdown", help="Write a readable Markdown report")
    parser.add_argument("--force", action="store_true", help="Replace existing report files")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="oraculum", description="Oraculum paper-research core")
    root.add_argument("--version", action="version", version=f"Oraculum {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("demo", "rank"):
        p = commands.add_parser(name, help="Run fictional examples" if name == "demo" else "Rank a canonical JSON bundle")
        if name == "rank":
            p.add_argument("--input", required=True)
        p.add_argument("--config", help="Full JSON config; defaults are built in")
        p.add_argument("--database", default=DEFAULT_DATABASE)
        p.add_argument("--no-save", action="store_true", help="Calculate without writing run history")
        _exports(p)
    p = commands.add_parser("validate", help="Validate a canonical bundle without saving")
    p.add_argument("--input", required=True)
    p = commands.add_parser("history", help="List saved runs")
    p.add_argument("--database", default=DEFAULT_DATABASE)
    p.add_argument("--limit", type=int, default=20)
    for name in ("show", "replay"):
        p = commands.add_parser(name, help="Read a saved run" if name == "show" else "Recompute a saved run and verify its output")
        p.add_argument("run_id")
        p.add_argument("--database", default=DEFAULT_DATABASE)
        if name == "show":
            _exports(p)
    return root


def _check_paths(args: argparse.Namespace) -> None:
    outputs = [Path(p).resolve() for p in (getattr(args, "output", None), getattr(args, "markdown", None)) if p]
    protected = [Path(p).resolve() for p in (
        getattr(args, "input", None), getattr(args, "config", None), getattr(args, "database", None),
    ) if p]
    def same_file(left: Path, right: Path) -> bool:
        return left == right or (left.exists() and right.exists() and left.samefile(right))

    if (any(same_file(p, q) for index, p in enumerate(outputs) for q in outputs[index + 1:])
            or any(same_file(p, q) for p in outputs for q in protected)):
        raise ValidationError("Report paths must differ from each other and from input, config and database")
    for output in outputs:
        if output.exists() and not args.force:
            raise ValidationError(f"Report already exists: {output}; use --force to replace it")


def _write_outputs(report: dict, args: argparse.Namespace) -> None:
    if args.output:
        write_report(report, args.output, force=args.force)
    if args.markdown:
        write_report(report, args.markdown, markdown=True, force=args.force)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            bundle = parse_bundle(load_json(args.input))
            print(f"VALID: {len(bundle.assets)} instruments, {len(bundle.sources)} sources, mode={bundle.mode}")
            return 0
        if args.command in ("demo", "rank"):
            _check_paths(args)
            raw = make_demo_bundle() if args.command == "demo" else load_json(args.input)
            config = load_json(args.config) if args.config else None
            report = build_run(raw, config)
            if not args.no_save:
                report = RunRepository(args.database).save(report)
            _write_outputs(report, args)
            print(terminal_report(report))
            return 0
        repository = RunRepository(args.database, create=False)
        if args.command == "history":
            print(json.dumps(repository.history(args.limit), indent=2))
            return 0
        saved = repository.get(args.run_id)
        if args.command == "show":
            _check_paths(args)
            _write_outputs(saved, args)
            print(terminal_report(saved))
            return 0
        rebuilt = build_run(saved["input"], saved["config"])
        old = {k: v for k, v in saved.items() if k != "generated_at"}
        new = {k: v for k, v in rebuilt.items() if k != "generated_at"}
        if digest(old) != digest(new):
            raise ValidationError("REPLAY MISMATCH: code or algorithm version differs from the saved run")
        print(f"REPLAY VERIFIED: {saved['run_id']}")
        return 0
    except (ValidationError, OSError, sqlite3.Error) as exc:
        print(f"Oraculum error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
