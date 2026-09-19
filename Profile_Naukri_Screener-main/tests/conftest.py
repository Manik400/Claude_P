"""Tests never call the local model: with it installed, every unmatched
screening question in the suite would cost a real generation. The tests
that exercise the model path patch naukri.localai explicitly."""
import os

os.environ.setdefault("LOCAL_AI", "0")
