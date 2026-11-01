"""Separate real/demo workspaces and preserve older price caches during repair."""
from contextlib import closing
import os
from pathlib import Path

from .contracts import ValidationError, day, timestamp
from .local_data import MarketStore

PROJECT = Path(__file__).resolve().parents[1]


def data_directory(command, override=None, *, platform=None, environment=None, project=None):
    if override is not None:
        return Path(override).expanduser()
    platform = os.name if platform is None else platform
    environment = os.environ if environment is None else environment
    project = PROJECT if project is None else Path(project)
    if platform == "nt":
        location = environment.get("LOCALAPPDATA")
        if not location:
            raise ValidationError("LOCALAPPDATA is unavailable. Supply --data-dir with a writable local folder.")
        base = Path(location) / "Oraculum"
        return base / ("demo" if command == "demo" else "data")
    return project / "data" / ("demo" if command == "demo" else "local")


def _records(path):
    store = MarketStore(path)
    if not store.path.is_file():
        return []
    with closing(store._connect()) as conn:
        return [(store._decode(row), row[2]) for row in conn.execute(
            "SELECT payload,payload_sha,raw FROM market_snapshots ORDER BY session")]


def recover_market_cache(target, sources, *, progress=print):
    """Copy verified raw snapshots, never synthetic ledgers, reports or settings.

    Reads originals without modifying them. Conflicts/corrupt snapshots are
    detected before ingestion. Existing target snapshots keep their receipt time.
    Repeating repair is safe, including after a partial copy was interrupted.
    """
    from .market_research import workflow_lock
    target = Path(target)
    destination = target / "market.sqlite3"
    with workflow_lock(target):
        existing = {p["session"]: p for p, raw in _records(destination)}
        pending, seen_paths, used_sources = {}, set(), []
        for folder in sources:
            source = Path(folder) / "market.sqlite3"
            resolved = source.resolve()
            if resolved == destination.resolve() or resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            if not source.is_file():
                continue
            records = _records(source)
            used_sources.append(str(source.resolve()))
            for payload, raw in records:
                session = payload["session"]
                previous = existing.get(session) or (pending[session][0] if session in pending else None)
                if previous and previous["sha256"] != payload["sha256"]:
                    raise ValidationError(f"Cache conflict for {session}; no files were replaced. Keep both caches for review.")
                if session in existing:
                    continue
                # Same immutable file in multiple old folders: preserve its first receipt.
                if (session not in pending or timestamp(payload["received_at"], "received_at") <
                        timestamp(pending[session][0]["received_at"], "received_at")):
                    pending[session] = payload, raw
        store = MarketStore(destination)
        for session, (payload, raw) in sorted(pending.items()):
            store.ingest(raw, day(session, "session"), payload["uri"],
                         received_at=timestamp(payload["received_at"], "received_at"))
        result = {"data_dir": str(target.resolve()), "copied_sessions": len(pending),
                  "existing_sessions": len(existing), "source_caches": used_sources}
        progress(f"Market workspace: {target.resolve()}")
        progress(f"Recovered {len(pending)} price sessions; {len(existing)} were already present. Original files were kept.")
        if not used_sources and not existing:
            progress("No old market cache was found here. Research will download the required files.")
        return result
