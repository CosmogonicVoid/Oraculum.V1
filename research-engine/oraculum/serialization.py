"""Canonical JSON for audit hashes, with strict loading and bounded input size."""

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import ValidationError

MAX_INPUT_BYTES = 16 * 1024 * 1024


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"JSON: duplicate field {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValidationError(f"JSON: non-finite number {value} is not permitted")


def load_json(path: str | Path) -> Any:
    with Path(path).open("rb") as handle:
        content = handle.read(MAX_INPUT_BYTES + 1)
    if len(content) > MAX_INPUT_BYTES:
        raise ValidationError(f"Input exceeds {MAX_INPUT_BYTES // 1024 // 1024} MiB")
    try:
        return json.loads(content.decode("utf-8-sig"), object_pairs_hook=_object, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValidationError(f"Invalid JSON in {Path(path).name}: {exc}") from exc
