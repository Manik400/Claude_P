"""The local model is optional: without it nothing changes; with it, only
verified, grounded output is used. The smoke test at the end needs the
model files and is skipped otherwise."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from jobbot import localai  # noqa: E402
from jobbot.careers import relocation  # noqa: E402
from jobbot.models import Job  # noqa: E402
from jobbot.scoring import score_jobs  # noqa: E402

RESUME = ("Senior QA automation engineer. 5 years with Python, Selenium, Playwright, pytest, "
          "REST API testing, CI/CD with Jenkins and GitHub Actions, Docker. Led a team of three.")


def _jobs():
    return [
        Job(source="x", source_name="X", title="SDET - Python / Playwright", company="A", url="u1", country="IN",
            description="Automation with Python, Playwright and pytest for a fintech product. CI on Jenkins. " * 8),
        Job(source="x", source_name="X", title="Pastry Chef", company="B", url="u2", country="IN",
            description="Croissants, sourdough and cakes for a busy bakery. Early shifts. " * 8),
    ]


def test_absent_means_off(monkeypatch):
    monkeypatch.setattr(localai, "_HAVE_LLM", False)
    monkeypatch.setattr(localai, "_HAVE_EMBED", False)
    assert not localai.available()
    assert not localai.available("llm")
    assert localai.embed(["a"]) is None
    assert localai.ask("hi") is None
    assert localai.summarize_fit(RESUME, "t", "d") is None
    assert localai.answer_from_facts("q", [], "a: 1") is None
    assert localai.relocation_opinion("t", "d") is None
    assert "off" in localai.status_line()


def test_local_ai_env_switch(monkeypatch):
    monkeypatch.setenv("LOCAL_AI", "0")
    assert not localai.available()


def test_scores_identical_without_model(monkeypatch):
    monkeypatch.setattr(localai, "_HAVE_EMBED", False)
    a, b = _jobs(), _jobs()
    score_jobs(a, RESUME)               # ai=None -> localai, which is unavailable
    score_jobs(b, RESUME, ai=False)     # explicitly off
    assert [j.score for j in a] == [j.score for j in b]
    assert all("semantic" not in j.extra for j in a)
    assert a[0].score > a[1].score


def test_semantic_term_blends_in(monkeypatch):
    class FakeAI:
        @staticmethod
        def available(kind="any"):
            return True

        @staticmethod
        def semantic_scores(reference, texts):
            return [1.0, 0.0]

    plain = _jobs()
    score_jobs(plain, RESUME, ai=False)
    withai = _jobs()
    info = score_jobs(withai, RESUME, ai=FakeAI)
    assert info["semantic"] is True
    assert withai[0].extra["semantic"] == 1.0 and withai[1].extra["semantic"] == 0.0
    assert withai[0].score >= plain[0].score          # the matching job gains
    assert withai[1].score <= plain[1].score          # the bakery loses
    assert all(0 <= j.score <= 100 for j in withai)


def test_extract_json_strips_thinking_and_prose():
    assert localai.extract_json('<think>hmm</think>Sure: {"a": 1}') == {"a": 1}
    assert localai.extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert localai.extract_json("no json here") is None
    assert localai.extract_json("[1, 2]") is None


def test_chunk_text_respects_size():
    text = "\n\n".join("paragraph %d " % i * 30 for i in range(12))
    chunks = localai.chunk_text(text, size=600)
    assert len(chunks) > 1
    assert all(len(c) <= 900 for c in chunks)
    assert localai.chunk_text("") == []


TEXT = ("We are hiring in Berlin. We help you and your family relocate and cover the visa process. "
        "Hybrid, three days on site.")


def test_merge_opinion_requires_a_real_quote():
    reloc = {"label": "maybe", "relocation": "mixed", "visa": "unknown", "evidence": ""}
    invented = {"relocation": "yes", "visa": "yes", "evidence_quote": "Full relocation package provided."}
    assert relocation.merge_opinion(reloc, invented, TEXT)["label"] == "maybe"
    real = {"relocation": "yes", "visa": "yes",
            "evidence_quote": "We help you and your family relocate and cover the visa process."}
    out = relocation.merge_opinion(reloc, real, TEXT)
    assert out["label"] == "yes" and out["source"] == "local-ai" and out["evidence"]


def test_merge_opinion_never_downgrades_yes():
    reloc = {"label": "yes", "relocation": "yes", "visa": "unknown", "evidence": "x"}
    no = {"relocation": "no", "visa": "no", "evidence_quote": "Hybrid, three days on site."}
    assert relocation.merge_opinion(reloc, no, TEXT) is reloc


def test_merge_opinion_unknown_to_visa_and_no():
    unknown = {"label": "unknown", "relocation": "unknown", "visa": "unknown", "evidence": ""}
    visa = {"relocation": "unclear", "visa": "yes", "evidence_quote": "cover the visa process"}
    assert relocation.merge_opinion(unknown, visa, TEXT)["label"] == "visa"
    both_no = {"relocation": "no", "visa": "no", "evidence_quote": "Hybrid, three days on site."}
    assert relocation.merge_opinion(unknown, both_no, TEXT)["label"] == "no"


def test_excerpt_keeps_relocation_sentences():
    ex = relocation.excerpt_for_model("t", "Boring intro. " * 100 + TEXT)
    assert "relocate" in ex and len(ex) <= 3000


# --------------------------------------------------------------- smoke

_model_present = localai.available("llm") and bool(localai.model_path(download=False))


@pytest.mark.skipif(not _model_present, reason="local model not downloaded (run ai_setup.bat)")
def test_smoke_answer_from_facts():
    out = localai.answer_from_facts("What is your notice period?", ["1 month", "2 months", "3 months"],
                                    "notice_period_months: 2\ntotal_experience_years: 4")
    assert out and "2" in out["answer"]


@pytest.mark.skipif(not localai.available("embed"), reason="fastembed not installed")
def test_smoke_embed():
    vecs = localai.embed(["python developer", "python developer with selenium", "lentil soup recipe"])
    assert vecs and len(vecs) == 3 and len(vecs[0]) >= 256
    assert localai.cosine(vecs[0], vecs[1]) > localai.cosine(vecs[0], vecs[2])
