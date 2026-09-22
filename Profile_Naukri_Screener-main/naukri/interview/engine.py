"""The model call, behind one function, with two ways to reach a model.

    claude-cli   shell out to the `claude` CLI in print mode (default)
    anthropic    the Anthropic SDK, if ANTHROPIC_API_KEY is set

THE MODEL IS FIXED: Claude Opus 5 (`claude-opus-5`) at effort `high`, on both
transports. `--model` on the command line is refused unless it names that
model, and a CLI reply that reports having run on anything else is thrown
away. The preparation is a hundred technical answers you will study from; a
cheaper model's answers are not worth the study time.

THE LOGIN IS SEPARATE. The CLI is run with CLAUDE_CONFIG_DIR pointing at its
own folder (INTERVIEW_CONFIG_DIR, default %USERPROFILE%\.claude-interview),
so the preparation uses whichever Claude account is signed in THERE - the
organisation's Max plan - and never the personal Pro login that Claude Code
itself uses. Sign in once with

    login_interview_claude.bat        (= claude auth login, in that folder)

The SDK path exists for running this unattended from Task Scheduler, where a
CLI that wants to refresh its own auth is a worse bet than a key in the
environment. It is pinned to the same model and effort.

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

# The one model this module will generate with, and how hard it thinks.
REQUIRED_MODEL = "claude-opus-5"
EFFORT = "high"

# Where the CLI keeps the login used for the preparation - its own folder, so
# the account signed in here (the org's Max plan) is independent of the one
# Claude Code uses for coding.
INTERVIEW_CONFIG_DIR = os.environ.get("INTERVIEW_CLAUDE_CONFIG_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude-interview")


def check_model(model: str | None) -> str:
    """The model to send: REQUIRED_MODEL, or an error if something else was asked for."""
    if model and model.strip().lower() not in (REQUIRED_MODEL, "opus", "opus-5", "opus5"):
        raise EngineError(
            f"Interview preparation runs on {REQUIRED_MODEL} only (asked for {model!r}). "
            "Drop --model.")
    return REQUIRED_MODEL


def _cli_env() -> dict:
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = INTERVIEW_CONFIG_DIR
    # Never let the coding session's nesting guard or per-session model
    # choices leak into the preparation run.
    for key in ("CLAUDECODE", "ANTHROPIC_MODEL", "CLAUDE_CODE_EFFORT_LEVEL"):
        env.pop(key, None)
    return env


def cli_account() -> dict:
    """`claude auth status` for the preparation's own login folder.

    Returns the parsed JSON ({} when the CLI is missing or the output is not
    JSON). Raises EngineError when nobody is signed in there.
    """
    exe = _claude_cli()
    if not exe:
        return {}
    try:
        completed = subprocess.run([exe, "auth", "status"], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=60, env=_cli_env())
        status = json.loads(completed.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {}
    if not status.get("loggedIn"):
        raise EngineError(
            f"No Claude account is signed in for the interview preparation "
            f"(CLAUDE_CONFIG_DIR={INTERVIEW_CONFIG_DIR}).\n"
            "  Sign in once with the organisation account (the Max plan):\n"
            "      login_interview_claude.bat\n"
            "  This login is separate from the one Claude Code uses.")
    return status
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


def _cli_failure_text(stdout: str, stderr: str | None) -> str:
    """The human-readable part of a failed CLI run, for the log."""
    try:
        envelope = json.loads(stdout or "")
    except json.JSONDecodeError:
        envelope = None
    if isinstance(envelope, dict):
        for key in ("result", "error", "message"):
            if envelope.get(key):
                return str(envelope[key])[:400]
    text = (stderr or "").strip() or (stdout or "").strip()
    return text[:400] or "(no output)"


# A transient CLI failure - the login being refreshed, a rate limit, an
# overloaded API - costs a whole prep run when it lands on the first of seven
# calls. Try again after a pause before giving up.
#
# The ladder runs to ~17 minutes in total because the failure it exists for is
# the home connection dropping, and a two-minute ladder is shorter than a DNS
# blip: a run that had already spent twelve minutes and a dollar on the
# collective analysis died at "ENOTFOUND" with nothing to show for it. Waiting
# is free; re-running the whole prep is not.
CLI_RETRY_WAIT = (20, 45, 90, 180, 300, 420)
CLI_RETRIES = len(CLI_RETRY_WAIT)

# Failures that will never come right by waiting. Retrying these just makes a
# broken setup take a quarter of an hour to say so.
FATAL_CLI_MARKERS = ("is not on PATH", "not logged in", "invalid api key",
                     "authentication_error", "unauthorized", "no model to generate with")


def _is_fatal(message: str) -> bool:
    low = message.lower()
    return any(marker.lower() in low for marker in FATAL_CLI_MARKERS)


def _call_cli(prompt: str, timeout: int, model: str | None) -> tuple[str, dict]:
    last: EngineError | None = None
    for attempt in range(CLI_RETRIES + 1):
        try:
            return _call_cli_once(prompt, timeout, model)
        except EngineError as exc:
            last = exc
            if attempt >= CLI_RETRIES or _is_fatal(str(exc)):
                break
            wait = CLI_RETRY_WAIT[min(attempt, len(CLI_RETRY_WAIT) - 1)]
            log.warning("  claude CLI failed (%s) - retrying in %ds (attempt %d of %d)",
                        str(exc)[:200], wait, attempt + 2, CLI_RETRIES + 1)
            time.sleep(wait)
    raise last  # type: ignore[misc]


def _call_cli_once(prompt: str, timeout: int, model: str | None) -> tuple[str, dict]:
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
               "--strict-mcp-config",
               "--model", check_model(model),
               "--effort", EFFORT]

    try:
        completed = subprocess.run(
            command, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=_cli_env())
    except subprocess.TimeoutExpired:
        raise EngineError(f"claude CLI timed out after {timeout}s")

    raw = completed.stdout or ""
    if completed.returncode != 0:
        # A failed run still prints its JSON envelope; the message is in
        # "result" ("Not logged in", "rate limit", ...), well past the usage
        # counters that used to fill the 400 characters logged here.
        detail = _cli_failure_text(raw, completed.stderr)
        raise EngineError(f"claude CLI exited {completed.returncode}: {detail}")

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        # An older CLI, or one configured for text output. The body is the reply.
        return raw, {}

    if envelope.get("is_error"):
        raise EngineError(f"claude CLI reported an error: {str(envelope.get('result'))[:300]}")

    # The envelope names every model that produced tokens. Anything but the
    # required one means the CLI fell back (an alias resolving elsewhere, an
    # account without access) - and that reply is not used.
    used = [m for m, u in (envelope.get("modelUsage") or {}).items()
            if (u or {}).get("outputTokens") or (u or {}).get("inputTokens")]
    strangers = [m for m in used if REQUIRED_MODEL not in m]
    if strangers:
        raise EngineError(
            f"the reply came from {', '.join(strangers)}, not {REQUIRED_MODEL} - discarded. "
            f"Check the account signed in at {INTERVIEW_CONFIG_DIR} has Opus 5 access.")

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
    with client.messages.stream(
        model=check_model(model),
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()
    if message.model and REQUIRED_MODEL not in message.model:
        raise EngineError(f"the reply came from {message.model}, not {REQUIRED_MODEL} - discarded")
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

    model = check_model(model)
    if engine == "claude-cli" and not getattr(ask_json, "_account_logged", False):
        account = cli_account()
        if account:
            log.info("  [claude-cli] signed in as %s (%s, %s plan); model %s, effort %s",
                     account.get("email"), account.get("orgName"),
                     account.get("subscriptionType"), model, EFFORT)
            if str(account.get("subscriptionType") or "").lower() == "pro":
                log.warning("  the account at %s is a Pro plan, not the organisation's Max - "
                            "run login_interview_claude.bat to switch", INTERVIEW_CONFIG_DIR)
        ask_json._account_logged = True  # type: ignore[attr-defined]

    full = f"{prompt}\n\n{JSON_RULE}"
    attempt = 0
    while True:
        started = time.time()
        log.info("  [%s] %s ...", engine, label)
        text, meta = transport(full, timeout, model)
        meta = dict(meta, engine=engine, label=label, model=model, effort=EFFORT,
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
