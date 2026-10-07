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
* **Posted within / pays at least:** a window in days or hours (boards that give an exact time are cut exactly; a
  posting with only a date, or none, is kept and marked "date only"), and a pay floor in LPA read from each posting's
  text (postings that state less are left out; ones that state no pay stay, marked "pay not stated", filterable).
* **Company list:** add a line per company (`Name | ats | board | note`); the file explains the format.
  `python job-hunt/scripts/careers_bot.py find "<company>"` tells you what to write, `... check` tests the whole list.
  Tap **Company list** on the phone to see it or open it in GitHub's editor. A report is a snapshot of the list it was
  made from: every careers report carries the list's fingerprint, the phone compares it with the list on the branch
  and marks reports made with an **older list** (with a "Search again with the current list" link), so a company you
  removed only disappears from the *next* search, never from an old report.

## Posts tab (`#posts`): LinkedIn hiring posts

The PC reads LinkedIn's *post* search ("hiring software engineer", "hiring SDE", "hiring freshers software", "hiring
2025 batch"...) every 30 minutes in a headless browser on your saved LinkedIn session - the "we are hiring" posts people
write, not job listings - keeps the hiring posts for 0-2 years (freshers / entry level / "0-2 yrs" / a recent batch /
junior, or nothing said about seniority; job seekers' own "open to work" posts are left out) from the last **12 hours**
and publishes them to `data/posts/linkedin_posts.json` through the GitHub API. The tab filters them: posted within 3 / 6 /
12 h, role (SWE / backend / frontend / Java / Python / .NET / mobile / DevOps / QA / data), experience (freshers, <=1 yr,
<=2 yrs stated, not stated), location (India, remote, the big Indian cities, outside India, or any text), must-haves
(email, apply link, pay stated, names a batch), free text, and sort by newest / best match / most reactions. Every post
opens on LinkedIn (its own link, copied from the post's menu; the author's posts page when that failed) and shows the
emails, links, skills, locations, batch years and pay it mentions.

Set up once on the PC (after `python main.py --linkedin-login` in `Profile_Naukri_Screener-main`):
`powershell -ExecutionPolicy Bypass -File Profile_Naukri_Screener-main\scripts\schedule_linkedin_posts.ps1` - the task
LinkedInPostsWatch runs the watcher (`naukri\jobs\linkedin_posts.py --loop`) at logon with no time limit, restarts it if
it stops, and logs to `logs\linkedin_posts.log`. It only reads LinkedIn: nothing is liked, commented on or messaged.

## Premium tab (`#premium`): the LinkedIn Premium runner, the post to publish, the PC's tasks

The PC's LinkedIn Premium runner (`Profile_Naukri_Screener-main\naukri\jobs\linkedin_premium.py`, task LinkedInPremium)
publishes `data/premium/latest.json` after every pass: days of Premium left, the day's numbers (applied, liked, recruiter
leads, InMail drafts), **today's post draft**, the reach numbers, the whole daily report (leads with drafted notes, InMail
drafts, jobs to apply to by hand, the abroad checklist) and the state of every scheduled task on the PC.

* **Post on LinkedIn (via PC)** sends the draft through the apply queue (`apply.yml`, action `post`); the PC's queue worker
  publishes it from your saved LinkedIn session on its next check-in (every 30 minutes, 2 minutes after logon) and the
  tab shows *posted*. **Open in LinkedIn, prefilled** opens LinkedIn's composer with the text so you tap Post yourself
  right now; **Copy text** copies it.
* **What runs on the PC**: each task with its state and **Start / Stop / Run now** (action `control`): Stop also disables
  the task so the 30-minute check does not restart it, Start enables and starts it. Applied on the PC's next check-in.

## Auto-apply from the phone: the one queue

Full walkthrough: [AUTO_APPLY.md](../AUTO_APPLY.md).

The phone page has seven tabs: **Home** (queue progress, PC status, hiring posts, questions waiting), **Search**
(worldwide boards with country chips - India first - or company career pages), **Jobs** (every report;
worldwide searches and Naukri scans open as job lists with filters, contacts and **Queue all** /
**+ Queue**), **Posts** (LinkedIn hiring posts from the last 12 h, see above), **Queue** (the one list with every job's status, pause / resume, retry / remove, the rules:
auto-queue, minimum match, boards, per-run limit, company-site handling, one auto-apply switch per platform), **Track** (applications, Q&A,
Gmail replies, your answers form) and **Settings**.

Every tap that asks the PC for something starts `apply.yml`, which only *queues* the request
(as JSON, on `gh-pages`). The PC does the applying: `site\phone_apply.bat`, scheduled every 30 minutes
and 2 minutes after every logon by `site\schedule_phone_apply.ps1`, folds the requests into
`data/apply/queue.json`, applies on Naukri and LinkedIn with your logins through the Naukri screener's
own walkers (same answers, same pacing, same daily caps), follows every other posting's Apply button to the company's form and
fills and submits it (Simplify Copilot fills first when set up; login walls and CAPTCHAs are left for you), and publishes the queue back with every item's status,
the percentage done, the questions waiting and a heartbeat. A PC that was off simply catches up
after boot; nothing is lost in between.

```
phone ──queue / retry / remove / rules / answers──▶ apply.yml ──▶ data/apply/queue/*.json
   ▲                                                                       │
   └── Home / Queue: 75% · applied · needs answer · by hand ◀── data/apply/queue.json ◀── PC (phone_apply.bat)
```

GitHub's runners never apply: they have no login, and a datacenter IP on your account is what gets it
restricted. So the PC has to be on (the lock screen is fine) for the queue to move.

## Privacy

Reports, the queue and the Track data are published as plain files on the public `gh-pages` branch, so
anyone with the URL can read them; there is no passphrase. Your resume is never a file in the repo.

## Your resume: one per device, no login

* **Phone (or any browser):** Settings → **Resume on this device** → upload a .pdf / .docx / .txt. Its text is read
  in the browser (pdf.js / JSZip from cdnjs) and kept, with the original file, in that browser's own storage (IndexedDB).
  Nothing is uploaded to the repo. Every worldwide or career-page search started from that device sends the text along
  as the run's `resume` input, so the jobs are scored against it; the Search forms say which resume a run will use.
  Another phone, another PC, or another browser has its own store (or none). Replace or remove it in Settings.
  The run's inputs are visible on that run's page under Actions in your repository.
* **PC:** `site\set_resume.bat` (drag a file onto it) stores the resume for that computer in
  `%LOCALAPPDATA%\JobHuntPhone\resume` - outside the repo, per Windows user. Every run the PC starts (the hourly rounds,
  `job_bot.py` without `--resume`, company-site applies, the LinkedIn Premium drafts) uses it; `--resume` on the command
  line still wins. `python site\tools\resume_store.py show | set <file> | clear`.
* **Fallback:** a run without a device resume uses the `RESUME_TEXT` repo secret, if set; without either, jobs are not scored.
Naukri login cookies and profile data never leave the PC; only the generated HTML pages are published.

## Setup (once, on the PC)

1. Install the GitHub CLI (<https://cli.github.com>) and log in: `gh auth login` (HTTPS).
2. Double-click `site\setup_phone.bat`. It optionally stores your resume as a repo secret, then
   creates the `gh-pages` branch, turns on GitHub Pages, and prints the URL.
3. On the phone: open the URL, go to **Settings**, enter a fine-grained GitHub token
   (this repo only, permission *Actions: Read and write*). Add the page to your home screen.

## Use

| Where | What |
| --- | --- |
| Phone → **Search** | Worldwide: role, experience, country chips (or 🌍 Everywhere), posted within, pay floor → **Start search**; 5–15 min later (20–40 for the whole world) it is under **Jobs**. Career pages: role, experience range, countries, relocation, posted within (days or hours), pay floor → **Search career pages**; 15–25 min. |
| Phone → **Posts** | LinkedIn hiring posts from the last 12 h, read by the PC every 30 min; filter by role, experience, location, must-haves. |
| Phone → **Jobs** | Tap a worldwide report or Naukri scan → job list → **Queue all** / **+ Queue** / **Contacts**; **Full report** opens the HTML. |
| Phone → **Queue** | Progress, every job's status, retry / remove, pause, the rules (auto-queue, limits, company sites). |
| PC, Naukri | `Profile_Naukri_Screener-main\publish_to_phone.bat` pushes the newest openings + interview pages. `jobs_scan_and_publish.bat` does the scan and the push; schedule it with `scripts\schedule_jobs_agent.ps1 -Mode scanpublish`. |
| PC, job-hunt | `job-hunt\publish_to_phone.bat` pushes the newest local report (or drag a `report.html` onto it). |
| No phone page | The GitHub mobile app can start the same run: repo → Actions → *Job Hunt (phone)* → Run workflow. |

## Optional secrets for more coverage

`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`, `RAPIDAPI_KEY`, `FIRECRAWL_API_KEY` (all free sign-ups).
`APIFY_TOKEN` (+ repo variable `APIFY_SOURCES`) for real Naukri / Indeed / LinkedIn scraping - what makes India
searches worth reading. `SIGNALHIRE_API_KEY` / `HUNTER_API_KEY` / `APOLLO_API_KEY` for recruiter and
hiring-manager contacts on every report.
Add them with `gh secret set NAME` and the GitHub runs pick them up.

## Files

| File | Purpose |
| --- | --- |
| `index.html` | The phone page (single file, no build step). |
| `tools/vault.py` | Encrypt/decrypt reports. Same format the page decrypts. |
| `tools/publish.py` | Add a report to a gh-pages checkout and maintain `data/index.json`. |
| `tools/pages_git.py` | Clone/refresh/push the `gh-pages` branch, creating it if missing. Two publishers pushing at once are merged (both sides' reports kept in `data/index.json`); a report file left on the branch without an index entry is relisted by `publish.py`. |
| `tools/run_jobhunt.py` | What the GitHub Actions run executes. |
| `tools/run_careers.py` | What the careers run executes (career-page search → encrypted JSON). |
| `tools/run_apply_queue.py` | What `apply.yml` executes: writes the phone's request to the queue. |
| `tools/phone_apply.py` | PC-side worker: the one queue - folds requests in, applies, publishes `queue.enc`. |
| `tools/offsite_apply.py` | Alias of `Profile_Naukri_Screener-main/naukri/jobs/simplify.py` (the Simplify-equipped browser). |
| `../.github/workflows/apply.yml` | The auto-apply request (`workflow_dispatch`). |
| `tools/phone_publish.py` | PC-side publisher used by the `.bat` files. |
| `tools/setup_phone.py` | One-time setup. |
| `../.github/workflows/jobhunt.yml` | The search run (`workflow_dispatch`). |
| `../.github/workflows/careers.yml` | The career-page search run (`workflow_dispatch`). |
| `../job-hunt/assets/companies.txt` | Companies the careers search reads. |
| `../Profile_Naukri_Screener-main/naukri/jobs/linkedin_posts.py` | The LinkedIn hiring-posts watcher (Posts tab); scheduled by `scripts/schedule_linkedin_posts.ps1`. |
| `../.github/workflows/site.yml` | Re-publishes `index.html` when it changes on `main`. |
