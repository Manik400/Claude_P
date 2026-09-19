"""Company-site postings through Simplify Copilot - now naukri/jobs/simplify.py.

    python offsite_apply.py --setup            sign in to Simplify once (same as
                                               python -m naukri.jobs.simplify --setup)
    python offsite_apply.py --try <url> [--submit] [--hidden]
    python offsite_apply.py                    show what is set up

Kept as a thin alias so older notes and the phone page's hint keep working.
The applying itself lives in the Naukri screener: the career applier runs in
the Simplify-equipped browser and Simplify fills each form before the
applier answers the rest and submits (see that module's docstring).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAUKRI = os.path.join(os.path.dirname(os.path.dirname(HERE)), "Profile_Naukri_Screener-main")
sys.path.insert(0, NAUKRI)

from naukri.jobs import simplify  # noqa: E402

EXT_ID = simplify.EXT_ID
PROFILE_DIR = simplify.PROFILE_DIR
extension_dir = simplify.extension_dir
ready = simplify.ready
setup = simplify.setup


if __name__ == "__main__":
    sys.exit(simplify.main())
