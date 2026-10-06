"""Tiny helper for the gh-pages branch, used both on GitHub Actions and on the PC.

    python pages_git.py checkout <dir> [--repo URL]   clone/refresh gh-pages into <dir> (creates the branch if missing)
    python pages_git.py push <dir> "<message>"        commit everything in <dir> and push, retrying on races

The remote URL defaults to PAGES_REPO_URL, else the "origin" (or first) remote of the repo containing this file.
"""
import json
import os
import subprocess
import sys
import time

BRANCH = "gh-pages"
HERE = os.path.dirname(os.path.abspath(__file__))

# GitHub login for this folder only (`gh auth login` run with GH_CONFIG_DIR set
# to it, see site/gh.bat). When it exists, pushes from the gh-pages clone use it
# through a helper set in that clone's own .git/config - the global git
# credential helper and any other gh login are left alone.
LOCAL_GH = os.path.join(os.path.dirname(os.path.dirname(HERE)), ".gh")
if os.path.isfile(os.path.join(LOCAL_GH, "hosts.yml")):
    os.environ["GH_CONFIG_DIR"] = LOCAL_GH


def sh(args, cwd=None, check=True, capture=False):
    r = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=capture)
    if check and r.returncode != 0:
        err = (r.stderr or "") if capture else ""
        raise SystemExit("command failed (%d): %s\n%s" % (r.returncode, " ".join(args), err))
    return r


def default_repo_url():
    env = os.environ.get("PAGES_REPO_URL")
    if env:
        return env
    root = sh(["git", "rev-parse", "--show-toplevel"], cwd=HERE, capture=True).stdout.strip()
    remotes = sh(["git", "remote"], cwd=root, capture=True).stdout.split()
    name = "origin" if "origin" in remotes else (remotes[0] if remotes else None)
    if not name:
        raise SystemExit("no git remote found; pass --repo URL")
    return sh(["git", "remote", "get-url", name], cwd=root, capture=True).stdout.strip()


def remote_url(cwd):
    return sh(["git", "remote", "get-url", "origin"], cwd=cwd, check=False, capture=True).stdout.strip()


def ensure_identity(cwd):
    for key, val in (("user.name", "job-hunt-phone"), ("user.email", "job-hunt-phone@users.noreply.github.com")):
        if sh(["git", "config", key], cwd=cwd, check=False, capture=True).returncode != 0:
            sh(["git", "config", key, val], cwd=cwd)


def gh_exe():
    """Absolute path to the real gh.exe. Not shutil.which("gh"): run from site\\
    (the phone queue's working folder) that finds the gh.bat wrapper there as a
    relative "gh.BAT", which git's credential helper cannot start - every
    scheduled push then failed with "could not read Username"."""
    import shutil
    for path in (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "GitHub CLI", "gh.exe"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GitHub CLI", "gh.exe")):
        if os.path.isfile(path):
            return path
    found = shutil.which("gh.exe") or shutil.which("gh") or "gh"
    return os.path.abspath(found) if os.path.isfile(found) else found


def use_local_gh(cwd):
    if os.environ.get("GH_CONFIG_DIR") != LOCAL_GH:
        return
    gh = gh_exe().replace("\\", "/")
    key = "credential.https://github.com.helper"
    sh(["git", "config", "--local", "--unset-all", key], cwd=cwd, check=False)
    sh(["git", "config", "--local", "--add", key, ""], cwd=cwd)  # drop inherited helpers
    sh(["git", "config", "--local", "--add", key, "!'%s' auth git-credential" % gh], cwd=cwd)


def checkout(target, repo_url):
    target = os.path.abspath(target)
    if os.path.isdir(os.path.join(target, ".git")):
        sh(["git", "remote", "set-url", "origin", repo_url], cwd=target)
        r = sh(["git", "fetch", "--depth", "1", "origin", BRANCH], cwd=target, check=False, capture=True)
        if r.returncode == 0:
            sh(["git", "reset", "-q", "--hard", "FETCH_HEAD"], cwd=target)
        ensure_identity(target)
        use_local_gh(target)
        return
    os.makedirs(target, exist_ok=True)
    r = sh(["git", "clone", "-q", "--depth", "1", "--branch", BRANCH, "--single-branch", repo_url, target],
           check=False, capture=True)
    if r.returncode != 0:
        # Branch does not exist yet: start an empty one.
        sh(["git", "init", "-q", target])
        sh(["git", "checkout", "-q", "--orphan", BRANCH], cwd=target)
        sh(["git", "remote", "add", "origin", repo_url], cwd=target)
        with open(os.path.join(target, ".nojekyll"), "w") as f:
            f.write("")
    ensure_identity(target)
    use_local_gh(target)


def push(target, message):
    target = os.path.abspath(target)
    sh(["git", "add", "-A"], cwd=target)
    if sh(["git", "diff", "--cached", "--quiet"], cwd=target, check=False).returncode == 0:
        # nothing new to commit - but a commit made earlier and never pushed still goes
        ahead = sh(["git", "rev-list", "--count", "FETCH_HEAD..HEAD"], cwd=target, check=False, capture=True)
        if (ahead.stdout or "").strip() in ("", "0"):
            print("pages_git: nothing to publish")
            return
    else:
        sh(["git", "commit", "-q", "-m", message], cwd=target)
    for attempt in range(5):
        r = sh(["git", "push", "-q", "origin", "HEAD:" + BRANCH], cwd=target, check=False, capture=True)
        if r.returncode == 0:
            print("pages_git: published")
            return
        print("pages_git: push rejected (attempt %d), rebasing..." % (attempt + 1), file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        # A previous run may have died mid-rebase (auth failure etc.); clear it or every retry fails.
        git_dir = os.path.join(target, ".git")
        if os.path.isdir(os.path.join(git_dir, "rebase-merge")) or os.path.isdir(os.path.join(git_dir, "rebase-apply")):
            sh(["git", "rebase", "--abort"], cwd=target, check=False, capture=True)
        err = r.stderr or ""
        if "denied" in err or "403" in err:
            raise SystemExit(
                "pages_git: push denied by GitHub for " + remote_url(target) + "\n"
                "  the credentials git is using do not own this repo. Use the SSH remote instead:\n"
                "  set \"repo_url\" in %LOCALAPPDATA%\\JobHuntPhone\\config.json to git@github-personal:Manik400/Claude_P.git\n"
                "  (or remove the wrong github.com entry in Windows Credential Manager)")
        sh(["git", "fetch", "origin", BRANCH], cwd=target, check=False)
        rebase_keeping_both(target)
        time.sleep(2 + attempt * 3)
    raise SystemExit("pages_git: could not push after 5 attempts")


def merge_index_texts(ours_text, theirs_text, root):
    """Both sides' data/index.json folded into one: the union of their reports.

    Two publishers (the PC's queue run and a GitHub run, say) pushing at once used to
    settle the conflict with one side's copy of the index - `rebase -X theirs` - and
    the other side's report, its file safely on the branch, vanished from the phone.
    Items are kept from both sides by id; an item whose file is gone from the merged
    tree (a report removed on the phone meanwhile) stays gone; the `hidden` lists are
    joined; `updated` is the later of the two.
    """
    def load(text):
        try:
            d = json.loads(text or "{}")
        except ValueError:
            d = {}
        return d if isinstance(d, dict) else {}

    a, b = load(ours_text), load(theirs_text)
    by_id = {}
    for item in list(a.get("items") or []) + list(b.get("items") or []):
        if isinstance(item, dict) and item.get("id") and item["id"] not in by_id:
            by_id[item["id"]] = item
    items = [i for i in by_id.values()
             if not i.get("file") or os.path.exists(os.path.join(root, str(i["file"]).replace("/", os.sep)))]
    items.sort(key=lambda i: str(i.get("when") or ""), reverse=True)
    hidden = []
    for h in list(a.get("hidden") or []) + list(b.get("hidden") or []):
        if isinstance(h, list) and h not in hidden:
            hidden.append(h)
    out = dict(a)
    out.update({k: v for k, v in b.items() if k not in ("items", "hidden", "updated")})
    out["items"] = items
    if hidden:
        out["hidden"] = hidden[-500:]
    out["updated"] = max(str(a.get("updated") or ""), str(b.get("updated") or "")) or None
    return json.dumps(out, ensure_ascii=False, indent=1)


def rebase_keeping_both(target):
    """Replay this clone's commits on the branch's new tip, keeping both sides' work.

    data/index.json conflicts are merged (both sides' reports kept). Any other file in
    conflict keeps this clone's version: the PC is the only writer of the queue and the
    Track data, and a report file is never edited once published. Returns True when the
    rebase finished; on anything unexpected it is aborted and the caller's retry goes on
    from the state before.
    """
    r = sh(["git", "rebase", "FETCH_HEAD"], cwd=target, check=False, capture=True)
    rounds = 0
    while r.returncode != 0 and rounds < 50:
        rounds += 1
        conflicted = sh(["git", "diff", "--name-only", "--diff-filter=U"], cwd=target, check=False, capture=True).stdout.split()
        if not conflicted:
            print("pages_git: rebase stopped without a conflict to resolve:\n" + (r.stderr or r.stdout or ""), file=sys.stderr)
            sh(["git", "rebase", "--abort"], cwd=target, check=False, capture=True)
            return False
        for path in conflicted:
            if path.replace("\\", "/") == "data/index.json":
                # in a rebase, stage 2 is the branch as it is now ("ours") and stage 3 the commit being replayed ("theirs")
                ours = sh(["git", "show", ":2:" + path], cwd=target, check=False, capture=True).stdout
                theirs = sh(["git", "show", ":3:" + path], cwd=target, check=False, capture=True).stdout
                with open(os.path.join(target, path), "w", encoding="utf-8") as f:
                    f.write(merge_index_texts(ours, theirs, target))
                print("pages_git: data/index.json merged - both sides' reports kept")
            else:
                sh(["git", "checkout", "--theirs", "--", path], cwd=target, check=False, capture=True)
            sh(["git", "add", "--", path], cwd=target, check=False, capture=True)
        r = sh(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=target, check=False, capture=True)
    if r.returncode != 0:
        sh(["git", "rebase", "--abort"], cwd=target, check=False, capture=True)
        return False
    return True


def repo_slug(repo_url):
    """owner/name from https://github.com/o/r.git or git@host:o/r.git."""
    tail = repo_url.split("github.com/", 1)[-1] if "github.com/" in repo_url else repo_url.split(":", 1)[-1]
    tail = tail.strip("/")
    return tail[:-4] if tail.endswith(".git") else tail


def put_file(repo_url, path, text, message):
    """Write one file on gh-pages through the GitHub API - no local clone involved,
    so it is safe while another run is working in the clone (that run's next push
    rebases over this commit; it never touches the same file)."""
    import base64
    import json
    gh, slug = gh_exe(), repo_slug(repo_url)
    api = "repos/%s/contents/%s" % (slug, path)
    content = base64.b64encode(text.encode("utf-8")).decode("ascii")
    for _attempt in range(3):
        r = sh([gh, "api", api + "?ref=" + BRANCH, "--jq", ".sha"], check=False, capture=True)
        sha = r.stdout.strip() if r.returncode == 0 else ""
        body = {"message": message, "content": content, "branch": BRANCH}
        if sha:
            body["sha"] = sha
        r = subprocess.run([gh, "api", "-X", "PUT", api, "--input", "-"], input=json.dumps(body), text=True,
                           encoding="utf-8", errors="replace", capture_output=True)
        if r.returncode == 0:
            print("pages_git: %s written" % path)
            return
        if "409" not in (r.stderr or "") and "does not match" not in (r.stderr or ""):
            break   # not a race on the sha: retrying will not help
        time.sleep(2)
    raise SystemExit("pages_git: could not write %s: %s" % (path, (r.stderr or "").strip()[:300]))


def main(argv):
    if len(argv) >= 2 and argv[0] == "checkout":
        url = argv[argv.index("--repo") + 1] if "--repo" in argv else default_repo_url()
        checkout(argv[1], url)
    elif len(argv) == 3 and argv[0] == "push":
        push(argv[1], argv[2])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
