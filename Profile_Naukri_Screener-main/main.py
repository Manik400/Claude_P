#!/usr/bin/env python
"""Naukri profile toolkit.

    python main.py --roles      list the role packs and show the active one
    python main.py --login      sign in once, save the session
    python main.py --extract    scrape the profile into data/
    python main.py --apply      push changes.yaml into the live profile
    python main.py --refresh    daily nudge so recruiter searches surface you
    python main.py --jobs       search, score and apply to today's matches
    python main.py --jobs-probe capture one screening questionnaire, answer nothing
    python main.py --jobs-export write a ranked .xlsx of matches to apply by hand
    python main.py --linkedin-login  sign in to LinkedIn once, save the session
    python main.py --interview-prep  100 Q&A for today's Top 10, as a study page
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from naukri import apply as apply_mod
from naukri import roles as roles_mod
from naukri import extract as extract_mod
from naukri import refresh as refresh_mod
from naukri import session as session_mod
from naukri.jobs import config as jobs_config
from naukri.jobs import daily as jobs_daily
from naukri.jobs import export as jobs_export
from naukri.jobs import linkedin as linkedin_mod
from naukri.jobs import probe as jobs_probe

LOG_DIR = Path(__file__).resolve().parent / "logs"

# Windows consoles default to cp1252, and the profile carries a rupee sign in
# the salary field - printing the summary would raise UnicodeEncodeError and
# lose an otherwise successful run. Degrade unprintable characters instead.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _setup_logging(verbose: bool) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "naukri.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def prep_errors():
    """The interview module's expected refusals, imported lazily.

    Lazy because naukri.interview pulls in the whole prompt/engine stack, and a
    plain --refresh run should not pay for that import.
    """
    try:
        from naukri.interview.generate import GenerationError
        from naukri.interview.profile import ProfileError
        return (GenerationError, ProfileError)
    except ImportError:
        return ()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--roles", action="store_true",
                        help="List the available role packs and show which one is active")
    action.add_argument("--login", action="store_true", help="Sign in manually and save the session")
    action.add_argument("--extract", action="store_true", help="Scrape the profile into data/")
    action.add_argument("--apply", action="store_true", help="Apply changes.yaml to the live profile")
    action.add_argument("--refresh", action="store_true", help="Bump the profile's last-modified timestamp")
    action.add_argument("--jobs", action="store_true", help="Run the daily job search, scoring and apply cycle")
    action.add_argument("--linkedin-login", action="store_true", dest="linkedin_login",
                        help="Sign in to LinkedIn manually and save the session")
    action.add_argument("--jobs-export", action="store_true", dest="jobs_export",
                        help="Write a ranked spreadsheet of matches with apply links")
    action.add_argument("--jobs-probe", action="store_true", dest="jobs_probe",
                        help="Open one queued questionnaire and record its structure without answering")
    action.add_argument("--interview-prep", action="store_true", dest="interview_prep",
                        help="Analyse the Top 10 jobs and generate 100 interview Q&A")
    action.add_argument("--interview-page", action="store_true", dest="interview_page",
                        help="Rebuild the interview-prep HTML from saved data, no model calls")
    action.add_argument("--interview-repair", action="store_true", dest="interview_repair",
                        help="Re-validate a saved preparation set and regenerate only the "
                             "questions that fail, without re-running the whole analysis")

    parser.add_argument("--show", action="store_true", help="Run with a visible browser")
    parser.add_argument("--yes", action="store_true", help="With --apply or --jobs: actually do it (default is a dry run)")
    parser.add_argument("--url", help="With --jobs-probe: probe this job URL instead of the top queued one")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="With --jobs: attempt at most N applications this run")
    parser.add_argument("--locations", default="Pune,Ahmedabad,Gurgaon",
                        help="With --jobs-export: comma-separated cities to search")
    parser.add_argument("--top", type=int, default=30,
                        help="With --jobs-export: how many jobs to write (default 30)")
    parser.add_argument("--worldwide", action="store_true",
                        help="With --jobs-export: search everywhere, remote roles first")
    parser.add_argument("--no-linkedin", action="store_true", dest="no_linkedin",
                        help="With --jobs-export: skip the LinkedIn tab (Naukri only)")
    parser.add_argument("--include-applied", action="store_true", dest="include_applied",
                        help="With --jobs-export: keep jobs already applied to")
    parser.add_argument("--posted-days", type=float, default=None, dest="posted_days", metavar="N",
                        help="With --jobs-export: only listings posted in the last N days (1 = last 24 hours)")
    parser.add_argument("--new-only", action="store_true", dest="new_only",
                        help="With --jobs-export: only jobs not already listed on an earlier day's page")
    parser.add_argument("--date", metavar="YYYY-MM-DD",
                        help="With --interview-prep: analyse that day's scan instead of today's")
    parser.add_argument("--engine", choices=("claude-cli", "anthropic"),
                        help="With --interview-prep: which model transport to use "
                             "(default: the claude CLI if installed, else the Anthropic API)")
    parser.add_argument("--model", help="With --interview-prep: model name to pass to the engine")
    parser.add_argument("--reuse-jds", action="store_true", dest="reuse_jds",
                        help="With --interview-prep: reuse JD text already fetched for that "
                             "date instead of re-opening ten job pages")
    parser.add_argument("--run", type=int, metavar="N",
                        help="With --interview-prep: write this run slot for the day "
                             "(default: the next free one). Three scans a day give "
                             "runs 1, 2 and 3, each with its own permanent file.")
    parser.add_argument("--no-reuse", action="store_true", dest="no_reuse",
                        help="With --interview-prep: generate all 100 fresh, ignoring the "
                             "question bank from earlier days")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    try:
        if args.roles:
            active = roles_mod.active_name()
            print(f"\n  Active role: {active}   (set `role:` in jobs.yaml to change it)\n")
            for name in roles_mod.available():
                mark = "*" if name == active else " "
                print(mark + roles_mod.summarise(roles_mod.load(name)))
            print("  Write your own by copying a file in roles/ - see docs/ROLES.md\n")
            return 0

        if args.login:
            return 0 if session_mod.login() else 1

        if args.extract:
            # Same Akamai constraint as --refresh: headless gets blocked.
            profile = extract_mod.extract(headless=False)
            print(extract_mod.summarise(profile))
            print("  Written to data/profile.json, data/profile.txt, data/profile.png")
            return 0

        if args.apply:
            changes = apply_mod.load_changes()
            # Applying runs headed unless explicitly told otherwise - you want
            # to see a live profile being edited.
            results = apply_mod.apply(changes, headless=False, dry_run=not args.yes)
            if not args.yes:
                print("  Re-run with --yes to actually save these.")
            failed = [f for f, r in results.items() if r not in ("ok", "dry-run")]
            return 1 if failed else 0

        if args.jobs:
            # Headed for the same Akamai reason as --refresh, and because a run
            # that submits real applications is one you want to be able to see.
            overrides = None
            if args.limit is not None:
                overrides = {"max_auto_applies": args.limit, "max_apply_attempts": args.limit}
            summary = jobs_daily.run(headless=False, dry_run=not args.yes,
                                     config_overrides=overrides)
            print(jobs_daily.summarise(summary))
            if not args.yes:
                print("  Dry run - nothing was submitted. Re-run with --yes to apply." + "\n")
            return 0

        if args.linkedin_login:
            return 0 if linkedin_mod.login() else 1

        if args.jobs_export:
            locations = [c.strip() for c in args.locations.split(",") if c.strip()]
            path, jobs, cards = jobs_export.run(
                locations, top=args.top, headless=False,
                include_applied=args.include_applied,
                include_linkedin=not args.no_linkedin,
                worldwide=args.worldwide,
                posted_days=args.posted_days,
                new_only=args.new_only)
            print(jobs_export.summarise(path, jobs, locations, cards,
                                        posted_days=args.posted_days,
                                        new_only=args.new_only))
            return 0

        if args.jobs_probe:
            # Clicks Apply once on a questionnaire posting, which opens the
            # drawer but does not submit - the application only completes once
            # the questions are answered, and this answers none of them.
            result = jobs_probe.probe(url=args.url, headless=False)
            print(jobs_probe.summarise(result))
            return 0

        if args.interview_prep:
            # Headed for the JD fetch, same Akamai reason as everything else
            # that opens Naukri. The model calls afterwards are offline.
            from naukri.interview import generate as prep_mod
            prep = prep_mod.run(day=args.date, engine=args.engine, model=args.model,
                                headless=False, reuse_jds=args.reuse_jds,
                                no_reuse=args.no_reuse, run=args.run)
            print(prep_mod.summarise(prep))
            from naukri.interview import validate as prep_validate
            print(prep_validate.summarise(prep["validation"]))
            print(f"  Study page: {prep.get('page')}\n")
            return 0 if prep["validation"]["ok"] else 1

        if args.interview_repair:
            from naukri.interview import generate as prep_mod, store as prep_store
            from naukri.interview import validate as prep_validate
            day = args.date or (prep_store.prep_runs() or [None])[0]
            if not day:
                print("\n  No saved preparation data. Run: python main.py --interview-prep\n")
                return 2
            prep = prep_mod.repair_saved(day, engine=args.engine, model=args.model)
            print(prep_validate.summarise(prep["validation"]))
            print(f"  Study page: {prep.get('page')}\n")
            return 0 if prep["validation"]["ok"] else 1

        if args.interview_page:
            from naukri.interview import page as prep_page, store as prep_store
            from naukri.interview import validate as prep_validate
            day = args.date or (prep_store.prep_runs() or [None])[0]
            if not day:
                print("\n  No saved preparation data. Run: python main.py --interview-prep\n")
                return 2
            # Re-run the gate as well as the page. The checks are pure functions
            # of the saved data, so re-running them costs nothing and means a
            # tightened check applies to days generated before it existed.
            for stored in prep_store.prep_runs():
                prep = prep_store.load_prep(stored)
                if prep and prep.get("questions"):
                    prep["validation"] = prep_validate.report(prep)
                    prep_store.save_prep(prep)
                    if stored == day:
                        print(prep_validate.summarise(prep["validation"]))
            written = prep_page.rebuild_all()
            if not written:
                print(f"\n  data/interview/prep-{day}.json is unreadable - nothing "
                      f"to rebuild from.\n")
                return 2
            print(f"\n  Rebuilt {len(written)} page(s). Latest: "
                  f"{next((p for p in written if day in p.name), written[-1])}\n")
            return 0

        if args.refresh:
            # Headed, always. Akamai serves "Access Denied" to headless
            # Chromium, so a headless daily job would fail every single day.
            ok = refresh_mod.refresh(headless=False)
            print("  Profile refreshed." if ok else "  Refresh failed - see logs/naukri.log")
            return 0 if ok else 1

    except roles_mod.RoleError as exc:
        print("\n  " + str(exc) + "\n")
        return 2
    except jobs_config.ConfigError as exc:
        print("\n  " + str(exc) + "\n")
        return 2
    except session_mod.NotLoggedIn as exc:
        print(f"\n  {exc}\n")
        return 2
    except prep_errors() as exc:
        # "the scan found only 6 jobs today" is a documented-normal morning on a
        # 24-hour filter, not a crash. Exit 2 like the other expected refusals so
        # a scheduled wrapper can tell it apart from a real failure, and so
        # logs/naukri.log does not collect a stack trace for it.
        print(f"\n  {exc}\n")
        return 2
    except FileNotFoundError as exc:
        # --interview-prep on a day that was never scanned. The message already
        # says which command to run, so printing a traceback adds nothing.
        print(f"\n  {exc}\n")
        return 2
    except Exception as exc:
        logging.getLogger("naukri").exception("Unhandled error")
        print(f"\n  Error: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
