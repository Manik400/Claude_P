"""Add a report to a gh-pages checkout and update data/index.json.

    python publish.py report --pages DIR --kind jobhunt|careers|naukri|interview --title "..." --file report.html [--meta k=v ...]
    python publish.py site   --pages DIR            copy the phone UI (site/index.html) into the checkout

Kinds:  jobhunt   worldwide search report (job-hunt bot)
        careers   company career-page search (careers bot; JSON the Careers tab renders)
        naukri    Naukri daily openings page
        interview interview-prep study page
        applications  the Naukri screener's "Applications sent" log page (one copy, replaced)
Old reports are pruned per kind (KEEP newest) so the branch stays small.
Files are committed as plain .html / .json (careers results are JSON); the phone
page opens them directly, no passphrase.
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
KEEP = {"jobhunt": 40, "careers": 30, "naukri": 40, "interview": 20, "applications": 1, "accuracy": 1}
EXT = {"careers": "json"}   # everything else is an HTML page


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


def _remove_files(pages, item):
    for rel in (item.get("file"), (item.get("meta") or {}).get("jobs_file")):
        if not rel:
            continue
        p = os.path.join(pages, rel)
        if os.path.exists(p):
            os.remove(p)


def publish_report(a):
    with open(a.file, "rb") as f:
        raw = f.read()
    now = dt.datetime.now(dt.timezone.utc)
    rid = "%s-%s-%s" % (a.kind, now.strftime("%Y%m%d-%H%M%S"), slug(a.title))
    rel = "data/%s/%s.%s" % (a.kind, rid, EXT.get(a.kind, "html"))
    os.makedirs(os.path.join(a.pages, "data", a.kind), exist_ok=True)
    with open(os.path.join(a.pages, rel), "wb") as f:
        f.write(raw)
    meta = {}
    for kv in a.meta or []:
        k, _, v = kv.partition("=")
        meta[k] = v
    if getattr(a, "attach", None) and os.path.exists(a.attach):
        # The run's job list next to the report, so the phone's Auto-apply
        # panel can list the LinkedIn postings and the PC poller can look
        # them up by id.
        rel_jobs = "data/%s/%s.jobs.json" % (a.kind, rid)
        shutil.copyfile(a.attach, os.path.join(a.pages, rel_jobs))
        meta["jobs_file"] = rel_jobs
    idx = load_index(a.pages)
    # A re-published file with the same title on the same day replaces the earlier copy (Naukri re-runs).
    if a.replace_same_title:
        for old in [i for i in idx["items"] if i["kind"] == a.kind and i["title"] == a.title]:
            idx["items"].remove(old)
            _remove_files(a.pages, old)
    idx["items"].append({"id": rid, "kind": a.kind, "title": a.title, "when": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "file": rel, "bytes": len(raw), "meta": meta})
    same = sorted([i for i in idx["items"] if i["kind"] == a.kind], key=lambda i: i["when"], reverse=True)
    for old in same[KEEP.get(a.kind, 30):]:
        idx["items"].remove(old)
        _remove_files(a.pages, old)
    save_index(a.pages, idx)
    print('publish: %s (%d bytes) as "%s"' % (rel, len(raw), a.title))


def _convert(pages, rel, passphrase):
    """Rewrite one old encrypted file as plain; returns the new relative path, or None if unreadable."""
    import vault
    p = os.path.join(pages, rel)
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        blob = f.read()
    if not vault.is_encrypted(blob):
        return rel
    try:
        plain = vault.read_plain(blob, passphrase)
    except Exception:
        return None
    if rel.endswith(".jobs.enc") or rel.startswith("data/apply/"):
        new = rel[:-len(".enc")] + ".json"
    elif rel.endswith(".enc"):
        kind = rel.split("/")[1] if rel.count("/") >= 2 else ""
        new = rel[:-len(".enc")] + "." + EXT.get(kind, "html")
    else:
        new = rel
    with open(os.path.join(pages, new), "wb") as f:
        f.write(plain)
    if new != rel:
        os.remove(p)
    return new


def _has_encrypted(pages):
    """True when anything under data/ is still an old encrypted envelope."""
    for root, _dirs, files in os.walk(os.path.join(pages, "data")):
        for name in files:
            if name.endswith(".enc"):
                return True
    return False


def migrate_plain(pages):
    """One-time: turn the encrypted files of the old site into plain ones.

    Reports that still decrypt (the old passphrase is in SITE_PASSPHRASE or the PC
    config) are rewritten in place; the rest are dropped from the index, because
    nobody can read them any more. Also converts the queue, the Track data and
    pending phone requests. Safe to run every publish: a plain site is a no-op.

    With no passphrase in reach this does nothing at all. A GitHub runner has no
    SITE_PASSPHRASE unless the secret is set, and "cannot decrypt" there means
    "was not given the key", not "unreadable" - deleting on that reading is what
    wiped every Naukri and interview report the PC had published.
    """
    sys.path.insert(0, HERE)
    import vault

    passphrase = vault.get_passphrase()
    if not passphrase:
        if _has_encrypted(pages):
            print("publish: encrypted files found but no passphrase (set SITE_PASSPHRASE); "
                  "leaving them untouched")
        return
    idx = load_index(pages)
    kept, dropped, changed = [], 0, False
    for item in idx["items"]:
        new = _convert(pages, item["file"], passphrase)
        if new is None:
            _remove_files(pages, item)
            dropped += 1
            continue
        changed = changed or new != item["file"]
        item["file"] = new
        jobs = (item.get("meta") or {}).get("jobs_file")
        if jobs:
            nj = _convert(pages, jobs, passphrase)
            if nj:
                item["meta"]["jobs_file"] = nj
            else:
                item["meta"].pop("jobs_file", None)
        kept.append(item)
    if dropped or changed:
        idx["items"] = kept
        save_index(pages, idx)
        print("publish: migrated reports to plain files (%d kept, %d unreadable dropped)" % (len(kept), dropped))
    apply_dir = os.path.join(pages, "data", "apply")
    for name in ("queue", "profile"):
        old = os.path.join(apply_dir, name + ".enc")
        if os.path.exists(old):
            if _convert(pages, "data/apply/%s.enc" % name, passphrase) is None:
                os.remove(old)   # unreadable: the PC rebuilds it on its next run
            print("publish: migrated data/apply/%s" % name)
    qdir = os.path.join(apply_dir, "queue")
    if os.path.isdir(qdir):
        for name in os.listdir(qdir):
            if name.endswith(".enc") and _convert(pages, "data/apply/queue/" + name, passphrase) is None:
                os.remove(os.path.join(qdir, name))
    # Leftovers nobody can read any more: files of pruned reports, processed
    # requests, and the two mis-named copies an early migration run made.
    gone = 0
    for root, _dirs, files in os.walk(os.path.join(pages, "data")):
        for name in files:
            if name.endswith(".enc") or (root == apply_dir and name in ("queue.html", "profile.html")):
                os.remove(os.path.join(root, name))
                gone += 1
    if gone:
        print("publish: removed %d unreadable leftover file(s)" % gone)


def publish_site(a):
    # index.html is the page; the ui-v2 pair is the second skin it can switch
    # to (the portfolio look), copied only when present so an older checkout
    # still publishes.
    for name in ("index.html", "ui-v2.css", "ui-v2.js"):
        src = os.path.join(SITE_DIR, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(a.pages, name))
    with open(os.path.join(a.pages, ".nojekyll"), "w") as f:
        f.write("")
    if not os.path.exists(os.path.join(a.pages, "data", "index.json")):
        save_index(a.pages, {"updated": None, "items": []})
    migrate_plain(a.pages)
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
    r.add_argument("--attach", help="the run's jobs.json, stored next to the report for auto-apply")
    r.add_argument("--replace-same-title", action="store_true", dest="replace_same_title")
    r.set_defaults(fn=publish_report)
    s = sub.add_parser("site")
    s.add_argument("--pages", required=True)
    s.set_defaults(fn=publish_site)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
