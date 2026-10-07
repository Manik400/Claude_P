"""The resume stored for THIS computer, used by every run on it.

    python site\\tools\\resume_store.py set  "C:\\path\\Resume.pdf"    store (replaces the old one)
    python site\\tools\\resume_store.py show                           what is stored, and a preview of its text
    python site\\tools\\resume_store.py clear                          remove it

Where: %LOCALAPPDATA%\\JobHuntPhone\\resume\\current.<ext> - outside the repo, outside any login,
per Windows user. Another PC (or another user on this one) has its own. Everything on this PC
that scores or uploads a resume looks here first unless told a file explicitly: the worldwide
search (job_bot.py, the hourly rounds), company-site applies (career_apply.py), the LinkedIn
Premium runner's drafts. The phone keeps its own copy in its browser and sends it with the runs
it starts (workflow input `resume`); the runs the PC starts use this one.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "job-hunt", "scripts"))

from jobbot.resume import (  # noqa: E402
    ResumeError, clear_device_resume, device_resume_info, device_store_dir, extract_text, set_device_resume,
)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = (argv[0] if argv else "show").lower()
    if cmd == "set":
        if len(argv) < 2:
            print("usage: resume_store.py set <file.pdf|.docx|.txt>")
            return 2
        try:
            dest = set_device_resume(argv[1])
        except ResumeError as exc:
            print(f"  not stored: {exc}")
            return 1
        text = extract_text(dest)
        print(f"\n  Stored for this computer: {dest}\n  {len(text)} characters of text read from it. Every run on this PC uses it from now on.\n")
        return 0
    if cmd == "clear":
        clear_device_resume()
        print(f"\n  Cleared. Runs on this PC fall back to the resume in the project / the last run.\n")
        return 0
    info = device_resume_info()
    if not info:
        print(f"\n  No resume stored for this computer ({device_store_dir()}).\n  Store one: drag it onto site\\set_resume.bat, or  python site\\tools\\resume_store.py set <file>\n")
        return 0
    text = extract_text(info["path"])
    print(f"\n  {info['name']}  ({info['size']} bytes, stored {info.get('set_at') or '?'})\n  {info['path']}\n  {len(text)} characters of text. Preview:\n")
    print("  " + text[:600].replace("\n", "\n  "))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
