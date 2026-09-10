# Phone site

Run the worldwide job search from your phone and read every report (worldwide, Naukri, interview prep) at one URL.
No Claude involved: the phone page starts a GitHub Actions run, the run executes the job-hunt bot, and the
report is pushed to the `gh-pages` branch, which GitHub Pages serves.

```
phone  ──tap──▶  GitHub Actions (jobhunt.yml)  ──▶  job-hunt bot  ──▶  encrypted report  ──▶  gh-pages  ──▶  phone
PC     ──scan──▶ Naukri screener (needs Chrome on the PC) ──▶ publish_to_phone.bat ──▶ encrypted page ──▶ gh-pages ──▶ phone
```

## Privacy

The repo is public, so every report is encrypted (AES-256-GCM, key from your passphrase) before it is committed.
The phone page decrypts in the browser after you type the passphrase once. Without it the site shows only
titles like "python developer" and dates. Your resume is stored as text in a GitHub secret, never as a file in the repo.
Naukri login cookies and profile data never leave the PC; only the generated HTML pages are published.

## Setup (once, on the PC)

1. Install the GitHub CLI (<https://cli.github.com>) and log in: `gh auth login` (HTTPS).
2. Double-click `site\setup_phone.bat`. It asks for a passphrase and, optionally, your resume, then:
   stores the two repo secrets, creates the `gh-pages` branch, turns on GitHub Pages, and prints the URL.
3. On the phone: open the URL, go to **Settings**, enter the passphrase and a fine-grained GitHub token
   (this repo only, permission *Actions: Read and write*). Add the page to your home screen.

## Use

| Where | What |
| --- | --- |
| Phone → **Search** | Type role, experience, countries → **Start search**. About 5–15 min later it shows up under **Reports**. |
| Phone → **Reports** | Tap any report. Apply buttons open the job site in a new tab. |
| PC, Naukri | `Profile_Naukri_Screener-main\publish_to_phone.bat` pushes the newest openings + interview pages. `jobs_scan_and_publish.bat` does the scan and the push; schedule it with `scripts\schedule_jobs_agent.ps1 -Mode scanpublish`. |
| PC, job-hunt | `job-hunt\publish_to_phone.bat` pushes the newest local report (or drag a `report.html` onto it). |
| No phone page | The GitHub mobile app can start the same run: repo → Actions → *Job Hunt (phone)* → Run workflow. |

## Optional secrets for more coverage

`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`, `RAPIDAPI_KEY`, `FIRECRAWL_API_KEY` (all free sign-ups).
Add them with `gh secret set NAME` and the GitHub runs pick them up.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | The phone page (single file, no build step). |
| `tools/vault.py` | Encrypt/decrypt reports. Same format the page decrypts. |
| `tools/publish.py` | Add a report to a gh-pages checkout and maintain `data/index.json`. |
| `tools/pages_git.py` | Clone/refresh/push the `gh-pages` branch, creating it if missing. |
| `tools/run_jobhunt.py` | What the GitHub Actions run executes. |
| `tools/phone_publish.py` | PC-side publisher used by the `.bat` files. |
| `tools/setup_phone.py` | One-time setup. |
| `../.github/workflows/jobhunt.yml` | The search run (`workflow_dispatch`). |
| `../.github/workflows/site.yml` | Re-publishes `index.html` when it changes on `main`. |
