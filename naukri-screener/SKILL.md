---
name: naukri-screener
description: Naukri.com profile and job toolkit for the Indian job market. Extracts and rewrites the user's Naukri profile (headline, key skills, summary), refreshes it daily so it ranks higher in recruiter searches, scans and scores Naukri (and read-only LinkedIn) jobs against the profile, exports ranked Excel/HTML job trackers, auto-applies to high-scoring jobs only with explicit consent, and builds interview-prep pages (100 Q&A from the day's top 10 jobs). Use whenever the user mentions Naukri, their Indian job profile, recruiter visibility, refreshing/updating their profile, scanning Indian jobs, applying on Naukri, or interview preparation from scanned jobs — even if they don't say "skill".
---

# Naukri Screener

The tool lives at `D:\Manik\Projects\Claude_P\Profile_Naukri_Screener-main`. Run every command **from inside that folder** with its venv interpreter:

```
cd D:\Manik\Projects\Claude_P\Profile_Naukri_Screener-main
.venv\Scripts\python.exe main.py <flags>
```

Playwright drives a **visible** Chrome window (Naukri's Akamai blocks headless), so it needs a desktop session. Never pass `--headless`-style options. Runs can take several minutes — use a long timeout or run in the background.

## Safety rules (non-negotiable)

- Every command is a **dry run until `--yes` is added**. Never add `--yes` unless the user explicitly asked to apply/update in this conversation. Show the preview first, then ask.
- `data/state.json`, `data/chrome-login-profile/`, `data/profile.json` hold the user's logged-in session and personal data. Never print, copy, commit or upload them.
- Automating Naukri is against its ToS. When the user asks for live applies, keep `--limit` small (≤3) the first time and tell them to check what was sent.
- `jobs_agent.bat` applies live with no limit — don't run it unless the user names it.

## Common tasks → commands

| User wants | Command |
|---|---|
| Check which role pack is active | `main.py --roles` (set `role:` in `jobs.yaml`: `developer`, `support`, `cybersecurity`, `qa-automation`) |
| Log in / "session expired" | `main.py --login` (user signs in by hand; OTP/captcha OK) |
| Pull current profile | `main.py --extract` → `data/profile.json` |
| Rewrite headline / skills / summary | Read `data/profile.json`, draft new text into `changes.yaml` (copy from `changes.example.yaml`), run `main.py --apply` to preview, then **only after user says yes** `main.py --apply --yes` |
| Bump profile for recruiter ranking | `main.py --refresh` (or `daily_refresh.bat`) |
| Scan jobs, send nothing | `main.py --jobs` |
| Ranked Excel of jobs | `main.py --jobs-export --top 30 [--locations "Pune,Gurgaon"] [--worldwide] [--posted-days 1 --new-only]` → `data/jobs/` |
| Daily tracker page | `jobs_scan.bat` → `data/jobs/openings-<date>.html` (new jobs marked NEW) |
| Actually apply | `main.py --jobs --yes --limit 3` (only after explicit consent) |
| Jobs it couldn't auto-apply | `data/jobs/review_queue.json` (ranked) |
| LinkedIn read-only login | `main.py --linkedin-login` (`--no-linkedin` to skip LinkedIn in scans) |
| Interview prep | run a scan first, then `main.py --interview-prep` (or `interview_prep.bat`) → `data/interview/`; uses the `claude` CLI login, no API key. `--interview-page`, `--interview-repair`, `--reuse-jds`, `--model` are extras. |
| Scan + refresh + prep in one go | `jobs_scan_and_prep.bat` |
| Schedule 3 runs/day | `powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1` (needs the user logged in to Windows) |
| Probe a questionnaire | `main.py --jobs-probe [--url <job url>]` — required before enabling `answer_questionnaires` in `jobs.yaml` |

`--show` forces a visible browser, `--verbose` adds logging, `--date`/`--run` pick an earlier run.

## Config the user edits

- `jobs.yaml` — `role`, `searches` (keywords + cities), `auto_apply_min_score` (default 75), `max_auto_applies`, `answer_questionnaires` (keep `false` until probed), `skill_years` / `answers` (sent to recruiters in the user's name — must be real values).
- `roles/*.yaml` — role packs (search keywords, field gate, skill vocab). A new field = one new YAML, no code. See `docs/ROLES.md`.
- `resume/resume.yaml` + `python resume\build_resume.py` — needed for interview prep.
- `scripts/` — one-off profile editors (`add_project.py`, `add_past_employment.py`, `set_total_experience.py`, `repair_skills.py`, …); see `scripts/README.md`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Saved session has expired` | `main.py --login` |
| `No profile at data/profile.json` | `main.py --extract` |
| `Access Denied` | never headless; keep the browser visible |
| Google "browser may not be secure" | `--login` uses plain Chrome with profile in `data/chrome-login-profile/` |
| `spawn UNKNOWN` / side-by-side error | bundled Chromium broken; tool uses installed Chrome. `NAUKRI_BROWSER_CHANNEL=msedge` for Edge, `none` for bundled |
| Many fields `MISSING` | Naukri changed layout → update `naukri/selectors.py` |

## Presenting results

After a scan, summarise: number of jobs found / new today, the top 5 with score, company and location, how many hit `auto_apply_min_score`, and where the Excel/HTML tracker was written. After `--apply` preview, show the before/after diff of each field and ask for confirmation.

Related: the `job-hunt` skill covers jobs outside Naukri (worldwide boards). For Indian roles use this skill; for abroad/remote use `job-hunt`.
