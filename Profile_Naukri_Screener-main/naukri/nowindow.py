"""No console windows from background runs.

The scheduled tasks LiveFeed, LinkedInPremium, PostLabeling, SocialPostsWatch and
LinkedInPostsWatch run straight under pythonw.exe, which has no console. Windows
gives every console program such a process starts (gh.exe, git.exe, powershell,
taskkill, ollama) a brand-new visible console of its own - so each publish
(pages_git.put_file: `gh api` GET, then `gh api` PUT) flashed two black windows
every few minutes and stole the keyboard focus.

install() makes every subprocess started from a console-less process default to
CREATE_NO_WINDOW. A process that does have a console (a terminal, or the hidden
one run_hidden.vbs gives the batch runs) is left alone: its children share that
console, so they show nothing new, and output a terminal user expects still
appears there.
"""
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
_OWN_CONSOLE = 0x00000010 | 0x00000008   # CREATE_NEW_CONSOLE | DETACHED_PROCESS


def _has_console() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        return True


def install() -> None:
    if sys.platform != "win32" or getattr(subprocess.Popen, "_nowindow", False) or _has_console():
        return

    class Popen(subprocess.Popen):
        _nowindow = True

        def __init__(self, *args, **kwargs):
            flags = kwargs.get("creationflags") or 0
            if not flags & _OWN_CONSOLE:
                kwargs["creationflags"] = flags | CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = Popen
