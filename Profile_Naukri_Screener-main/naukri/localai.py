"""The local model, shared with the worldwide search: job-hunt/scripts/jobbot/localai.py.

One implementation for both tools. This shim puts job-hunt's scripts folder on
the path and re-exports the API; when that checkout is missing (the screener
used on its own) every function is a no-op, and the screener behaves exactly
as it did before the model existed.
"""
from __future__ import annotations

import os
import sys

_JOBHUNT_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "job-hunt", "scripts")
if os.path.isdir(_JOBHUNT_SCRIPTS) and _JOBHUNT_SCRIPTS not in sys.path:
    sys.path.insert(0, _JOBHUNT_SCRIPTS)

try:
    from jobbot.localai import (  # noqa: F401
        PERSONAL_MODEL, answer_from_facts, available, budget_left, chunk_text, cosine, embed, ollama_model, personal_model,
        relocation_opinion, same_question, semantic_scores, status, status_line, summarize_fit, write_answer,
    )
except Exception:  # noqa: BLE001 - no job-hunt checkout next door: hard no-op
    PERSONAL_MODEL = "jobbot-answers"

    def available(kind="any"):
        return False

    def status():
        return {"llm": False, "embed": False}

    def status_line():
        return "local AI: off (job-hunt/scripts/jobbot/localai.py not found next to this tool)"

    def budget_left():
        return 0.0

    def embed(texts, **_kw):
        return None

    def cosine(a, b):
        return 0.0

    def chunk_text(text, size=1200):
        return [text] if text else []

    def semantic_scores(reference_text, job_texts):
        return None

    def summarize_fit(*_a, **_k):
        return None

    def answer_from_facts(*_a, **_k):
        return None

    def relocation_opinion(*_a, **_k):
        return None

    def same_question(*_a, **_k):
        return None

    def write_answer(*_a, **_k):
        return None

    def ollama_model():
        return None

    def personal_model():
        return None
