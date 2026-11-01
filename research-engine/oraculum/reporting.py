"""Plain terminal, Markdown and full machine-readable reports."""

import json
from pathlib import Path
from .contracts import ValidationError


def terminal_report(report: dict) -> str:
    lines = [
        f"ORACULUM | {report['mode'].upper()} | {report['as_of']}",
        "Unvalidated baseline score / 100. Paper research only.",
        f"Run: {report['run_id']}", "",
        f"{'INSTRUMENT':<25} {'STATUS':<10} {'SCORE':>7} {'COVERAGE':>10}",
    ]
    for d in report["decisions"]:
        lines.append(f"{d['instrument_id']:<25} {d['status']:<10} {d['score']:>7.2f} {d['coverage']:>9.0%}")
    lines.extend(["", "Shortlist: " + (", ".join(report["shortlist"]) or "NONE - the engine abstained.")])
    for d in report["decisions"]:
        lines.append(f"\n{d['instrument_id']}")
        lines.extend(f"  + {s}" for s in d["reasons"])
        lines.extend(f"  ! {s}" for s in d["counterarguments"])
    return "\n".join(lines)


def _md(value: str) -> str:
    for ch in ("\\", chr(96), "*", "_", "[", "]", "<", ">", "|"):
        value = value.replace(ch, "\\" + ch)
    return value


def markdown_report(report: dict) -> str:
    lines = [
        "# Oraculum research report", "",
        f"Mode: **{report['mode']}** · As of: {report['as_of']}", "",
        "**Unvalidated baseline. Scores are neither return forecasts nor probabilities.**",
        "", f"Run ID: {report['run_id']}", "",
        "| Instrument | Status | Score | Coverage |", "| --- | --- | ---: | ---: |",
    ]
    for d in report["decisions"]:
        lines.append(f"| {_md(d['instrument_id'])} | {d['status']} | {d['score']:.2f} | {d['coverage']:.0%} |")
    lines.extend(["", "Shortlist: " + (", ".join(map(_md, report["shortlist"])) or "**None; engine abstained.**")])
    for d in report["decisions"]:
        lines.extend(["", f"## {_md(d['instrument_id'])}", ""])
        lines.extend(f"- Supporting: {_md(s)}" for s in d["reasons"])
        lines.extend(f"- Counterargument / blocker: {_md(s)}" for s in d["counterarguments"])
        lines.extend(f"- Data issue: {_md(s)}" for s in d["warnings"])
        lines.extend(["", "| Factor | Weight | Normalized | Points | Sources |",
                      "| --- | ---: | ---: | ---: | --- |"])
        for f in d["factors"]:
            n = "missing" if f["normalized"] is None else f"{f['normalized']:.4f}"
            lines.append(f"| {f['factor']} | {f['weight']:.2f} | {n} | {f['points']:+.2f} | "
                         + ", ".join(map(_md, f["source_ids"])) + " |")
    lines.extend(["", "## Sources", ""])
    for s in report["input"]["sources"]:
        lines.append(f"- **{_md(s['id'])}**: {_md(s['title'])}; available {s['available_at']}; {_md(s['uri'])}")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {s}" for s in report["limitations"])
    return "\n".join(lines) + "\n"


def write_report(report: dict, path: str | Path, *, markdown: bool = False, force: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (markdown_report(report) if markdown else
               json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n")
    try:
        with target.open("w" if force else "x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ValidationError(f"Report already exists: {target}; use --force to replace it") from exc
