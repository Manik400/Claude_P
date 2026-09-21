"""A free model that runs on this machine - the PC or a GitHub runner - no key, no API.

Two backends, whichever is there:

    ollama      an Ollama server already running on this machine (OLLAMA_HOST,
                default http://127.0.0.1:11434). Nothing to download here - it
                serves whatever you have pulled (`ollama pull qwen2.5:3b`), uses
                the GPU when it has one, and is preferred when it answers.
    llama-cpp   the bundled CPU fallback below, used when no Ollama server answers.

Two small open-weight models, both CPU-only, both downloaded once from
Hugging Face into LOCAL_AI_CACHE (default ~/.cache/jobbot-ai):

    LLM         unsloth/Qwen3.5-2B-GGUF : Qwen3.5-2B-Q4_K_M.gguf   (~1.3 GB)
                via llama-cpp-python (prebuilt CPU wheels; nothing to compile)
    embeddings  BAAI/bge-small-en-v1.5 via fastembed (ONNX, ~130 MB)

What they are used for (each caller degrades to today's behaviour when this
module reports unavailable, so nothing here is ever required):

    scoring.py / naukri score.py   a semantic resume<->job similarity term
    job_bot.py / naukri export.py  a one-line "why it fits / gap" for the top jobs
    naukri answers.py              screening answers, from your facts sheet only
    careers_bot.py                 a second opinion on relocation / visa wording

Nothing runs at import. `available()` only checks that the packages import;
the model files are fetched on first use (or by `--download`, which the
GitHub workflow runs behind actions/cache). Generation has a wall-clock
budget per process (LOCAL_AI_BUDGET_SECONDS) so a run inside a 45-minute
GitHub job stays inside it: when the budget is spent, `ask()` returns None
and the callers carry on without it.

    python -m jobbot.localai --status      what is installed, which model, budget
    python -m jobbot.localai --download    fetch the model files now
    python -m jobbot.localai --smoke       one embedding + one JSON answer, with timings

Environment (all optional; <repo>/.env is read through jobbot.dotenv):
    LOCAL_AI=0|1                     force off / on (default: on when a backend answers)
    LOCAL_AI_BACKEND=auto|ollama|llama   which backend to use (default auto: ollama first)
    OLLAMA_HOST=http://host:11434    where the Ollama server is
    OLLAMA_MODEL=<name>              which pulled model to use (default: first one the server lists,
                                     preferring qwen / llama / mistral / phi / gemma)
    LOCAL_AI_MODEL=<hf repo>:<file>  the GGUF (default above); e.g. unsloth/Qwen3.5-4B-GGUF:Qwen3.5-4B-Q4_K_M.gguf
    LOCAL_AI_EMBED_MODEL=<name>      fastembed model name (default BAAI/bge-small-en-v1.5)
    LOCAL_AI_CACHE=<dir>             where the files live
    LOCAL_AI_BUDGET_SECONDS=N        generation budget per process (default 600)
    LOCAL_AI_THREADS=N               default min(4, cpu_count)
    LOCAL_AI_CTX=N                   context window (default 4096)
    LOCAL_AI_SUMMARY_TOP=N           how many top jobs get the "why it fits" line (30)
    LOCAL_AI_RELOC_MAX=N             how many relocation second opinions per run (40)
    LOCAL_AI_ANSWER_MIN_CONFIDENCE   0..1, below which a screening answer is refused (0.8)
"""
from __future__ import annotations

import json as _json
import math
import os
import re
import sys
import time

if not __package__:
    # Run as a script (python jobbot/localai.py): its own folder is sys.path[0]
    # and holds jobbot/http.py, which would shadow the standard library's
    # `http` for huggingface_hub. Hand over to the package module instead.
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _here]
    sys.path.insert(0, os.path.dirname(_here))

try:
    from .dotenv import load_env as _load_env
except ImportError:  # run as a script from another directory
    _load_env = None
if _load_env:
    try:
        _load_env()
    except Exception:  # noqa: BLE001 - a bad .env must not break imports
        pass

try:
    import llama_cpp as _llama_cpp
    _HAVE_LLM = True
except Exception:  # noqa: BLE001 - ImportError, or a broken wheel
    _llama_cpp = None
    _HAVE_LLM = False

try:
    import fastembed as _fastembed
    _HAVE_EMBED = True
except Exception:  # noqa: BLE001
    _fastembed = None
    _HAVE_EMBED = False

try:
    from huggingface_hub import hf_hub_download as _hf_download
except Exception:  # noqa: BLE001
    _hf_download = None

DEFAULT_MODEL = "unsloth/Qwen3.5-2B-GGUF:Qwen3.5-2B-Q4_K_M.gguf"
# Bigger, for the PC (ai_setup.bat /big):
BIG_MODEL = "unsloth/Qwen3.5-4B-GGUF:Qwen3.5-4B-Q4_K_M.gguf"
# If the installed llama-cpp-python predates the Qwen 3.5 architecture:
FALLBACK_MODEL = "unsloth/Qwen3-1.7B-GGUF:Qwen3-1.7B-Q4_K_M.gguf"
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Qwen's "thinking" mode writes a long <think> block before the answer; that
# is wasted CPU time here and blows the token caps. /no_think switches it off,
# and the block is stripped anyway in case a model ignores the hint.
NO_THINK = "/no_think"
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


def _env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _int_env(name, default):
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


def _float_env(name, default):
    try:
        return float(_env(name, default))
    except (TypeError, ValueError):
        return default


def cache_dir() -> str:
    return _env("LOCAL_AI_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "jobbot-ai")


def model_spec() -> tuple[str, str]:
    """(hf repo id, filename) of the GGUF in use."""
    spec = _env("LOCAL_AI_MODEL", DEFAULT_MODEL)
    repo, _, name = spec.partition(":")
    if not name:
        raise ValueError("LOCAL_AI_MODEL must be '<hf repo>:<file.gguf>', got %r" % spec)
    return repo.strip(), name.strip()


def embed_model_name() -> str:
    return _env("LOCAL_AI_EMBED_MODEL", DEFAULT_EMBED_MODEL)


def threads() -> int:
    return _int_env("LOCAL_AI_THREADS", min(4, os.cpu_count() or 4))


# ----------------------------------------------------------------- ollama

OLLAMA_PREFERRED = ("qwen", "llama", "mistral", "phi", "gemma", "deepseek")
_ollama = {"checked": 0.0, "url": None, "model": None}


def ollama_url() -> str:
    url = (_env("OLLAMA_HOST") or "http://127.0.0.1:11434").strip().rstrip("/")
    return url if "://" in url else "http://" + url


def _pick_ollama_model(names):
    """The model to use: OLLAMA_MODEL when it is pulled, else the first familiar name."""
    want = (_env("OLLAMA_MODEL") or "").strip()
    if want:
        for n in names:
            if n == want or n.split(":")[0] == want.split(":")[0]:
                return n
        return want if names else None
    for family in OLLAMA_PREFERRED:
        for n in names:
            if n.lower().startswith(family) and "embed" not in n.lower():
                return n
    return next((n for n in names if "embed" not in n.lower()), None)


def ollama_ready(recheck_after: float = 60.0) -> bool:
    """Is an Ollama server answering, with a model to talk to? Cached for a minute.

    Never raises and never waits long: no server is the normal case, and every
    caller has a fallback.
    """
    if (_env("LOCAL_AI_BACKEND") or "auto").lower() == "llama":
        return False
    if _ollama["url"] and time.time() - _ollama["checked"] < recheck_after:
        return bool(_ollama["model"])
    _ollama["checked"] = time.time()
    _ollama["url"] = ollama_url()
    try:
        import requests
        r = requests.get(ollama_url() + "/api/tags", timeout=2.5)
        names = [m.get("name") or m.get("model") or "" for m in (r.json().get("models") or [])]
        _ollama["model"] = _pick_ollama_model([n for n in names if n])
    except Exception:  # noqa: BLE001 - not running, wrong port, no requests
        _ollama["model"] = None
    return bool(_ollama["model"])


def ollama_model() -> str | None:
    return _ollama["model"] if ollama_ready() else None


def _ask_ollama(prompt, system, max_tokens, json_mode, temperature, limit):
    """One /api/chat completion against the Ollama server. None when it cannot answer."""
    import requests
    body = {
        "model": _ollama["model"],
        "messages": [m for m in ({"role": "system", "content": system} if system else None,
                                 {"role": "user", "content": prompt}) if m],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        body["format"] = "json"
    started = time.time()
    ok = True
    try:
        r = requests.post(ollama_url() + "/api/chat", json=body, timeout=limit)
        r.raise_for_status()
        text = ((r.json().get("message") or {}).get("content")) or ""
    except Exception:  # noqa: BLE001 - timeout, server restarted, model pulled away
        ok, text = False, ""
    finally:
        _charge(time.time() - started, ok)
    if not ok:
        return None
    return extract_json(text) if json_mode else (_THINK_RE.sub("", text).strip() or None)



def _forced() -> str | None:
    v = (_env("LOCAL_AI") or "").strip().lower()
    if v in ("0", "off", "false", "no"):
        return "off"
    if v in ("1", "on", "true", "yes"):
        return "on"
    return None


def available(kind: str = "any") -> bool:
    """Whether the packages are installed (and LOCAL_AI is not 0). Never downloads."""
    if _forced() == "off":
        return False
    if kind == "llm":
        return ollama_ready() or (_HAVE_LLM and _hf_download is not None)
    if kind == "embed":
        return _HAVE_EMBED
    return available("llm") or _HAVE_EMBED


# ------------------------------------------------------------------ budget

_budget = {"spent": 0.0, "calls": 0, "failed": 0}


def budget_seconds() -> float:
    return _float_env("LOCAL_AI_BUDGET_SECONDS", 600.0)


def budget_left() -> float:
    return max(0.0, budget_seconds() - _budget["spent"])


def _charge(seconds: float, ok: bool) -> None:
    _budget["spent"] += max(0.0, seconds)
    _budget["calls"] += 1
    if not ok:
        _budget["failed"] += 1


def status() -> dict:
    repo, name = model_spec()
    path = model_path(download=False)
    return {
        "llm": available("llm"), "embed": available("embed"),
        "backend": "ollama" if ollama_ready() else ("llama-cpp" if (_HAVE_LLM and _hf_download is not None) else "off"),
        "ollama": ollama_model() or "", "ollama_host": ollama_url(),
        "model": ollama_model() or name, "repo": repo, "model_file": path, "downloaded": bool(path and os.path.exists(path)),
        "embed_model": embed_model_name(), "cache": cache_dir(), "threads": threads(),
        "budget": budget_seconds(), "budget_left": round(budget_left(), 1),
        "calls": _budget["calls"], "failed": _budget["failed"],
    }


def status_line() -> str:
    """One line for a run's log."""
    s = status()
    if not (s["llm"] or s["embed"]):
        return ("local AI: off (start Ollama and `ollama pull qwen2.5:3b`, run ai_setup.bat, "
                "or pip install -r job-hunt/requirements-ai.txt)")
    parts = []
    if s["ollama"]:
        parts.append("llm=%s via ollama" % s["ollama"])
    else:
        parts.append("llm=%s%s" % (s["model"], "" if s["downloaded"] else " (not downloaded yet)") if s["llm"] else "llm=off")
    parts.append("embed=%s" % s["embed_model"] if s["embed"] else "embed=off")
    parts.append("budget=%ds" % s["budget"])
    return "local AI: " + ", ".join(parts)


# ------------------------------------------------------------------ models

_llm_instance = None
_embedder_instance = None


def model_path(download: bool = True) -> str | None:
    """Local path of the GGUF; downloads it when asked and missing."""
    if _hf_download is None:
        return None
    repo, name = model_spec()
    root = cache_dir()
    # huggingface_hub lays the file out under the repo's own folder; look
    # for it there first so no network call happens when it is present.
    for base, _dirs, files in os.walk(root) if os.path.isdir(root) else []:
        if name in files and repo.replace("/", "--") in base:
            return os.path.join(base, name)
    if not download:
        return None
    os.makedirs(root, exist_ok=True)
    return _hf_download(repo_id=repo, filename=name, cache_dir=root)


def _llm():
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance
    if not available("llm"):
        return None
    path = model_path(download=True)
    if not path:
        return None
    _llm_instance = _llama_cpp.Llama(
        model_path=path, n_ctx=_int_env("LOCAL_AI_CTX", 4096), n_threads=threads(),
        n_batch=512, verbose=False)
    return _llm_instance


def _embedder():
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance
    if not available("embed"):
        return None
    os.makedirs(cache_dir(), exist_ok=True)
    _embedder_instance = _fastembed.TextEmbedding(
        model_name=embed_model_name(), cache_dir=cache_dir(), threads=threads())
    return _embedder_instance


def download(log=print) -> dict:
    """Fetch both model files now (the workflow runs this behind actions/cache)."""
    out = {"llm": None, "embed": None}
    if available("llm"):
        t = time.time()
        out["llm"] = model_path(download=True)
        log("local AI: LLM %s (%.0fs)" % (out["llm"], time.time() - t))
    if available("embed"):
        t = time.time()
        _embedder()
        out["embed"] = embed_model_name()
        log("local AI: embeddings %s ready (%.0fs)" % (out["embed"], time.time() - t))
    if not (out["llm"] or out["embed"]):
        log(status_line())
    return out


# --------------------------------------------------------------- embeddings

def embed(texts, *, batch_size: int = 32, max_chars: int = 1500):
    """Vectors for `texts` (plain lists of floats), or None when unavailable."""
    model = _embedder()
    if model is None or not texts:
        return None
    clipped = [(t or "")[:max_chars] for t in texts]
    try:
        return [[float(x) for x in v] for v in model.embed(clipped, batch_size=batch_size)]
    except Exception:  # noqa: BLE001 - a bad batch costs the term, not the run
        return None


def cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def chunk_text(text: str, size: int = 1200) -> list[str]:
    """Paragraph-bounded chunks of about `size` chars (bge-small reads 512 tokens)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z#*-])", text or "") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 1 > size:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n" + p) if cur else p
        while len(cur) > size * 1.5:
            chunks.append(cur[:size])
            cur = cur[size:]
    if cur:
        chunks.append(cur)
    return chunks or ([text[:size]] if text else [])


# Where bge-small cosines sit for "unrelated" and "same job": the term below
# is rescaled from that band to 0..1.
SEM_LOW, SEM_HIGH = 0.55, 0.85


def semantic_scores(reference_text: str, job_texts: list[str]) -> list[float] | None:
    """0..1 per job text against a reference (resume / profile), or None.

    The reference is chunked and every job is compared with all its chunks:
    half the best chunk (the section that matches), half the mean (the whole
    resume's relevance), rescaled from the model's typical cosine band.
    """
    if not available("embed") or not job_texts:
        return None
    ref_vecs = embed(chunk_text(reference_text))
    if not ref_vecs:
        return None
    job_vecs = embed(job_texts)
    if not job_vecs:
        return None
    out = []
    for jv in job_vecs:
        sims = [cosine(rv, jv) for rv in ref_vecs]
        raw = 0.5 * max(sims) + 0.5 * (sum(sims) / len(sims))
        out.append(max(0.0, min(1.0, (raw - SEM_LOW) / (SEM_HIGH - SEM_LOW))))
    return out


# ---------------------------------------------------------------- the LLM

def extract_json(text: str):
    """The JSON object in a reply, thinking block and prose stripped; None if none."""
    text = _THINK_RE.sub("", text or "")
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I | re.M)
    try:
        v = _json.loads(text)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            v = _json.loads(text[start:end + 1])
            return v if isinstance(v, dict) else None
        except ValueError:
            return None
    return None


def ask(prompt: str, *, system: str = "", max_tokens: int = 200, json: bool = False,
        schema: dict | None = None, temperature: float = 0.0, timeout: float | None = None):
    """One chat completion. Returns text, a dict (json=True), or None.

    None means: no model, budget spent, the call overran its time, or (json)
    the reply held no object. Callers treat None as "carry on without it".
    """
    if budget_left() <= 0:
        return None
    limit = min(timeout or 60.0, budget_left())
    sys_text = (NO_THINK + " " + system).strip()
    if ollama_ready():
        return _ask_ollama(prompt, sys_text, max_tokens, json, temperature, limit)
    llm = _llm()
    if llm is None:
        return None
    kwargs = dict(
        messages=[{"role": "system", "content": sys_text}, {"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=temperature, stream=True)
    if json:
        fmt = {"type": "json_object"}
        if schema:
            fmt["schema"] = schema
        kwargs["response_format"] = fmt
    started = time.time()
    pieces, ok, timed_out = [], True, False
    try:
        for chunk in llm.create_chat_completion(**kwargs):
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                pieces.append(delta["content"])
            if time.time() - started > limit:
                timed_out = True
                break
    except Exception:  # noqa: BLE001 - a grammar the model cannot satisfy, an OOM
        ok = False
    finally:
        _charge(time.time() - started, ok and not timed_out)
    if not ok:
        return None
    text = "".join(pieces)
    if timed_out and not json:
        return None
    if json:
        return extract_json(text)
    return _THINK_RE.sub("", text).strip() or None


# ------------------------------------------------------------ task helpers

def summarize_fit(resume_text: str, job_title: str, job_text: str,
                  matched: list[str] | None = None, missing: list[str] | None = None):
    """{"why": ..., "gaps": ...} for one job, or None."""
    if not available("llm") or budget_left() < 15:
        return None
    prompt = (
        "RESUME:\n%s\n\nJOB: %s\n%s\n\nMatched skills: %s\nMissing skills: %s\n\n"
        "Return JSON: {\"why\": \"<=25 words on why this candidate fits the job\", "
        "\"gaps\": \"<=20 words on the biggest gap, or 'none'\"}"
        % ((resume_text or "")[:3000], job_title or "", (job_text or "")[:2500],
           ", ".join(matched or []) or "-", ", ".join(missing or []) or "-"))
    out = ask(prompt, system="You compare a candidate's resume with a job posting. Reply with JSON only.",
              max_tokens=90, json=True,
              schema={"type": "object", "properties": {"why": {"type": "string"}, "gaps": {"type": "string"}},
                      "required": ["why", "gaps"]})
    if not out or not str(out.get("why", "")).strip():
        return None
    return {"why": str(out.get("why", "")).strip()[:240], "gaps": str(out.get("gaps", "")).strip()[:200]}


def answer_from_facts(question: str, options: list[str] | None, facts_sheet: str):
    """{"answer", "confidence", "basis"} from the facts sheet only, or None.

    The model is told to say UNKNOWN when the sheet does not hold the answer;
    the caller (naukri answers.py) verifies the basis and every number before
    anything is typed into a form.
    """
    if not available("llm"):
        return None
    prompt = (
        "FACTS:\n%s\n\nQUESTION: %s\nOPTIONS: %s\n\n"
        "Return JSON: {\"answer\": \"one of the options exactly, or a short value, or UNKNOWN\", "
        "\"confidence\": 0.0-1.0, \"basis\": \"the FACTS line you used\"}"
        % (facts_sheet, question, " | ".join(options) if options else "free text"))
    out = ask(prompt,
              system="You answer job-application screening questions ONLY from FACTS. If FACTS do not "
                     "contain the answer, set answer to \"UNKNOWN\". Never guess numbers.",
              max_tokens=80, json=True,
              schema={"type": "object",
                      "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"},
                                     "basis": {"type": "string"}},
                      "required": ["answer", "confidence", "basis"]})
    if not out:
        return None
    try:
        conf = float(out.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return {"answer": str(out.get("answer", "")).strip(), "confidence": conf,
            "basis": str(out.get("basis", "")).strip()}


def relocation_opinion(title: str, text: str):
    """{"relocation": yes|no|unclear, "visa": yes|no|unclear, "evidence_quote": ...} or None."""
    if not available("llm"):
        return None
    prompt = (
        "JOB: %s\n\nPOSTING EXCERPTS:\n%s\n\n"
        "Does the posting explicitly offer relocation support, and does it explicitly offer visa "
        "sponsorship? Answer only from the text. Return JSON: {\"relocation\": \"yes|no|unclear\", "
        "\"visa\": \"yes|no|unclear\", \"evidence_quote\": \"an exact sentence from the text, or empty\"}"
        % (title or "", (text or "")[:3000]))
    out = ask(prompt, system="You read a job posting and report only what it explicitly states. Quote exactly.",
              max_tokens=120, json=True,
              schema={"type": "object",
                      "properties": {"relocation": {"type": "string", "enum": ["yes", "no", "unclear"]},
                                     "visa": {"type": "string", "enum": ["yes", "no", "unclear"]},
                                     "evidence_quote": {"type": "string"}},
                      "required": ["relocation", "visa", "evidence_quote"]})
    if not out:
        return None
    return {"relocation": str(out.get("relocation", "unclear")).lower(),
            "visa": str(out.get("visa", "unclear")).lower(),
            "evidence_quote": str(out.get("evidence_quote", "")).strip()}


# ---------------------------------------------------------------------- CLI

def _smoke(log=print) -> int:
    log(status_line())
    rc = 0
    if available("embed"):
        t = time.time()
        vecs = embed(["python developer with selenium", "a recipe for lentil soup"])
        log("embed: %s in %.1fs" % (("%d x %d" % (len(vecs), len(vecs[0]))) if vecs else "FAILED", time.time() - t))
        if vecs:
            log("  cosine(dev, soup) = %.2f" % cosine(vecs[0], vecs[1]))
        else:
            rc = 1
    if available("llm"):
        t = time.time()
        try:
            out = answer_from_facts("What is your notice period?", ["1 month", "2 months", "3 months"],
                                    "notice_period_months: 2\ntotal_experience_years: 4")
        except Exception as exc:  # noqa: BLE001
            log("llm: FAILED to load/run %s: %s" % (model_spec()[1], str(exc)[:300]))
            log("  If the error names an unknown architecture, set LOCAL_AI_MODEL=%s" % FALLBACK_MODEL)
            return 1
        dt = time.time() - t
        log("llm: %s in %.1fs (%s)" % (out, dt, model_spec()[1]))
        if not out or "2" not in out.get("answer", ""):
            log("  unexpected answer - check the model")
            rc = 1
    return rc


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    if a.download:
        download()
    if a.smoke:
        return _smoke()
    if a.status or not (a.download or a.smoke):
        for k, v in status().items():
            print("%-12s %s" % (k, v))
        print(status_line())
    return 0


if __name__ == "__main__":
    if not __package__:
        from jobbot import localai as _self
        sys.exit(_self.main(sys.argv[1:]))
    sys.exit(main())
