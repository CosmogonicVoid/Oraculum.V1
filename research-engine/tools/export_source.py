"""Create a GitHub-source ZIP without runtime data; Python standard library only."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("oraculum", "tests", "examples", "config", "docs", "handoffs", "tools", ".github")
FILES = ("README.md", "CHANGELOG.md", "pyproject.toml", ".gitignore", ".gitattributes",
         "run.cmd", "start.cmd", "demo.cmd", "research.cmd", "repair.cmd", "run-daily.cmd", "install-schedule.cmd", "remove-schedule.cmd", "ai-setup.cmd", "LICENSE", "LICENSE.md", "NOTICE", "COPYING")


def main():
    paths = [ROOT / name for name in FILES]
    for name in FOLDERS:
        paths.extend(p for p in (ROOT / name).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo"))
    # Only known source/config/document extensions. Do not export symlink targets.
    allowed = {".py", ".md", ".txt", ".json", ".csv", ".toml", ".yml", ".yaml", ".cmd", ".ps1"}
    paths = sorted(set(p for p in paths if p.is_file() and not p.is_symlink()
                       and (p.suffix in allowed or p.name in FILES)))
    target = ROOT / "dist/oraculum-source.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, "oraculum/" + path.relative_to(ROOT).as_posix())
    print(f"Wrote {target} ({len(paths)} source files; no runtime databases)")


if __name__ == "__main__":
    main()
