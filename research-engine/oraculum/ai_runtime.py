"""Bounded Ollama transport, fixed to loopback and verified local weights."""

import http.client
import json
import re
import socket
import threading
import time
from .ai_contract import SYSTEM, model_schema, strict_json
from .ai_evidence import prompt_packet
from .contracts import ValidationError
from .serialization import digest

DEFAULT_MODEL = "qwen3.5:2b"
OPTIONS = {
    "temperature": 0,
    "seed": 7,
    "num_ctx": 8192,
    "num_predict": 600,
    "repeat_penalty": 1.0,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
}
MAX_RESPONSE = 1024 * 1024


def model_name(value):
    if (
        not isinstance(value, str)
        or len(value) > 160
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", value)
        or any(x in value.lower() for x in ("cloud", "://", "..", "@"))
        or value.count(":") > 1
    ):
        raise ValidationError(
            "Use an installed local Ollama model; cloud models and URLs are not allowed"
        )
    return value if ":" in value else value + ":latest"


def request(method, path, data=None, *, port=11434, timeout=20):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValidationError("Local model port must be between 1024 and 65535")
    if method not in ("GET", "POST") or path not in (
        "/api/tags",
        "/api/show",
        "/api/version",
        "/api/chat",
    ):
        raise ValidationError("Unsupported local model operation")
    if not 0 < timeout <= 600:
        raise ValidationError("Model timeout must be positive and at most 600 seconds")
    body = (
        None
        if data is None
        else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
    )
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    timer = response = None
    expired = threading.Event()
    started = time.monotonic()
    try:
        connection.connect()
        sock = connection.sock

        def cancel():
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

        timer = threading.Timer(
            max(0.001, timeout - (time.monotonic() - started)), cancel
        )
        timer.daemon = True
        timer.start()
        connection.request(
            method,
            path,
            body=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValidationError(
                f"Local Ollama returned HTTP {response.status}; no redirect or cloud fallback was attempted"
            )
        raw = response.read(MAX_RESPONSE + 1)
        if expired.is_set() or time.monotonic() - started > timeout:
            raise ValidationError("Local model exceeded its wall-clock deadline")
        if len(raw) > MAX_RESPONSE:
            raise ValidationError("Local model response is too large")
        result = strict_json(raw)
        if not isinstance(result, dict) or result.get("error"):
            raise ValidationError("Local model returned an invalid response")
        return result
    except (OSError, http.client.HTTPException, UnicodeError) as exc:
        raise ValidationError(
            "Local model request timed out"
            if expired.is_set() or isinstance(exc, TimeoutError)
            else "Cannot reach local Ollama; start it and run ai-doctor"
        ) from exc
    finally:
        if timer:
            timer.cancel()
        if response is not None:
            response.close()
        connection.close()


def preflight(model, *, port=11434, expected_digest=None, timeout=20, transport=None):
    transport = transport or request
    name = model_name(model)
    deadline = time.monotonic() + timeout

    def call(method, path, data=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValidationError("Model inspection timed out")
        return transport(method, path, data, port=port, timeout=remaining)

    listing = call("GET", "/api/tags").get("models")
    if not isinstance(listing, list) or any(not isinstance(m, dict) for m in listing):
        raise ValidationError("Invalid local model catalogue")
    installed = next(
        (m for m in listing if m.get("name") == name or m.get("model") == name), None
    )
    if installed is None:
        raise ValidationError(f"Local weights are missing. Run: ollama pull {name}")
    ident = str(installed.get("digest", "")).removeprefix("sha256:")
    if not re.fullmatch(r"[a-f0-9]{64}", ident):
        raise ValidationError("Model lacks a verifiable manifest digest")
    if expected_digest and expected_digest != ident:
        raise ValidationError("Model weights changed; run ai-configure and ai-evaluate")
    info = call("POST", "/api/show", {"model": name})
    if any(
        obj.get(k)
        for obj in (installed, info)
        for k in ("remote_host", "remote_model", "remote_url")
    ):
        raise ValidationError("Remote model aliases are not allowed")
    if (
        not isinstance(info.get("model_info"), dict)
        or not info["model_info"]
        or type(installed.get("size")) is not int
        or installed["size"] <= 0
    ):
        raise ValidationError("Model does not expose local weight metadata")
    version = call("GET", "/api/version")
    return {
        "name": name,
        "digest": ident,
        "size_bytes": installed["size"],
        "details": info.get("details", {}),
        "runtime_version": str(version.get("version", "unknown")),
        "model_info_sha256": digest(info["model_info"]),
    }


def generate(packet, config, model, *, timeout=None, transport=None):
    payload = {
        "model": model["name"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    prompt_packet(packet), ensure_ascii=False, separators=(",", ":")
                ),
            },
        ],
        "format": model_schema(packet),
        "stream": False,
        "think": False,
        "options": OPTIONS,
        "keep_alive": "2m",
    }
    result = (transport or request)(
        "POST",
        "/api/chat",
        payload,
        port=config["port"],
        timeout=timeout or config["timeout"],
    )
    if (
        result.get("done") is not True
        or result.get("done_reason") != "stop"
        or any(result.get(k) for k in ("remote_host", "remote_model", "remote_url"))
    ):
        raise ValidationError("Incomplete, truncated or remote output was rejected")
    if model_name(result.get("model")) != model["name"]:
        raise ValidationError("Response named a different model")
    message = result.get("message")
    if (
        not isinstance(message, dict)
        or message.get("tool_calls")
        or not isinstance(message.get("content"), str)
    ):
        raise ValidationError("Expected evidence selection, not tool calls")
    return {
        "raw": message["content"],
        "prompt_sha256": digest(payload),
        "stats": {
            k: result.get(k)
            for k in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "eval_count",
                "eval_duration",
            )
        },
    }
