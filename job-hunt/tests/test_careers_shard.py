"""careers_bot reads the company list in parts (--shard) and merges them into one report."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import careers_bot  # noqa: E402
from jobbot.careers.companies import Company  # noqa: E402


def _companies():
    out = [Company(f"gh{i}", "greenhouse", f"gh{i}") for i in range(50)]
    out += [Company(f"wd{i}", "workday", f"h{i}.wd5.myworkdayjobs.com/t/s") for i in range(20)]
    out += [Company(f"pe{i}", "personio", f"pe{i}") for i in range(7)]   # appended last in the real list
    return out


def test_parts_cover_every_company_once():
    companies = _companies()
    order = careers_bot.interleave(companies)
    parts = [order[i::4] for i in range(4)]
    names = [c.name for p in parts for c in p]
    assert sorted(names) == sorted(c.name for c in companies)
    # the boards at the end of the list are spread over the parts, not all in the last one
    assert all(any(c.ats == "workday" for c in p) for p in parts)
    assert sum(1 for p in parts if any(c.ats == "personio" for c in p)) >= 3


def test_shard_of():
    assert careers_bot.shard_of("2/4") == (2, 4)
    for bad in ("0/4", "5/4", "two"):
        try:
            careers_bot.shard_of(bad)
        except SystemExit:
            continue
        raise AssertionError(bad)


def _part(tmp_path, n, companies, jobs, ok):
    meta = {"version": "x", "roles": ["software engineer"], "generated": f"2026-10-01 10:0{n}", "seconds": 100 + n,
            "requests": 10, "companies": len(companies), "companies_total": 6, "companies_ok": ok,
            "companies_link_only": 0, "companies_skipped": 0, "boards_fixed": [], "role_matches": 5,
            "dropped": {"older than 30 days": 2}, "scored": False, "resume_skills": [], "shard": f"{n}/3"}
    path = tmp_path / f"p{n}.json"
    path.write_text(json.dumps({"meta": meta, "names": {"NL": "Netherlands"},
                                "companies": [{"name": c, "status": "ok"} for c in companies],
                                "jobs": jobs}), encoding="utf-8")
    return str(path)


def test_merge_sums_parts_and_counts_a_missing_one(tmp_path, capsys):
    p1 = _part(tmp_path, 1, ["a", "b"], [{"id": "1", "chance": 40, "reloc": "yes"}], 2)
    p2 = _part(tmp_path, 2, ["c", "d"], [{"id": "2", "chance": 90, "reloc": "visa"}], 2)
    out = tmp_path / "merged.json"
    careers_bot.main(["merge", str(out), p1, p2, str(tmp_path / "p3.json")])   # part 3 failed
    d = json.loads(out.read_text(encoding="utf-8"))
    assert [j["id"] for j in d["jobs"]] == ["2", "1"]          # best chance first across parts
    m = d["meta"]
    assert (m["companies"], m["companies_ok"], m["companies_skipped"]) == (6, 4, 2)
    assert m["role_matches"] == 10 and m["dropped"] == {"older than 30 days": 4}
    assert m["generated"] == "2026-10-01 10:02" and m["parts"] == 2
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["relocation"] == 1
