"""Add an encrypted report to a gh-pages checkout and update data/index.json.

    python publish.py report --pages DIR --kind jobhunt|careers|naukri|interview --title "..." --file report.html [--meta k=v ...]
    python publish.py site   --pages DIR            copy the phone UI (site/index.html) into the checkout

Kinds:  jobhunt   worldwide search report (job-hunt bot)
        careers   company career-page search (careers bot; JSON the Careers tab renders)
        naukri    Naukri daily openings page
        interview interview-prep study page
Old reports are pruned per kind (KEEP newest) so the branch stays small.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.dirname(HERE)
KEEP = {"jobhunt": 40, "careers": 30, "naukri": 40, "interview": 20}


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40] or "report"


def load_index(pages):
    p = os.path.join(pages, "data", "index.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"updated": None, "items": []}


def save_index(pages, idx):
    os.makedirs(os.path.join(pages, "data"), exist_ok=True)
    idx["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    idx["items"].sort(key=lambda i: i["when"], reverse=True)
    with open(os.path.join(pages, "data", "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


def publish_report(a):
    sys.path.insert(0, HERE)
    import vault

    passphrase = vault.get_passphrase()
    if not passphrase:
        raise SystemExit("publish: no passphrase. Add the SITE_PASSPHRASE secret (GitHub) or run setup_phone.bat (PC).")
    with open(a.file, "rb") as f:
        raw = f.read()
    now = dt.datetime.now(dt.timezone.utc)
    rid = "%s-%s-%s" % (a.kind, now.strftime("%Y%m%d-%H%M%S"), slug(a.title))
    rel = "data/%s/%s.enc" % (a.kind, rid)
    os.makedirs(os.path.join(a.pages, "data", a.kind), exist_ok=True)
    with open(os.path.join(a.pages, rel), "wb") as f:
        f.write(vault.encrypt_bytes(raw, passphrase))
    meta = {}
    for kv in a.meta or []:
        k, _, v = kv.partition("=")
        meta[k] = v
    idx = load_index(a.pages)
    # A re-published file with the same title on the same day replaces the earlier copy (Naukri re-runs).
    if a.replace_same_title:
        for old in [i for i in idx["items"] if i["kind"] == a.kind and i["title"] == a.title]:
            idx["items"].remove(old)
            p = os.path.join(a.pages, old["file"])
            if os.path.exists(p):
                os.remove(p)
    idx["items"].append({"id": rid, "kind": a.kind, "title": a.title, "when": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "file": rel, "bytes": len(raw), "meta": meta})
    same = sorted([i for i in idx["items"] if i["kind"] == a.kind], key=lambda i: i["when"], reverse=True)
    for old in same[KEEP.get(a.kind, 30):]:
        idx["items"].remove(old)
        p = os.path.join(a.pages, old["file"])
        if os.path.exists(p):
            os.remove(p)
    save_index(a.pages, idx)
    print('publish: %s (%d bytes) as "%s"' % (rel, len(raw), a.title))


def publish_site(a):
    shutil.copyfile(os.path.join(SITE_DIR, "index.html"), os.path.join(a.pages, "index.html"))
    with open(os.path.join(a.pages, ".nojekyll"), "w") as f:
        f.write("")
    if not os.path.exists(os.path.join(a.pages, "data", "index.json")):
        save_index(a.pages, {"updated": None, "items": []})
    print("publish: site files copied")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    r = sub.add_parser("report")
    r.add_argument("--pages", required=True)
    r.add_argument("--kind", required=True, choices=sorted(KEEP))
    r.add_argument("--title", required=True)
    r.add_argument("--file", required=True)
    r.add_argument("--meta", action="append")
    r.add_argument("--replace-same-title", action="store_true", dest="replace_same_title")
    r.set_defaults(fn=publish_report)
    s = sub.add_parser("site")
    s.add_argument("--pages", required=True)
    s.set_defaults(fn=publish_site)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
