"""One-time setup for the phone site. Run it via site\\setup_phone.bat.

What it does, in order:
  1. checks that git and the GitHub CLI (gh) are installed and logged in
  2. asks for a passphrase -> saved locally and stored as the SITE_PASSPHRASE repo secret
     (every published report is encrypted with it; you type it once on the phone)
  3. optionally turns your resume into text and stores it as the RESUME_TEXT secret
     (so runs on GitHub can score jobs against it; the file itself never leaves the PC)
  4. creates the gh-pages branch with the phone page and turns on GitHub Pages
  5. prints the URL to open on the phone

Re-running is safe: it updates the secrets and leaves published reports alone.
"""
import getpass
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "job-hunt", "scripts"))

MAX_SECRET = 45_000  # GitHub secrets are capped at 48 KB


def config_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JobHuntPhone", "config.json")


def sh(args, check=True, capture=True, **kw):
    r = subprocess.run(args, text=True, capture_output=capture, **kw)
    if check and r.returncode != 0:
        raise SystemExit("failed: %s\n%s" % (" ".join(args), r.stderr or r.stdout))
    return r


def step(msg):
    print("\n== " + msg)


def ask(q, default=""):
    try:
        v = input("%s%s: " % (q, (" [" + default + "]") if default else "")).strip()
    except EOFError:
        v = ""
    return v or default


def gh_repo():
    r = sh(["gh", "repo", "view", "--json", "nameWithOwner,url"], cwd=ROOT)
    return json.loads(r.stdout)


def ensure_pkg(mod, pip_name):
    try:
        __import__(mod)
    except ImportError:
        print("installing %s ..." % pip_name)
        sh([sys.executable, "-m", "pip", "install", "-q", "--user", pip_name], capture=False)


def main():
    step("Checking tools")
    for tool in ("git", "gh"):
        if not shutil.which(tool):
            raise SystemExit("%s is not installed. git: https://git-scm.com  gh: https://cli.github.com" % tool)
    if sh(["gh", "auth", "status"], check=False).returncode != 0:
        raise SystemExit("GitHub CLI is not logged in. Run:  gh auth login   (choose HTTPS, then re-run this).")
    # Let plain `git push` (used to publish to gh-pages) reuse the gh login.
    sh(["gh", "auth", "setup-git"], check=False)
    repo = gh_repo()
    owner, name = repo["nameWithOwner"].split("/")
    print("repo:", repo["nameWithOwner"])
    ensure_pkg("cryptography", "cryptography")

    cfg = {}
    if os.path.exists(config_path()):
        with open(config_path(), encoding="utf-8") as f:
            cfg = json.load(f)

    step("Passphrase for the phone site")
    print("Reports are encrypted with this before they go online. You will type it once on the phone.")
    if cfg.get("passphrase") and ask("A passphrase is already saved. Keep it? (y/n)", "y").lower().startswith("y"):
        passphrase = cfg["passphrase"]
    else:
        while True:
            passphrase = getpass.getpass("Passphrase (min 8 chars, not shown): ")
            if len(passphrase) < 8:
                print("too short")
                continue
            if getpass.getpass("Again: ") == passphrase:
                break
            print("did not match")
    cfg["passphrase"] = passphrase
    cfg["repo"] = repo["nameWithOwner"]
    cfg["repo_url"] = repo["url"] + ".git"
    os.makedirs(os.path.dirname(config_path()), exist_ok=True)
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    sh(["gh", "secret", "set", "SITE_PASSPHRASE", "--repo", repo["nameWithOwner"]], input=passphrase)
    print("secret SITE_PASSPHRASE set")

    step("Resume (optional)")
    print("Used only to score jobs on GitHub runs. Stored as text in a repo secret, never as a file in the repo.")
    path = ask("Resume file (.pdf/.docx/.txt), or Enter to skip", cfg.get("resume", "")).strip('"')
    if path:
        ensure_pkg("pypdf", "pypdf")
        ensure_pkg("docx", "python-docx")
        from jobbot.resume import extract_text
        text = extract_text(path)
        if len(text.encode("utf-8")) > MAX_SECRET:
            print("resume text is long; keeping the first %d bytes" % MAX_SECRET)
            text = text.encode("utf-8")[:MAX_SECRET].decode("utf-8", "ignore")
        sh(["gh", "secret", "set", "RESUME_TEXT", "--repo", repo["nameWithOwner"]], input=text)
        cfg["resume"] = path
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        print("secret RESUME_TEXT set (%d chars)" % len(text))

    step("Publishing the phone page (gh-pages branch)")
    sh([sys.executable, os.path.join(HERE, "phone_publish.py"), "site"], capture=False)

    step("Turning on GitHub Pages")
    api = "repos/%s/pages" % repo["nameWithOwner"]
    r = sh(["gh", "api", "-X", "POST", api, "-f", "source[branch]=gh-pages", "-f", "source[path]=/"], check=False)
    if r.returncode != 0 and "already" not in (r.stderr + r.stdout).lower() and "409" not in (r.stderr + r.stdout):
        print("could not enable Pages automatically:", (r.stderr or r.stdout).strip())
        print("Enable it by hand: GitHub -> repo Settings -> Pages -> Source: Deploy from a branch -> gh-pages / (root)")
    else:
        sh(["gh", "api", "-X", "PUT", api, "-f", "source[branch]=gh-pages", "-f", "source[path]=/"], check=False)
        print("Pages enabled")

    url = "https://%s.github.io/%s/" % (owner.lower(), name)
    step("Done")
    print("""
Open this on your phone (give GitHub a minute after the first publish):

    %s

On the phone page, open Settings once and enter:
  1. the passphrase you just chose
  2. a GitHub token so the page can start searches:
     GitHub -> Settings -> Developer settings -> Personal access tokens -> Fine-grained
     -> Generate: repository access = only %s, permissions: Actions = Read and write,
        Contents = Read-only. Copy it into the page.
Add the page to your home screen (Share -> Add to Home Screen) to use it like an app.
""" % (url, repo["nameWithOwner"]))


if __name__ == "__main__":
    main()
