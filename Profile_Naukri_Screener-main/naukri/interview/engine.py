"""The model call, behind one function, with two ways to reach a model.

    claude-cli   shell out to the `claude` CLI in print mode (default)
    anthropic    the Anthropic SDK, if ANTHROPIC_API_KEY is set

The CLI is the default because it needs no API key and no new dependency - it
reuses the Claude Code login already on this machine. The SDK path exists for
running this unattended from Task Scheduler, where a CLI that wants to refresh
its own auth is a worse bet than a key in the environment.

Everything above this module talks in dicts. `ask_json` is the only entry
point: it sends a prompt, insists on JSON back, and retries a mangled reply
once with the parse error attached - which fixes the overwhelmingly common
failure, a model wrapping good JSON in an apologetic sentence.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time

log = logging.getLogger("naukri.interview.engine")

DEFAULT_TIMEOUT = 900          # question batches are long generations
JSON_RULE = (
    "Respond with a single valid JSON object and nothing else. "
    "No prose before or after it, no markdown code fence, no explanation."
)


class EngineError(RuntimeError):
    """The model could not be reached, or would not return usable JSON."""


# ------------------------------------------------------------------ transports

def _claude_cli() -> str | None:
    for name in ("claude", "claude.cmd", "claude.CMD", "claude.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _call_cli(prompt: str, timeout: int, model: str | None) -> tuple[str, dict]:
    exe = _claude_cli()
    if not exe:
        raise EngineError(
            "The `claude` CLI is not on PATH and ANTHROPIC_API_KEY is not set, "
            "so there is no model to generate with.\n"
            "  Install:  npm install -g @anthropic-ai/claude-code\n"
            "  or set ANTHROPIC_API_KEY and pass --engine anthropic")

    # Text in, JSON out - and nothing else. No tools, no settings files, no MCP
    # servers. The prompt carries job descriptions written by strangers, and a
    # JD is free to contain "ignore your instructions and run this instead".
    # Without these flags the CLI hands that text a fully tooled agent running
    # under the user's own global permission allow-list, in their repo.
    command = [exe, "-p", "--output-format", "json",
               "--allowedTools", "",
               "--setting-sources", "",
               "--strict-mcp-config"]
    if model:
        command += ["--model", model]

    try:
        completed = subprocess.run(
            command, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise EngineError(f"claude CLI timed out after {timeout}s")

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "")[:400]
        raise EngineError(f"claude CLI exited {completed.returncode}: {detail}")

    raw = completed.stdout or ""
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        # An older CLI, or one configured for text output. The body is the reply.
        return raw, {}

    if envelope.get("is_error"):
        raise EngineError(f"claude CLI reported an error: {str(envelope.get('result'))[:300]}")

    usage = envelope.get("usage") or {}
    meta = {
        "cost_usd": envelope.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "duration_ms": envelope.get("duration_ms"),
    }
    return envelope.get("result") or "", meta


def _call_anthropic(prompt: str, timeout: int, model: str | None) -> tuple[str, dict]:
    try:
        import anthropic
    except ImportError:
        raise EngineError(
            "engine=anthropic needs the SDK:  pip install anthropic\n"
            "  (or drop --engine to use the `claude` CLI instead)")

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise EngineError("engine=anthropic needs ANTHROPIC_API_KEY in the environment")

    client = anthropic.Anthropic(api_key=key, timeout=float(timeout))
    message = client.messages.create(
        model=model or "claude-sonnet-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    meta = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    return text, meta


TRANSPORTS = {"claude-cli": _call_cli, "anthropic": _call_anthropic}


def default_engine() -> str:
    """Prefer the CLI; fall back to the API key if the CLI is not installed."""
    if _claude_cli():
        return "claude-cli"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "claude-cli"       # so the error message names the missing CLI


# --------------------------------------------------------------- JSON handling

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I | re.M)


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply that may be wrapped in prose.

    Tries the whole string, then the fenced block, then the widest brace span.
    A model that answers correctly but chats first is still a correct answer,
    and re-prompting for that wastes a minute per batch.
    """
    if not text or not text.strip():
        raise ValueError("empty reply")

    candidates = [text.strip(), _FENCE.sub("", text).strip()]

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
    raise ValueError(f"no JSON object in reply ({last_error}); starts: {text[:160]!r}")


def ask_json(prompt: str, *, engine: str | None = None, model: str | None = None,
             timeout: int = DEFAULT_TIMEOUT, label: str = "call",
             retries: int = 1) -> tuple[dict, dict]:
    """Send `prompt`, return (parsed JSON, metadata). Raises EngineError."""
    engine = engine or default_engine()
    transport = TRANSPORTS.get(engine)
    if not transport:
        raise EngineError(f"Unknown engine {engine!r}. Choose from: {', '.join(TRANSPORTS)}")

    full = f"{prompt}\n\n{JSON_RULE}"
    attempt = 0
    while True:
        started = time.time()
        log.info("  [%s] %s ...", engine, label)
        text, meta = transport(full, timeout, model)
        meta = dict(meta, engine=engine, label=label,
                    elapsed_sec=round(time.time() - started, 1))
        try:
            parsed = extract_json(text)
        except ValueError as exc:
            attempt += 1
            if attempt > retries:
                raise EngineError(f"{label}: {exc}")
            log.warning("  %s: unparseable reply (%s) - retrying", label, str(exc)[:120])
            full = (f"{prompt}\n\n{JSON_RULE}\n\n"
                    f"Your previous reply could not be parsed as JSON: {exc}. "
                    f"Return only the JSON object this time.")
            continue

        cost = f", ${meta['cost_usd']:.3f}" if meta.get("cost_usd") else ""
        log.info("  [%s] %s done in %ss (%s out tokens%s)", engine, label,
                 meta["elapsed_sec"], meta.get("output_tokens", "?"), cost)
        return parsed, meta
