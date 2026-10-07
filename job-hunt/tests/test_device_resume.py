"""The resume stored per computer (jobbot.resume.device_*): outside the repo, replaced as a whole,
refused when unreadable or of the wrong type."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from jobbot import resume as R  # noqa: E402


@pytest.fixture
def device(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_DEVICE_DIR", str(tmp_path / "local"))
    return tmp_path


def test_empty_store(device):
    assert R.device_resume_path() is None and R.device_resume_info() is None
    R.clear_device_resume()          # nothing there: no error


def test_set_show_replace_clear(device):
    cv = device / "My CV.txt"
    cv.write_text("MANIK GOYAL\nBackend Software Engineer | Java, Kafka\n" + "Built things. " * 20, encoding="utf-8")
    dest = R.set_device_resume(str(cv))
    assert dest.endswith(os.path.join("JobHuntPhone", "resume", "current.txt")) and R.device_resume_path() == dest
    info = R.device_resume_info()
    assert info["name"] == "My CV.txt" and info["set_at"] and info["size"] == cv.stat().st_size
    assert "Backend Software Engineer" in R.extract_text(dest)
    # a new file of another type replaces it whole: one current.* at a time
    md = device / "new.md"
    md.write_text("# New resume\n\nPython developer " * 10, encoding="utf-8")
    R.set_device_resume(str(md))
    assert R.device_resume_path().endswith("current.md") and not os.path.exists(dest)
    R.clear_device_resume()
    assert R.device_resume_path() is None


def test_wrong_type_and_missing_are_refused(device):
    with pytest.raises(R.ResumeError):
        R.set_device_resume(str(device / "missing.pdf"))
    bad = device / "cv.exe"
    bad.write_bytes(b"x")
    with pytest.raises(R.ResumeError):
        R.set_device_resume(str(bad))
    assert R.device_resume_path() is None
