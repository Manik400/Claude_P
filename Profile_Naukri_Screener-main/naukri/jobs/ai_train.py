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
# What goes into the model has to fit its context window WITH the facts sheet and the
# question being asked. Before 2026-11-11 the last 80 bank entries went in whole: one of
# them was a 3,302-option dropdown (105,000 characters), so the built prompt was ~30,000
# tokens against a 4,096-token window. Ollama then cut examples off the front on every
# call and still had to read a full window (about two minutes at 33 tokens/s here).
NUM_CTX = 4096                 # stated in the Modelfile so the budget below is what runs
MAX_EXAMPLE_CHARS = 400        # one question with its options; longer ones teach nothing
EXAMPLE_BUDGET_CHARS = 3000    # all examples together: with the MESSAGE wrappers and the
                               # facts sheet the built prompt is about 2,000 tokens, which
                               # leaves half the window for the question (answers.py sends
                               # the facts sheet again with it) and the reply
PLACEHOLDER_ANSWERS = {"free text", "n/a", "na", "none", "-", "."}


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
    lines.insert(2, f"PARAMETER num_ctx {NUM_CTX}")
    examples = select_examples(bank)
    for ask, answer in examples:
        lines += [f"MESSAGE user {_q(ask)}", f"MESSAGE assistant {_q(answer)}"]
    return "\n".join(lines) + "\n", len(examples)


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def select_examples(bank: list[dict]) -> list[tuple[str, str]]:
    """The (question, answer) pairs worth baking in, oldest first, inside the size budget.

    Left out, because each one teaches the model something wrong or costs more than it gives:
      - an answer that is not one of the question's own options (a "Yes" saved against a list
        of visa choices, a degree name against a list of degree levels): the form could never
        have taken it, so as an example it trains the model to answer off the list;
      - placeholder answers ("free text");
      - a question longer than MAX_EXAMPLE_CHARS with its options (country / university lists);
      - an older copy of a question that was answered again later (the latest answer wins).
    The newest answers are kept first until EXAMPLE_BUDGET_CHARS or MAX_EXAMPLES is reached.
    """
    picked, seen, spent = [], set(), 0
    for e in reversed(bank):
        question = str(e.get("question") or "").strip()
        answer = str(e.get("answer") or "").strip()
        options = [str(o).strip() for o in (e.get("options") or []) if str(o).strip()]
        if not question or not answer or _norm(answer) in PLACEHOLDER_ANSWERS:
            continue
        if options and _norm(answer) not in {_norm(o) for o in options}:
            continue
        ask = question + (("\nOPTIONS: " + " | ".join(options)) if options else "")
        size = len(ask) + len(answer)
        key = _norm(ask)
        if size > MAX_EXAMPLE_CHARS or key in seen:
            continue
        if spent + size > EXAMPLE_BUDGET_CHARS:
            continue  # a shorter, older one may still fit
        seen.add(key)
        picked.append((ask, answer))
        spent += size
        if len(picked) >= MAX_EXAMPLES:
            break
    picked.reverse()
    return picked


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
