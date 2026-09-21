"""A stale slug must cost a company nothing: the row is re-resolved, and only a board that
answers *and* belongs to that company is accepted. Nothing here touches the network."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from jobbot.careers import resolve  # noqa: E402
from jobbot.careers.ats import Unresolved, fetch  # noqa: E402
from jobbot.careers.companies import Company, load  # noqa: E402


# ---------------------------------------------------------------- URL -> board

@pytest.mark.parametrize("url, want", [
    ("https://job-boards.greenhouse.io/agoda", ("greenhouse", "agoda")),
    ("https://boards.eu.greenhouse.io/adyen", ("greenhouse", "adyen")),
    ("https://boards.greenhouse.io/embed/job_board?for=stripe", ("greenhouse", "stripe")),
    ("https://jobs.lever.co/binance", ("lever", "binance")),
    ("https://jobs.ashbyhq.com/openai", ("ashby", "openai")),
    ("https://jobs.smartrecruiters.com/grab", ("smartrecruiters", "grab")),
    ("https://apply.workable.com/huggingface", ("workable", "huggingface")),
    ("https://bunq.recruitee.com", ("recruitee", "bunq")),
    ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
     ("workday", "nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite")),
    ("https://micron.wd1.myworkdayjobs.com/External/job/Hyderabad/SDET_JR-1",
     ("workday", "micron.wd1.myworkdayjobs.com/micron/External")),
    ("https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs",
     ("workday", "cisco.wd5.myworkdayjobs.com/cisco/Cisco_Careers")),
    ("https://dbs.wd3.myworkdayjobs.com/en-US/dbs/Dbs_Careers",
     ("workday", "dbs.wd3.myworkdayjobs.com/dbs/Dbs_Careers")),
    ("https://www.metacareers.com/", (None, None)),
    ("", (None, None)),
])
def test_from_url(url, want):
    assert resolve.from_url(url) == want


def test_slug_variants_drops_suffixes_and_keeps_the_host():
    v = resolve.slug_variants("Weights & Biases Inc", "https://wandb.ai/site/careers")
    assert "weightsbiases" in v and "weights-biases" in v and "wandb" in v


# --------------------------------------------------------- whose board is it?

@pytest.mark.parametrize("name, board_owner, want", [
    ("Meta", "Addis Ababa University", False),
    ("Hugging Face", "Hugging Face", True),
    ("Zomato / Eternal", "Eternal Limited", True),
    ("Agoda", "Agoda Services Co., Ltd.", True),
    ("Personio", "FD Sandbox", False),
    ("Anything", "", None),          # the board does not say - undecided, not a rejection
])
def test_same_company(name, board_owner, want):
    assert resolve.same_company(name, board_owner) is want


# ------------------------------------------------------------- the file itself

def _write(tmp_path, text):
    p = tmp_path / "companies.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_a_board_link_wins_over_the_columns(tmp_path):
    path = _write(tmp_path, "OpenAI | greenhouse | openai | https://jobs.ashbyhq.com/openai | San Francisco\n")
    c = load(path)[0]
    assert (c.ats, c.board) == ("ashby", "openai")
    assert c.note == "San Francisco"


def test_an_unreadable_row_is_kept_for_resolving_not_dropped(tmp_path):
    path = _write(tmp_path, "Rakuten | official | rakuten | https://rakuten.careers/\n"
                            "Tesla   | workday  | tesla   | Austin\n")
    rows = load(path)
    assert [c.name for c in rows] == ["Rakuten", "Tesla"]
    assert all(not c.readable for c in rows)
    assert rows[0].url == "https://rakuten.careers/"
    assert rows[1].ats == "workday"          # the ats stays as a hint, the unusable board does not


def test_duplicates_merge_into_the_row_that_knows_more(tmp_path):
    path = _write(tmp_path, "Spotify | greenhouse | spotify | Stockholm\n"
                            "Spotify | lever      | spotify | https://www.lifeatspotify.com/ | London\n")
    rows = load(path)
    assert len(rows) == 1
    assert rows[0].url == "https://www.lifeatspotify.com/"
    assert "London" in rows[0].note and "Stockholm" in rows[0].note


# ------------------------------------------------------------ the fallback path

class FakeHttp:
    """Answers only for the boards in `boards`; everything else 404s like the real thing."""

    def __init__(self, boards, owners=None):
        self.boards, self.owners, self.calls = boards, owners or {}, []

    def _find(self, url):
        self.calls.append(url)
        for (ats, board), n in self.boards.items():
            if board in url and _host_of(ats) in url:
                return ats, board, n
        return None

    def get_json(self, url, params=None, **kw):
        hit = self._find(url)
        if not hit:
            raise RuntimeError("404 Client Error: Not Found for url: " + url)
        ats, board, n = hit
        if ats == "lever":                       # lever answers with a bare list of postings
            return [{"text": "Engineer"}] * n
        if ats == "greenhouse" and url.rstrip("/").endswith(board):
            return {"name": self.owners.get(board, "")}
        return {"jobs": [{"title": "Engineer"}] * n, "offers": [{"company_name": self.owners.get(board, "")}] * n,
                "totalFound": n, "content": [{"company": {"name": self.owners.get(board, "")}}]}

    def get(self, url, **kw):
        raise RuntimeError("no page")

    def post(self, url, json=None, **kw):
        raise RuntimeError("404")


def _host_of(ats):
    return {"greenhouse": "greenhouse.io", "ashby": "ashbyhq.com", "lever": "lever.co",
            "smartrecruiters": "smartrecruiters.com", "workable": "workable.com",
            "recruitee": "recruitee.com"}[ats]


def test_a_dead_slug_is_re_resolved_by_name():
    http = FakeHttp({("ashby", "openai"): 3}, owners={"openai": "OpenAI"})
    hit = resolve.resolve(http, "OpenAI", use_ai=False, hint_ats="greenhouse", hint_board="openai")
    assert (hit["ats"], hit["board"], hit["jobs"]) == ("ashby", "openai", 3)
    assert hit["via"].startswith("name")


def test_a_board_belonging_to_someone_else_is_refused():
    http = FakeHttp({("recruitee", "meta"): 1}, owners={"meta": "Addis Ababa University"})
    hit = resolve.resolve(http, "Meta", url="https://www.metacareers.com/", use_ai=False)
    assert hit["ats"] == ""
    assert hit["url"] == "https://www.metacareers.com/"      # the row still carries a link to apply through


def test_nothing_found_and_no_link_falls_back_to_linkedin():
    hit = resolve.resolve(FakeHttp({}), "Nowhere Corp", use_ai=False)
    assert hit["ats"] == "" and "linkedin.com/jobs" in hit["url"]


def test_the_model_only_gets_to_suggest_verified_boards(monkeypatch):
    http = FakeHttp({("lever", "epifi"): 2}, owners={})
    monkeypatch.setattr(resolve, "ai_suggestions",
                        lambda name, note="": {"ats": "greenhouse", "slugs": ["fimoney", "epifi"], "careers_url": ""})
    hit = resolve.resolve(http, "Fi Money", use_ai=True)
    assert (hit["ats"], hit["board"], hit["via"]) == ("lever", "epifi", "local AI")

    # the same suggestion, with no board behind it, must not reach the list
    hit = resolve.resolve(FakeHttp({}), "Fi Money", use_ai=True)
    assert hit["ats"] == ""


def test_the_cache_is_used_before_the_network():
    cache = {"openai": {"ats": "ashby", "board": "openai", "url": "u", "jobs": 5, "checked": __import__("time").time()}}
    http = FakeHttp({})
    hit = resolve.resolve(http, "OpenAI", use_ai=False, cache=cache)
    assert hit["board"] == "openai" and http.calls == []


# --------------------------------------------------------------- fetch() glue

def test_fetch_retries_with_the_resolved_board():
    http = FakeHttp({("ashby", "openai"): 2}, owners={"openai": "OpenAI"})
    dead = Company("OpenAI", "greenhouse", "openai")
    fixed = Company("OpenAI", "ashby", "openai")
    jobs, total, _ = fetch(http, dead, lambda t: True, ["engineer"], 0, resolver=lambda c, why: fixed)
    assert total == 2 and len(jobs) == 2


def test_fetch_without_a_board_says_so_instead_of_raising_a_404():
    http = FakeHttp({})
    c = Company("Meta", "auto", "", url="https://www.metacareers.com/")
    with pytest.raises(Unresolved) as e:
        fetch(http, c, lambda t: True, ["engineer"], 0, resolver=lambda c, why: None)
    assert e.value.url == "https://www.metacareers.com/"
