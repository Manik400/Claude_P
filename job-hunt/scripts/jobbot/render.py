"""HTML report generation: data is embedded as JSON into assets/report_template.html."""
import json
import os
from datetime import datetime

from .config import REMOTE, country_flag, country_name
from .fallback import direct_links

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")


def build_payload(meta, jobs, statuses):
    codes = list(meta.get("countries") or [])
    if REMOTE not in codes and any(j.country == REMOTE for j in jobs):
        codes.append(REMOTE)
    countries = []
    for cc in codes:
        n = sum(1 for j in jobs if j.country == cc)
        countries.append({
            "code": cc, "name": country_name(cc), "flag": country_flag(cc), "count": n,
            "links": direct_links(meta.get("roles", [""])[0] if meta.get("roles") else "", cc),
        })
    payload = {
        "meta": meta,
        "countries": countries,
        "sources": statuses,
        "jobs": [j.to_dict() for j in jobs],
    }
    return payload


def render(run_dir, meta, jobs, statuses, template_path=None):
    template_path = template_path or os.path.join(ASSETS, "report_template.html")
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()
    payload = build_payload(meta, jobs, statuses)
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    roles = ", ".join(meta.get("roles") or []) or "jobs"
    title = f"Job Hunt · {roles} · {datetime.now().strftime('%d %b %Y')}"
    html = tpl.replace("__TITLE__", title).replace("__DATA__", data)
    out = os.path.join(run_dir, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out
