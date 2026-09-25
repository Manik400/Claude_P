import json
from types import SimpleNamespace

from naukri import learning


def _use_model(tmp_path, monkeypatch, data):
    path = tmp_path / "learned.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(learning, "LEARNED", path)
    learning._MODEL_CACHE.clear()


def test_features_cover_company_keyword_skills_title():
    f = learning.features("Senior Python Developer", "Acme", ["Django", "AWS"], "Backend Developer")
    assert "company:acme" in f and "keyword:backend developer" in f
    assert "skill:django" in f and "title:python" in f
    assert "title:senior" not in f and "title:developer" not in f   # stop words


def test_strategy_of():
    assert learning.strategy_of({"board": "linkedin"}) == "linkedin easy apply"
    assert learning.strategy_of({"board": "naukri", "status": "offsite"}) == "naukri company site"
    assert learning.strategy_of({"board": "naukri", "answers": [{}]}) == "naukri questionnaire"
    assert learning.strategy_of({"board": "naukri", "status": "applied"}) == "naukri one-click"


def test_no_model_means_no_adjustment(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "LEARNED", tmp_path / "missing.json")
    learning._MODEL_CACHE.clear()
    job = SimpleNamespace(title="Python Developer", company="Acme", skills=["python"], source="")
    assert learning.adjustment(job) == 0.0
    assert learning.job_priority(job) == 1.0


def test_inactive_model_does_not_move_scores(tmp_path, monkeypatch):
    _use_model(tmp_path, monkeypatch, {"active": False, "weights": {"company:acme": 3.0}})
    job = SimpleNamespace(title="x", company="Acme", skills=[], source="")
    assert learning.adjustment(job) == 0.0


def test_adjustment_is_signed_and_capped(tmp_path, monkeypatch):
    _use_model(tmp_path, monkeypatch, {"active": True, "weights": {
        "company:good": 3.0, "skill:python": 3.0, "company:bad": -2.0}})
    good = SimpleNamespace(title="", company="Good", skills=["python"], source="")
    bad = SimpleNamespace(title="", company="Bad", skills=[], source="")
    assert 0 < learning.adjustment(good) <= learning.LEARNED_CAP
    assert -learning.LEARNED_CAP <= learning.adjustment(bad) < 0


def test_route_that_never_applies_ranks_below_one_that_does(tmp_path, monkeypatch):
    _use_model(tmp_path, monkeypatch, {"active": True, "weights": {}, "strategies": {
        "naukri one-click": {"success": 40, "failed": 10, "tried": 50},
        "naukri company site": {"manual": 200, "tried": 0},
    }})
    one_click = SimpleNamespace(company_apply=False, has_questionnaire=False)
    company = SimpleNamespace(company_apply=True, has_questionnaire=False)
    assert learning.job_priority(one_click) > 1.0 > learning.job_priority(company)
    assert 0.75 <= learning.job_priority(company) and learning.job_priority(one_click) <= 1.25
