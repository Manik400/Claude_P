# Claude_P

There are two job-search tools in this repo:

| Folder | What it does |
| --- | --- |
| `job-hunt/` | Searches about 20 job sites worldwide, scores each job against your resume, and writes an HTML report with Apply buttons. |
| `Profile_Naukri_Screener-main/` | Improves your Naukri profile, keeps it near the top of recruiter searches, scans and applies to Naukri jobs, and builds interview-prep pages. |

---

## 1. job-hunt

### Setup (once)

1. Install Python 3.8 or newer from python.org and tick **Add Python to PATH**.
2. Install the packages:
   - double-click `job-hunt\install.bat`, **or**
   - run `python -m pip install --user -r job-hunt\requirements.txt`
3. Optional: make it usable from Claude by copying the `job-hunt` folder to `%USERPROFILE%\.claude\skills\job-hunt`.
4. Optional: for more job coverage, set any of these environment variables (all are free sign-ups): `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`, `RAPIDAPI_KEY`, `FIRECRAWL_API_KEY`.

### Use

1. **Easy mode:** double-click `job-hunt\jobhunt.bat` and answer the questions.
2. **Command mode:**
   ```
   python job-hunt\scripts\job_bot.py run --role "software engineer" --experience 0-2 --resume "C:\path\cv.pdf" --open
   ```
3. A full run takes about 3–8 minutes. The report opens in your browser when it finishes.
4. Reports are saved to `Documents\JobHunt\<date>_<role>\report.html`.
5. In the report, click **Apply** on a job. The bot never applies for you.

### Useful flags

| Flag | What it does |
| --- | --- |
| `--role "x"` | Job title to search. Repeat it to search more than one title. |
| `--experience 3` / `2-4` / `5+` | Your experience; used to filter out jobs you don't fit |
| `--countries "Germany,India"` | Countries to search. Default: DE, NL, ES, FI, AU, JP, TH, plus a Remote tab |
| `--resume cv.pdf` | Adds a 0–100 match score to each job. The resume stays on your PC. |
| `--days 7` | Only jobs posted in the last N days (default 30) |
| `--fit strict` / `all` | `strict` keeps only jobs you qualify for; `all` keeps everything |
| `--exclude "senior,lead"` | Drop jobs with these words in the title |
| `--must "python"` | Keep only jobs with these words in the title |
| `--details 0` | Faster, but the scores are weaker |
| `--no-remote` | Skip the remote job boards |

### Other commands

- `python job-hunt\scripts\job_bot.py countries`: list the supported countries.
- `python job-hunt\scripts\job_bot.py sources`: list the job sites it searches.
- `python job-hunt\scripts\job_bot.py selftest`: check that each site is reachable.
- `python job-hunt\scripts\job_bot.py score --run <run_dir> --resume cv.pdf`: add match scores to an earlier run.

### Notes

- Indeed, Naukri, Glassdoor and StepStone block bots. Use the **Search directly on** links in each country tab instead.
- If a site shows `ERROR` in `run.log`, that site has changed its page layout. Fix it in `job-hunt\scripts\jobbot\sources\`.

---

## 2. Profile_Naukri_Screener-main

All commands below are run from inside `Profile_Naukri_Screener-main\`.

### Setup (once)

1. Needs Python 3.9 or newer and a desktop session. Naukri blocks headless browsers, so a real browser window opens while it works.
2. Create a virtual environment and install:
   ```
   cd Profile_Naukri_Screener-main
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
3. Create your config with `copy jobs.example.yaml jobs.yaml`, then set `role:` to `developer`, `support`, `cybersecurity` or `qa-automation`.
4. Run `python main.py --roles` to confirm the right role is active.
5. Run `python main.py --login`. A browser opens; log in by hand (OTP and captcha work). The session is saved to `data/state.json`. Treat that file like a password.
6. Run `python main.py --extract` to save your profile to `data/profile.json`. Every job scan scores against this file.
7. Optional, needed for interview prep: copy `resume\resume.example.yaml` to `resume\resume.yaml`, edit it, then run `python resume\build_resume.py`.

### Use: profile

1. Copy `changes.example.yaml` to `changes.yaml` and write your new headline, key skills and summary in it.
2. `python main.py --apply`: preview the changes. Nothing is sent.
3. `python main.py --apply --yes`: push the changes to Naukri.
4. `python main.py --refresh`: bumps your profile's "last updated" time so it ranks higher in recruiter searches. Run it once a day, or use `daily_refresh.bat`.

### Use: jobs

1. `python main.py --jobs`: dry run. Searches, scores and writes a report, but **sends nothing**. Do this for a few days first.
2. `python main.py --jobs-export --top 30`: writes a ranked Excel sheet with apply links to `data/jobs/`.
   - `--locations "Pune,Gurgaon"` picks the cities to search.
   - `--worldwide` includes remote LinkedIn jobs.
   - `--posted-days 1 --new-only` shows only today's new jobs.
3. `jobs_scan.bat`: daily scan. Writes `data/jobs/openings-<date>.html`, a tracker page with jobs new today marked **NEW**.
4. `python main.py --linkedin-login`: log in to LinkedIn once. LinkedIn is **read-only**; the tool never applies there.
5. `python main.py --jobs --yes --limit 3`: really applies, up to 3 jobs. Check what it sent before you raise the limit.
6. Jobs it couldn't auto-apply to are listed, ranked, in `data/jobs/review_queue.json`.

### Use: interview prep

1. Run a scan first (`jobs_scan.bat` or `--jobs-export`).
2. `interview_prep.bat` (or `python main.py --interview-prep`) takes the day's top 10 jobs and writes a page of 100 questions with answers to `data/interview/`.
3. It uses your `claude` CLI login, so no API key is needed.
4. `jobs_scan_and_prep.bat` runs the scan, the refresh and the prep in one go.

### Automation (optional)

- `powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1` schedules 3 runs a day (08:52, 13:23, 18:11). Stay logged in to Windows, because it needs a visible browser.
- `jobs_agent.bat` applies **live** with no limit. Don't use it until you trust the scores.

### Settings in `jobs.yaml`

- `searches`: the keywords and cities to search. Delete the block to use your role pack's searches with your own city.
- `auto_apply_min_score`: jobs at or above this score are applied to automatically (default 75).
- `max_auto_applies`: the most applications it sends per day.
- `answer_questionnaires`: leave this `false` until you have run `python main.py --jobs-probe`.
- `skill_years` / `answers`: these are sent to recruiters in your name. Replace the example values with your real ones.

### Troubleshooting

| Problem | Fix |
| --- | --- |
| `Saved session has expired` | `python main.py --login` |
| Google says "This browser or app may not be secure" | `--login` now opens plain Chrome, so Google sign-in works there. Its profile is kept in `data/chrome-login-profile/`; treat it like a password. |
| `No profile at data/profile.json` | `python main.py --extract` |
| `Access Denied` | Don't run headless; keep the browser visible |
| `spawn UNKNOWN` / "side-by-side configuration is incorrect" | Playwright's bundled Chromium is broken on this PC, so the tool now uses your installed Chrome. Set `NAUKRI_BROWSER_CHANNEL=msedge` for Edge, or `none` to use the bundled build. |
| Many fields `MISSING` | Naukri changed its page layout. Update `naukri/selectors.py` |

⚠️ Automating Naukri is against its terms of service, so there is some risk to your account. Every command is a dry run until you add `--yes`.
