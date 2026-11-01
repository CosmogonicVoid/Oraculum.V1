"""Best-effort writer heartbeat; inspection is strictly read-only.

A recent heartbeat proves only that a writer thread was alive, not that its
network request or calculations made progress. SQLite still owns exclusion.
"""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import threading
import uuid

from .contracts import UTC, iso, timestamp
from .serialization import load_json

STALE_SECONDS = 90


@contextmanager
def heartbeat(folder, *, interval=10, clock=None):
    from .market_research import write_json

    clock = clock or (lambda: datetime.now(UTC))
    path = Path(folder) / "activity.json"
    record = {"id": uuid.uuid4().hex, "state": "active", "started_at": iso(clock())}
    stop = threading.Event()

    def emit(state):
        try:
            write_json(path, {**record, "state": state, "heartbeat_at": iso(clock())})
        except OSError:
            pass  # Optional telemetry cannot undo completed research.

    def tick():
        while not stop.wait(interval):
            emit("active")

    emit("active")
    worker = threading.Thread(target=tick, name="oraculum-heartbeat", daemon=True)
    worker.start()
    try:
        yield record
    finally:
        stop.set()
        worker.join()  # An atomic local write may still be finishing.
        emit("stopped")


def observed_status(folder, value, *, now=None):
    """Return a copy, never repair/delete status or acquire the writer lock."""
    if not value or value.get("state") != "running":
        return value
    result = dict(value)
    observation = {"state": "unknown", "heartbeat_at": None, "age_seconds": None}
    now = now or datetime.now(UTC)
    try:
        record = load_json(Path(folder) / "activity.json")
        if (
            isinstance(record, dict)
            and value.get("activity_id")
            and record.get("id") == value["activity_id"]
        ):
            age = (now - timestamp(record["heartbeat_at"], "heartbeat")).total_seconds()
            observation.update(
                heartbeat_at=record["heartbeat_at"], age_seconds=max(0, round(age))
            )
            if age < -5:
                observation["state"] = "clock_mismatch"
            elif record.get("state") == "stopped":
                observation["state"] = "stopped"
            elif record.get("state") == "active":
                observation["state"] = "active" if age <= STALE_SECONDS else "stale"
    except (OSError, ValueError, TypeError, KeyError):
        pass
    result["activity"] = observation
    return result


def activity_message(status, *, label="Research update"):
    state = status.get("activity", {}).get("state", "unknown")
    phase = status.get("phase", "preparing inputs")
    if state == "active":
        return f"{label} is active: {phase}. The heartbeat is recent; this does not guarantee download progress."
    if state == "stopped":
        return f"{label} stopped without a completion receipt. Check the terminal error, then rerun research.cmd to resume cached work."
    if state == "stale":
        return f"{label} has no recent heartbeat; completion is unconfirmed. Check the terminal before restarting. Cached work is preserved."
    return f"{label} has not recorded completion; live activity is unconfirmed. Check the terminal before restarting."
