# Phone site

Run the worldwide job search from your phone and read every report (worldwide, Naukri, interview prep) at one URL.
No Claude involved: the phone page starts a GitHub Actions run, the run executes the job-hunt bot, and the
report is pushed to the `gh-pages` branch, which GitHub Pages serves.

```
phone  ──tap──▶  GitHub Actions (jobhunt.yml)  ──▶  job-hunt bot  ──▶  encrypted report  ──▶  gh-pages  ──▶  phone
phone  ──tap──▶  GitHub Actions (careers.yml)  ──▶  careers bot   ──▶  encrypted JSON    ──▶  gh-pages  ──▶  phone (Careers tab)
PC     ──scan──▶ Naukri screener (needs Chrome on the PC) ──▶ publish_to_phone.bat ──▶ encrypted page ──▶ gh-pages ──▶ phone
```

## Careers tab (`#careers`)

Searches the career pages of the companies in `job-hunt/assets/companies.txt` directly (Agoda, Adyen, Spotify, …),
so you see a job the day the company posts it, including ones that never reach LinkedIn.

* **Form:** job title, your experience (`4`, `3-5`, `5+`), countries (🌍 Worldwide or pick several; the list is ordered by
  how often employers there relocate foreign tech hires), and **Only jobs that clearly offer relocation**. Tick
  **…or visa sponsorship** to also keep postings that sponsor a visa without saying "relocation".
* **Relocation check:** reads each posting and keeps the sentence that says it ("A relocation package including visa
  sponsorship…"), so you can see why a job counts. Postings that rule it out ("unable to sponsor") are marked *no relocation*.
* **Results** open in a separate screen: each job has its resume match score, experience fit, relocation evidence and an
  apply link. The country filter is sorted by chance of getting hired (match × experience fit × relocation, added up per country).
  **Contacts** gives LinkedIn and Google people searches for the CTO / heads of engineering, engineering managers,
  senior engineers and tech recruiters at that company in that city, plus recruiter names and emails the postings mention.
* **Company list:** add a line per company (`Name | ats | board | note`); the file explains the format.
  `python job-hunt/scripts/careers_bot.py find "<company>"` tells you what to write, `... check` tests the whole list.
  Tap **Company list** on the phone to see it or open it in GitHub's editor.

## Auto-apply from the phone

Open a worldwide report's **auto-apply** chip under Reports. It lists the report's LinkedIn postings with a
checkbox each and two buttons: **Apply to all** and **Apply to selected**. Tapping one starts the
`apply.yml` workflow, which only *queues* the request (encrypted, on `gh-pages`). The applying is done by
your PC: `site\phone_apply.bat`, scheduled every 30 minutes by `site\schedule_phone_apply.ps1`, reads
the queue, applies with your LinkedIn login through the Naukri screener's Easy Apply walker (same
answers, same pacing, same daily cap, a few per poll), and publishes each posting's status back, so the
panel shows *applied* / *needs your answer* / *apply on company site*. Screening questions it could not
answer appear in the same panel; answer them there and the PC re-applies on its next check.

The **Track** tab (`#track`) shows, after the passphrase, what the PC dashboard shows: your answers form
(CTC, phone, notice period, skill years, Yes/No on the standard questions, saved answers), the questions
waiting for you, and every application with its questions, answers, Gmail replies and your own status and
notes. Everything is editable there; edits travel back the same way (`apply.yml` -> queue -> PC) and are
saved exactly as the dashboard would save them. The PC refreshes `data/apply/profile.enc` on every check.

GitHub's runners never apply: they have no LinkedIn session, and a datacenter IP on your account is what
gets it restricted. So the PC has to be on (the lock screen is fine) for requests to be carried out.

```
phone ──auto-apply──▶ apply.yml ──▶ data/apply/queue/*.enc ──▶ PC (phone_apply.bat, every 30 min) ──▶ LinkedIn
                                                                          └──▶ data/apply/status.enc ──▶ phone
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
| Phone → **Careers** | Role, experience range, countries, relocation → **Search career pages**. About 3–8 min later it shows up under **Results** on the same tab. |
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
| `tools/run_careers.py` | What the careers run executes (career-page search → encrypted JSON). |
| `tools/run_apply_queue.py` | What `apply.yml` executes: writes the phone's request to the queue. |
| `tools/phone_apply.py` | PC-side poller: carries out queued requests, publishes status. |
| `../.github/workflows/apply.yml` | The auto-apply request (`workflow_dispatch`). |
| `tools/phone_publish.py` | PC-side publisher used by the `.bat` files. |
| `tools/setup_phone.py` | One-time setup. |
| `../.github/workflows/jobhunt.yml` | The search run (`workflow_dispatch`). |
| `../.github/workflows/careers.yml` | The career-page search run (`workflow_dispatch`). |
| `../job-hunt/assets/companies.txt` | Companies the careers search reads. |
| `../.github/workflows/site.yml` | Re-publishes `index.html` when it changes on `main`. |
