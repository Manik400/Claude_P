"""Tests never call the local model: with it installed, every unmatched
screening question in the suite would cost a real generation. The tests
that exercise the model path patch naukri.localai explicitly.

Set per test rather than once at import. naukri.localai is a shim over
job-hunt's jobbot.localai, so an os.environ write here reaches the whole
pytest process - running both suites together then made job-hunt's own
"ollama answers" test fail, because this file had switched the model off
underneath it.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _no_local_model(monkeypatch):
    monkeypatch.setenv("LOCAL_AI", os.environ.get("LOCAL_AI", "0"))
