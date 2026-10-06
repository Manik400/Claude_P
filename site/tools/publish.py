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
KEEP = {"jobhunt": 40, "careers": 30, "naukri": 60, "interview": 31, "applications": 1, "accuracy": 1}
# Reports older than this are deleted from the site, whatever KEEP allows. The one-copy
# pages (applications log, accuracy) are rewritten every run and never age out.
RETENTION_DAYS = 30


def prune_old(pages, idx, now):
    cutoff = (now - dt.timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = [i for i in idx["items"] if KEEP.get(i["kind"], 30) > 1 and str(i.get("when") or "") < cutoff]
    for item in old:
        idx["items"].remove(item)
        _remove_files(pages, item)
    return len(old)


def prune_keep(pages, idx):
    """At most KEEP[kind] reports per kind, newest kept. Returns how many went."""
    gone = 0
    for kind, keep in KEEP.items():
        same = sorted([i for i in idx["items"] if i.get("kind") == kind], key=lambda i: str(i.get("when") or ""), reverse=True)
        for old in same[keep:]:
            idx["items"].remove(old)
            _remove_files(pages, old)
            gone += 1
    return gone


EXT = {"careers": "json"}   # everything else is an HTML page
STAMP_RX = re.compile(r"^(?P<kind>[a-z]+)-(?P<d>\d{8})-(?P<t>\d{6})-")


def _title_from_html(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(20000)
    except OSError:
        return ""
    m = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
    if not m:
        return ""
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    title = re.sub(r"^Job Hunt\s*[·-]\s*", "", title)                        # the report's own prefix
    title = re.sub(r"\s*[·-]\s*\d{1,2} [A-Za-z]{3} \d{4}$", "", title)       # ...and its date suffix
    return title


def _item_from_file(pages, kind, rel, m):
    """An index entry rebuilt from a published file alone (its name has the time; a careers
    JSON carries its roles and counts; an HTML page its <title>)."""
    path = os.path.join(pages, rel.replace("/", os.sep))
    name = os.path.basename(rel)
    rid = name.rsplit(".", 1)[0]
    d, t = m.group("d"), m.group("t")
    when = "%s-%s-%sT%s:%s:%sZ" % (d[:4], d[4:6], d[6:], t[:2], t[2:4], t[4:])
    meta, title = {}, ""
    if kind == "careers" and name.endswith(".json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        mm = (data.get("meta") or {}) if isinstance(data, dict) else {}
        jobs = (data.get("jobs") or []) if isinstance(data, dict) else []
        title = ", ".join(mm.get("roles") or [])
        lst = mm.get("list") or {}
        meta = {"jobs": str(len(jobs)), "relocation": str(sum(1 for j in jobs if isinstance(j, dict) and j.get("reloc") == "yes")),
                "countries": "worldwide" if "*" in (mm.get("countries") or []) else ",".join(mm.get("countries") or []),
                "experience": mm.get("experience") or "", "reloc_mode": mm.get("relocation") or "",
                "days": str(mm.get("days") or ""), "hours": str(mm.get("hours") or ""),
                "list_sha": lst.get("sha", ""), "list_count": str(lst.get("count", ""))}
    elif name.endswith(".html"):
        title = _title_from_html(path)
    if not title:
        title = rid[len(kind) + 17:].replace("-", " ").strip() or rid
    jobs_rel = rel.rsplit(".", 1)[0] + ".jobs.json"
    if os.path.exists(os.path.join(pages, jobs_rel.replace("/", os.sep))):
        meta["jobs_file"] = jobs_rel
        if "jobs" not in meta:
            try:
                with open(os.path.join(pages, jobs_rel.replace("/", os.sep)), encoding="utf-8") as f:
                    meta["jobs"] = str(len(json.load(f)))
            except (OSError, ValueError, TypeError):
                pass
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {"id": rid, "kind": kind, "title": title, "when": when, "file": rel, "bytes": size, "meta": meta}


def reconcile_index(pages, idx):
    """List again every report file that is on the branch but missing from the index.

    Two publishers pushing at once used to settle data/index.json with one side's copy,
    and the other side's report - file safely on the branch - vanished from the phone.
    Such a file is relisted from what it carries. One-copy kinds (applications, accuracy)
    are never relisted: a leftover there is deleted instead. Reports removed on the
    phone (their kind + title on the index's `hidden` list) stay removed.
    Returns (added, deleted).
    """
    listed = set()
    for i in idx.get("items") or []:
        for rel in (i.get("file"), (i.get("meta") or {}).get("jobs_file")):
            if rel:
                listed.add(str(rel).replace("\\", "/"))
    hidden = {tuple(h) for h in idx.get("hidden") or [] if isinstance(h, list) and len(h) == 2}
    added = deleted = 0
    for kind in KEEP:
        folder = os.path.join(pages, "data", kind)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            rel = "data/%s/%s" % (kind, name)
            if rel in listed or name.endswith(".jobs.json") or not name.endswith((".html", ".json")):
                continue
            m = STAMP_RX.match(name)
            if not m or m.group("kind") != kind:
                continue
            if KEEP.get(kind, 30) <= 1:
                try:
                    os.remove(os.path.join(folder, name))
                    deleted += 1
                except OSError:
                    pass
                continue
            item = _item_from_file(pages, kind, rel, m)
            if item is None or (kind, item["title"]) in hidden:
                continue
            idx.setdefault("items", []).append(item)
            listed.add(rel)
            added += 1
    if added or deleted:
        print("publish: index reconciled - %d report(s) relisted from their files, %d leftover one-copy file(s) deleted" % (added, deleted))
    return added, deleted


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
    reconcile_index(a.pages, idx)
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
    aged = prune_old(a.pages, idx, now)
    if aged:
        print("publish: deleted %d report(s) older than %d days" % (aged, RETENTION_DAYS))
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
    # The 75-Day SDE Plan tracker (the site's Plan tab) lives at plan/.
    plan_src = os.path.join(os.path.dirname(SITE_DIR), "sde-75-day-plan")
    if os.path.exists(os.path.join(plan_src, "index.html")):
        os.makedirs(os.path.join(a.pages, "plan"), exist_ok=True)
        for name in ("index.html", "plan.json", "qna.json"):
            shutil.copyfile(os.path.join(plan_src, name), os.path.join(a.pages, "plan", name))
    with open(os.path.join(a.pages, ".nojekyll"), "w") as f:
        f.write("")
    if not os.path.exists(os.path.join(a.pages, "data", "index.json")):
        save_index(a.pages, {"updated": None, "items": []})
    else:
        idx = load_index(a.pages)
        added, deleted = reconcile_index(a.pages, idx)
        pruned = prune_keep(a.pages, idx)
        aged = prune_old(a.pages, idx, dt.datetime.now(dt.timezone.utc))
        if added or deleted or pruned or aged:
            save_index(a.pages, idx)
        if aged:
            print("publish: deleted %d report(s) older than %d days" % (aged, RETENTION_DAYS))
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
