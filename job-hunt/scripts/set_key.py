"""Store an API key in both places it is read from, without it showing on screen or in chat.

    python job-hunt/scripts/set_key.py APIFY_TOKEN
    python job-hunt/scripts/set_key.py FIRECRAWL_API_KEY --local-only

Asks for the value (hidden input), writes it into the repo-root .env (the PC's hourly
search reads that), sets the GitHub repository secret of the same name through `gh`
(the phone-triggered searches read that), then runs check_keys.py so you see at once
whether the key is accepted.
"""
import argparse
import getpass
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(os.path.dirname(os.path.dirname(HERE)), ".env")
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="e.g. " + ", ".join(KNOWN[:3]))
    ap.add_argument("--local-only", action="store_true", help="only .env, not the GitHub secret")
    a = ap.parse_args(argv)
    name = a.name.strip().upper()
    if name not in KNOWN and input(f"{name} is not a key this project reads. Store it anyway? [y/N] ").lower() != "y":
        return 1
    value = getpass.getpass(f"Paste {name} (hidden) and press Enter: ").strip()
    if not value:
        print("nothing entered; nothing changed")
        return 1
    write_env(name, value)
    print(f".env: {name} saved")
    if not a.local_only:
        r = subprocess.run(["gh", "secret", "set", name], input=value, text=True, capture_output=True)
        print(f"GitHub secret {name}: " + ("set" if r.returncode == 0 else "FAILED - " + (r.stderr or r.stdout).strip()))
    return subprocess.run([sys.executable, os.path.join(HERE, "check_keys.py")]).returncode


if __name__ == "__main__":
    sys.exit(main())
