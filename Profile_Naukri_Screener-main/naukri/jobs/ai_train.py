"""Your personal answer model for Ollama, rebuilt from what you have answered.

    python -m naukri.jobs.ai_train            rebuild now (`ollama create` when Ollama is installed)
    python -m naukri.jobs.ai_train --show     print the Modelfile it would build

Ollama does not fine-tune weights. What it can do is bake a system prompt and
example exchanges into a named model on top of one you pulled, and that is the
"training" here: your facts sheet becomes the system prompt, and every answer in
data/jobs/answer_bank.yaml - the ones you typed and the ones the local model gave
in forms that went through (questions.learn) - becomes an example exchange.
localai.ask(personal=True), used for screening answers and written answers, then
talks to `jobbot-answers`; everything else keeps the base model.

learning.learn() calls rebuild_if_changed() after every scan, so the model follows
your answer bank without anyone running this. Without Ollama (the llama-cpp
fallback) nothing is built; the same answers reach the model per question instead
(answers._examples), so the loop works either way.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

log = logging.getLogger("naukri.jobs.ai_train")

ROOT = Path(__file__).resolve().parent.parent.parent
MODELFILE = ROOT / "data" / "metrics" / "Modelfile"
STATE = ROOT / "data" / "metrics" / "personal_model.json"
MAX_EXAMPLES = 80


def _q(text: str) -> str:
    return '"""' + str(text).replace('"""', "'''") + '"""'


def modelfile(base: str) -> tuple[str, int]:
    """(Modelfile text, number of examples) from the facts sheet and the answer bank."""
    from . import answers, config as config_mod, questions
    profile = config_mod.load_profile()
    facts = answers.build_facts(profile, config_mod.load(profile=profile))
    system = ("You fill in job applications for one candidate. Answer only from these facts and from the "
              "candidate's earlier answers; when they do not hold the answer, say UNKNOWN. Never invent numbers.\n\n"
              "FACTS:\n" + facts["_facts_sheet"])
    lines = [f"FROM {base}", f"SYSTEM {_q(system)}", "PARAMETER temperature 0.1"]
    bank = [e for e in questions._read_list(questions.BANK_PATH)
            if str(e.get("answer") or "").strip() and str(e.get("answer")).strip().lower() != questions.SKIP]
    examples = bank[-MAX_EXAMPLES:]
    for e in examples:
        options = e.get("options") or []
        ask = e["question"] + (("\nOPTIONS: " + " | ".join(map(str, options))) if options else "")
        lines += [f"MESSAGE user {_q(ask)}", f"MESSAGE assistant {_q(e['answer'])}"]
    return "\n".join(lines) + "\n", len(examples)


def rebuild_if_changed(force: bool = False) -> dict:
    """Rebuild `jobbot-answers` when the facts or the bank changed since the last build."""
    try:
        from naukri import localai
    except Exception:  # noqa: BLE001
        return {"built": False, "why": "local AI module unavailable"}
    base = localai.ollama_model()
    if not base or not shutil.which("ollama"):
        return {"built": False, "why": "Ollama is not running here (the llama-cpp model gets your answers per question instead)"}
    text, n = modelfile(base)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not force and state.get("digest") == digest:
        return {"built": False, "why": "unchanged", **state}
    MODELFILE.parent.mkdir(parents=True, exist_ok=True)
    MODELFILE.write_text(text, encoding="utf-8")
    try:
        done = subprocess.run(["ollama", "create", localai.PERSONAL_MODEL, "-f", str(MODELFILE)],
                              capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"built": False, "why": f"ollama create failed: {exc}"}
    if done.returncode != 0:
        return {"built": False, "why": "ollama create failed: " + (done.stderr or done.stdout)[-300:]}
    state = {"digest": digest, "base": base, "examples": n, "built_at": datetime.now().isoformat(timespec="seconds")}
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    log.info("personal model rebuilt on %s with %d answer(s)", base, n)
    return {"built": True, **state}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true", help="print the Modelfile and exit")
    a = ap.parse_args(argv)
    if a.show:
        from naukri import localai
        print(modelfile(localai.ollama_model() or "<your pulled model>")[0])
        return 0
    print(rebuild_if_changed(force=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
