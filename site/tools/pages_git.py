"""Tiny helper for the gh-pages branch, used both on GitHub Actions and on the PC.

    python pages_git.py checkout <dir> [--repo URL]   clone/refresh gh-pages into <dir> (creates the branch if missing)
    python pages_git.py push <dir> "<message>"        commit everything in <dir> and push, retrying on races

The remote URL defaults to PAGES_REPO_URL, else the "origin" (or first) remote of the repo containing this file.
"""
import os
import subprocess
import sys
import time

BRANCH = "gh-pages"
HERE = os.path.dirname(os.path.abspath(__file__))


def sh(args, cwd=None, check=True, capture=False):
    r = subprocess.run(args, cwd=cwd, text=True, capture_output=capture)
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


def ensure_identity(cwd):
    for key, val in (("user.name", "job-hunt-phone"), ("user.email", "job-hunt-phone@users.noreply.github.com")):
        if sh(["git", "config", key], cwd=cwd, check=False, capture=True).returncode != 0:
            sh(["git", "config", key, val], cwd=cwd)


def checkout(target, repo_url):
    target = os.path.abspath(target)
    if os.path.isdir(os.path.join(target, ".git")):
        sh(["git", "remote", "set-url", "origin", repo_url], cwd=target)
        r = sh(["git", "fetch", "--depth", "1", "origin", BRANCH], cwd=target, check=False, capture=True)
        if r.returncode == 0:
            sh(["git", "reset", "-q", "--hard", "FETCH_HEAD"], cwd=target)
        ensure_identity(target)
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


def push(target, message):
    target = os.path.abspath(target)
    sh(["git", "add", "-A"], cwd=target)
    if sh(["git", "diff", "--cached", "--quiet"], cwd=target, check=False).returncode == 0:
        print("pages_git: nothing to publish")
        return
    sh(["git", "commit", "-q", "-m", message], cwd=target)
    for attempt in range(5):
        r = sh(["git", "push", "-q", "origin", "HEAD:" + BRANCH], cwd=target, check=False, capture=True)
        if r.returncode == 0:
            print("pages_git: published")
            return
        print("pages_git: push rejected (attempt %d), rebasing..." % (attempt + 1), file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        sh(["git", "fetch", "origin", BRANCH], cwd=target, check=False)
        sh(["git", "rebase", "-X", "theirs", "FETCH_HEAD"], cwd=target, check=False)
        time.sleep(2 + attempt * 3)
    raise SystemExit("pages_git: could not push after 5 attempts")


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
