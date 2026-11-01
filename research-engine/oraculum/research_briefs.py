"""Explicit local setup, bounded generation and read-only saved research briefs."""

from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4
from .ai_contract import VERSION, assemble, contract_hash, validate_selection
from .ai_evidence import build_packet, verify_report
from .ai_runtime import DEFAULT_MODEL, OPTIONS, generate, model_name, preflight
from .ai_store import BriefStore
from .contracts import UTC, ValidationError, iso, timestamp
from .market_research import read_research, workflow_lock, write_json
from .serialization import digest, load_json


def cache_key(packet, model_digest):
    return digest(
        {
            "packet": packet["packet_id"],
            "model": model_digest,
            "contract": contract_hash(OPTIONS),
        }
    )


def load_config(folder):
    path = Path(folder) / "ai/config.json"
    if not path.is_file():
        return None
    config = load_json(path)
    if (
        not isinstance(config, dict)
        or config.get("schema") != "local-ai-v1"
        or type(config.get("enabled")) is not bool
    ):
        raise ValidationError("Invalid AI configuration; rerun ai-configure")
    model_name(config.get("model"))
    ident = config.get("model_digest")
    if (
        not isinstance(ident, str)
        or len(ident) != 64
        or any(c not in "0123456789abcdef" for c in ident)
    ):
        raise ValidationError("AI configuration lacks a pinned model digest")
    for key, low, high in (
        ("port", 1024, 65535),
        ("limit", 1, 20),
        ("timeout", 30, 600),
        ("budget", 60, 3600),
    ):
        if type(config.get(key)) is not int or not low <= config[key] <= high:
            raise ValidationError(f"AI {key} must be between {low} and {high}")
    return config


def configure(
    folder,
    *,
    model=DEFAULT_MODEL,
    port=11434,
    limit=3,
    timeout=600,
    budget=1800,
    inspector=None,
):
    for value, low, high in (
        (port, 1024, 65535),
        (limit, 1, 20),
        (timeout, 30, 600),
        (budget, 60, 3600),
    ):
        if type(value) is not int or not low <= value <= high:
            raise ValidationError("AI configuration limits are invalid")
    info = (inspector or preflight)(model, port=port)
    config = {
        "schema": "local-ai-v1",
        "enabled": True,
        "model": info["name"],
        "model_digest": info["digest"],
        "port": port,
        "limit": limit,
        "timeout": timeout,
        "budget": budget,
        "configured_at": iso(datetime.now(UTC)),
    }
    with workflow_lock(Path(folder) / "ai"):
        write_json(Path(folder) / "ai/config.json", config)
    return config


def disable(folder):
    config = load_config(folder)
    if config:
        with workflow_lock(Path(folder) / "ai"):
            config["enabled"] = False
            write_json(Path(folder) / "ai/config.json", config)
    return {"state": "disabled", "saved_briefs_preserved": True}


def status(folder, *, audit=False):
    folder = Path(folder)
    try:
        config = load_config(folder)
        path = folder / "ai/status.json"
        last = load_json(path) if path.is_file() else None
        path = folder / "ai/evaluations/latest.json"
        evaluation = load_json(path) if path.is_file() else None
        result = {
            "state": (
                "enabled"
                if config and config["enabled"]
                else "disabled" if config else "not_configured"
            ),
            "config": config,
            "last_batch": last,
            "evaluation": evaluation,
            "evaluation_current": bool(
                config
                and evaluation
                and evaluation.get("model", {}).get("digest") == config["model_digest"]
                and evaluation.get("contract_sha256") == contract_hash(OPTIONS)
            ),
            "affects_ranking": False,
            "affects_paper": False,
        }
        if audit:
            result["audit"] = BriefStore(folder).audit()
        return result
    except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
        return {"state": "unavailable", "config": None, "error": str(exc)[:800]}


def doctor(folder, *, model=None, port=None):
    config = load_config(folder)
    name = model or (config["model"] if config else DEFAULT_MODEL)
    port = port if port is not None else config["port"] if config else 11434
    result = {
        "endpoint": f"http://127.0.0.1:{port}",
        "ollama_cli_installed": shutil.which("ollama") is not None,
        "cloud_fallback": False,
    }
    try:
        result.update(
            state="ready",
            model=preflight(
                name,
                port=port,
                expected_digest=(
                    config["model_digest"]
                    if config and name == config["model"]
                    else None
                ),
            ),
        )
    except ValidationError as exc:
        result.update(state="unavailable", error=str(exc))
    return result


def select_assets(report, limit):
    def order(asset):
        combined = asset.get("combined", {})
        rank = combined.get("rank")
        return (
            0 if combined.get("highlight") else 1 if rank is not None else 2,
            rank if rank is not None else asset.get("rank") or 10**9,
            asset["symbol"],
        )

    return sorted(report["assets"], key=order)[:limit]


def run_briefs(
    folder,
    report=None,
    *,
    symbol=None,
    limit=None,
    retry=False,
    clock=None,
    progress=print,
    inspector=None,
    generator=None,
    monotonic=None,
):
    folder = Path(folder)
    clock = clock or (lambda: datetime.now(UTC))
    monotonic = monotonic or time.monotonic
    inspector, generator = inspector or preflight, generator or generate
    config = load_config(folder)
    if not config or not config["enabled"]:
        return {
            "state": "not_configured" if not config else "disabled",
            "message": "Evidence notebooks are available. Run ai-setup.cmd to enable local selection.",
        }
    report = report or read_research(folder)
    if not report:
        raise ValidationError("Run research.cmd before generating briefs")
    verify_report(report)
    if timestamp(report["as_of"], "cutoff") > clock():
        raise ValidationError("Cannot generate a brief for a future report")
    count = config["limit"] if limit is None else limit
    if type(count) is not int or not 1 <= count <= 20:
        raise ValidationError("Batch limit must be between 1 and 20")
    chosen = (
        [a for a in report["assets"] if a["symbol"] == symbol]
        if symbol
        else select_assets(report, count)
    )
    if symbol and not chosen:
        raise ValidationError("Stock is absent from this report")
    with workflow_lock(folder / "ai"):
        store, path, started = (
            BriefStore(folder),
            folder / "ai/status.json",
            monotonic(),
        )
        model, failures = None, 0
        state = {
            "state": "running",
            "report_id": report["report_id"],
            "started_at": iso(clock()),
            "requested": len(chosen),
            "accepted": 0,
            "cached": 0,
            "rejected": 0,
            "failed": 0,
            "pending": len(chosen),
            "results": [],
            "error": None,
        }
        write_json(path, state)
        try:
            for asset in chosen:
                remaining = config["budget"] - (monotonic() - started)
                if remaining < 5:
                    state["error"] = "Batch budget reached; rerun ai-refresh to resume."
                    break
                packet = build_packet(folder, report, asset["symbol"])
                key = cache_key(packet, config["model_digest"])
                saved = store.latest(cache_key=key)
                if saved and (saved["state"] == "accepted" or not retry):
                    label = "cached" if saved["state"] == "accepted" else saved["state"]
                    state[label] += 1
                    state["pending"] -= 1
                    state["results"].append(
                        {
                            "symbol": asset["symbol"],
                            "state": label,
                            "attempt_id": saved["attempt_id"],
                        }
                    )
                    write_json(path, state)
                    continue
                if model is None:
                    model = inspector(
                        config["model"],
                        port=config["port"],
                        expected_digest=config["model_digest"],
                        timeout=min(20, remaining),
                    )
                store.save_packet(packet)
                item = {
                    "attempt_id": uuid4().hex,
                    "state": "started",
                    "cache_key": key,
                    "packet_id": packet["packet_id"],
                    "report_id": report["report_id"],
                    "symbol": asset["symbol"],
                    "report_as_of": report["as_of"],
                    "started_at": iso(clock()),
                    "model": model,
                    "contract_version": VERSION,
                    "contract_sha256": contract_hash(OPTIONS),
                    "options": OPTIONS,
                    "affects_ranking": False,
                    "affects_paper": False,
                }
                store.record(item)
                progress(
                    "Local AI: " + asset["symbol"] + " — selecting captured evidence."
                )
                response = None
                try:
                    remaining = config["budget"] - (monotonic() - started)
                    if remaining < 2:
                        raise ValidationError(
                            "Batch deadline reached before generation"
                        )
                    response = generator(
                        packet, config, model, timeout=min(config["timeout"], remaining)
                    )
                    selection = validate_selection(response["raw"], packet)
                    remaining = config["budget"] - (monotonic() - started)
                    if remaining < 1:
                        raise ValidationError(
                            "Batch deadline reached before model verification"
                        )
                    after = inspector(
                        config["model"],
                        port=config["port"],
                        expected_digest=model["digest"],
                        timeout=min(20, remaining),
                    )
                    if after["digest"] != model["digest"]:
                        raise ValidationError("Model changed during generation")
                    item.update(
                        state="accepted",
                        selection=selection,
                        brief=assemble(selection, packet),
                        validation="references_and_roles_checked; interpretation_requires_review",
                    )
                    failures = 0
                except (ValueError, OSError, RuntimeError) as exc:
                    item.update(
                        state="rejected" if response is not None else "failed",
                        error=str(exc)[:800],
                    )
                    failures += 1
                if response is not None:
                    item.update(
                        raw_output=response.get("raw", "")[:16000],
                        prompt_sha256=response.get("prompt_sha256"),
                        stats=response.get("stats", {}),
                    )
                item["generated_at"] = iso(clock())
                store.record(item)
                state[item["state"]] += 1
                state["pending"] -= 1
                state["results"].append(
                    {
                        "symbol": asset["symbol"],
                        "state": item["state"],
                        "attempt_id": item["attempt_id"],
                        "error": item.get("error"),
                    }
                )
                write_json(path, state)
                progress(
                    "Local AI: "
                    + asset["symbol"]
                    + " — "
                    + item["state"]
                    + (
                        ": " + item["error"]
                        if item.get("error")
                        else " (selection and tone require review)."
                    )
                )
                if failures >= 2:
                    state["error"] = (
                        "Stopped after consecutive failures; inspect ai-status and use --retry after fixing the cause."
                    )
                    break
            state["state"] = (
                "partial"
                if state["pending"]
                else "needs_review" if state["failed"] or state["rejected"] else "ready"
            )
        except (Exception, KeyboardInterrupt) as exc:
            state.update(
                state=(
                    "interrupted"
                    if isinstance(exc, KeyboardInterrupt)
                    else "unavailable"
                ),
                error=str(exc)[:800] or type(exc).__name__,
            )
            if isinstance(exc, KeyboardInterrupt):
                raise
        finally:
            state.update(
                finished_at=iso(clock()),
                elapsed_seconds=round(monotonic() - started, 2),
            )
            write_json(path, state)
        return state


def read_brief(folder, report, symbol):
    verify_report(report)
    if not any(a["symbol"] == symbol for a in report["assets"]):
        raise ValidationError("Stock is absent from this report")
    try:
        store = BriefStore(folder)
        item = store.latest(report_id=report["report_id"], symbol=symbol)
        packet = (
            store.packet(item["packet_id"])
            if item
            else build_packet(folder, report, symbol)
        )
        config = load_config(folder)
        return {
            "packet": packet,
            "attempt": item,
            "current_configuration": bool(
                item
                and config
                and item["cache_key"] == cache_key(packet, config["model_digest"])
            ),
            "error": None,
        }
    except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
        return {
            "packet": build_packet(folder, report, symbol),
            "attempt": None,
            "current_configuration": False,
            "error": "Saved AI brief unavailable: " + str(exc)[:500],
        }
