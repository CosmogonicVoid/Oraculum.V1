"""Persistent bounded retry policy for public filing collection."""

from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError

from .contracts import ValidationError, iso, timestamp
from .serialization import load_json


def read_attempts(path, now):
    records = load_json(path) if Path(path).is_file() else {}
    if not isinstance(records, dict):
        raise ValidationError(
            "Invalid filing-attempt state; preserve it and inspect before retrying"
        )
    active = {}
    for key, record in records.items():
        if not isinstance(record, dict):
            raise ValidationError("Invalid filing-attempt entry")
        at = timestamp(record.get("at"), "filing attempt")
        until = (
            timestamp(record["retry_at"], "retry time")
            if record.get("retry_at")
            else at + timedelta(days=1)
        )
        if (
            at > now + timedelta(minutes=5)
            or until < at
            or until > at + timedelta(days=8)
        ):
            raise ValidationError(
                "Filing retry clock is inconsistent; check the computer clock"
            )
        if until > now:
            active[key] = {**record, "retry_at": iso(until)}
    return active


def failure_record(exc, now):
    code = exc.code if isinstance(exc, HTTPError) else None
    if code in (401, 403, 429):
        category, delay = "provider_block", timedelta(days=1)
    elif isinstance(exc, ValidationError) or code in (400, 404, 410):
        category, delay = "document_review", timedelta(days=7)
    else:
        category, delay = "transient", timedelta(hours=1)
    return {
        "at": iso(now),
        "retry_at": iso(now + delay),
        "category": category,
        "error": str(exc)[:500],
    }


def provider_pause(records):
    blocked = [r for r in records.values() if r.get("category") == "provider_block"]
    return max((r["retry_at"] for r in blocked), default=None)
