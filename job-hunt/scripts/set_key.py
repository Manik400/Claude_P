"""Store an API key in both places it is read from, without it showing on screen or in chat.

    python job-hunt/scripts/set_key.py APIFY_TOKEN
    python job-hunt/scripts/set_key.py FIRECRAWL_API_KEY --local-only
    python job-hunt/scripts/set_key.py --all                  every key in turn, Enter skips one

Asks for the value (hidden input), writes it into the repo-root .env (the PC's hourly
search reads that), sets the GitHub repository secret of the same name through `gh`
(the phone-triggered searches read that), then runs check_keys.py so you see at once
whether the key is accepted.
"""
import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ENV = os.path.join(ROOT, ".env")
# The GitHub secret goes through this folder's own gh login (site/gh.bat), not
# the machine-wide one - the PC has more than one GitHub profile.
os.environ["GH_CONFIG_DIR"] = os.path.join(ROOT, ".gh")
# The real gh.exe, not whatever "gh" resolves to first (site\gh.bat is a wrapper).
GH = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "GitHub CLI", "gh.exe")
if not os.path.isfile(GH):
    GH = shutil.which("gh.exe") or "gh"
KNOWN = ("APIFY_TOKEN", "FIRECRAWL_API_KEY", "JOOBLE_API_KEY", "RAPIDAPI_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY",
         "SIGNALHIRE_API_KEY", "HUNTER_API_KEY", "APOLLO_API_KEY")


def write_env(name, value):
    lines = open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
    for i, line in enumerate(lines):
        if re.match(rf"\s*{re.escape(name)}\s*=", line):
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def store(name, local_only):
    value = getpass.getpass(f"Paste {name} (hidden, Enter to skip): ").strip()
    if not value:
        print(f"{name}: skipped")
        return False
    write_env(name, value)
    print(f".env: {name} saved")
    if not local_only:
        r = subprocess.run([GH, "secret", "set", name], input=value, text=True, capture_output=True, cwd=ROOT)
        print(f"GitHub secret {name}: " + ("set" if r.returncode == 0 else "FAILED - " + (r.stderr or r.stdout).strip()))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="e.g. " + ", ".join(KNOWN[:3]))
    ap.add_argument("--all", action="store_true", help="ask for every key this project reads, in turn")
    ap.add_argument("--local-only", action="store_true", help="only .env, not the GitHub secret")
    a = ap.parse_args(argv)
    if a.all:
        for name in KNOWN:
            store(name, a.local_only)
    else:
        if not a.name:
            ap.error("give a key name, or --all")
        name = a.name.strip().upper()
        if name not in KNOWN and input(f"{name} is not a key this project reads. Store it anyway? [y/N] ").lower() != "y":
            return 1
        if not store(name, a.local_only):
            return 1
    return subprocess.run([sys.executable, os.path.join(HERE, "check_keys.py")]).returncode


if __name__ == "__main__":
    sys.exit(main())
