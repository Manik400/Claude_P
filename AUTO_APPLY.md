# Auto-apply from the phone: the one queue

> Short version: [AUTO_APPLY_SIMPLE.md](AUTO_APPLY_SIMPLE.md)

**What it is:** on the phone site (<https://manik400.github.io/Claude_P/>) every worldwide report and
every Naukri scan opens as a job list. Tap **Queue all** (or tick a few and **Queue selected**) and the
jobs go into **one queue**. Your PC works through that queue every 30 minutes with your own LinkedIn and
Naukri logins, and the phone shows the progress: `75% · 9 of 12 settled · 5 applied · 1 needs your
answer · 2 by hand · 1 failed`. The phone never applies by itself and GitHub never does either - it only
carries the request home.

## The tabs

| Tab | What it is for |
| --- | --- |
| **Home** | The queue's progress bar, whether the PC is on, today's counts against the daily caps, the questions waiting for you, the latest reports, searches running. |
| **Search** | Worldwide boards (country chips, India first; Naukri / Indeed / LinkedIn through Apify when set up) or company career pages. |
| **Jobs** | Every report: worldwide searches, Naukri scans from the PC, career-page searches, interview prep. Tap one → its job list with filters (board, country, match), **Contacts** per job, **+ Queue** per job or **Queue all**. |
| **Queue** | The one list: progress, pause / resume, the rules (auto-queue, minimum match, boards, per-run limit, what to do with company-site postings), every job with its status, **retry** / **remove**, the PC's recent runs. |
| **Track** | Every application (both projects), its screening Q&A, Gmail replies, your own status and notes; your answers form. |
| **Settings** | Passphrase, token, repo. Which optional keys unlock India coverage, contacts and Simplify. |

## Why the PC does the applying

* **The phone can't.** A web page on github.io has no access to your LinkedIn or Naukri session.
* **GitHub's runners mustn't.** No login there, and a datacenter IP on your account is what gets it restricted.
* **The PC already can.** The Naukri screener on it has the Naukri applier, the LinkedIn Easy Apply
  walker, your saved answers, the pacing rules and the daily caps. The queue just feeds it.

```
phone ──Queue all / +Queue / retry / remove / rules / answers──▶ apply.yml (GitHub Actions)
                                   │  writes  data/apply/queue/<request>.enc   (encrypted, gh-pages)
                                   ▼
        PC: site\phone_apply.bat  (every 30 min + 2 min after logon; site\schedule_phone_apply.ps1)
                                   │  folds requests into THE queue, auto-queues strong matches,
                                   │  applies on Naukri + LinkedIn (Simplify for company sites, optional)
                                   │  writes  data/apply/queue.enc    (every item, status, %, questions, PC heartbeat)
                                   │  writes  data/apply/profile.enc  (Track tab)
                                   ▼
phone ◀── Home / Queue: 75% done · applied · needs your answer · by hand · failed
```

## What happens when...

**...I tap Queue all and the PC is off.** Nothing is lost. The request sits on the `gh-pages` branch;
the queue file remembers every item and its status. The scheduled task fires two minutes after you log
in (and every 30 minutes after that), reads the request and starts applying. Home shows "PC off? last
seen 5 h ago" until then, and every queued item says *queued*.

**...the queue has 60 jobs.** Each run applies to at most 5 per board (change it under Queue → Rules),
a minute or more apart, and the daily caps from `Profile_Naukri_Screener-main\jobs.yaml`
(`linkedin_max_applies_per_day`, `max_auto_applies`) still hold. 60 jobs take a few hours to a couple of
days; the percentage on Home tells you where it is.

**...a form asks something the agent cannot answer.** The job shows *needs your answer* and the
question appears on Home / Queue / Track. Answer it there; the next run absorbs the answer, re-applies to
every job that was waiting on it, and remembers it for later applications (same
`data/jobs/questions.yaml` / answer bank the PC dashboard uses).

**...an application fails.** It is retried on the next two runs; after three tries it shows
*failed - tap retry* and waits for you. *Retry* puts it back in the queue.

**...the posting is on the company's own site.** With the default rule it is marked *company site -
apply by hand* and the job stays in the list with an **open** link. With Simplify set up (below) the PC
opens it in a browser that has the Simplify Copilot extension, lets it fill the form, screenshots it, and
either stops (*form pre-filled - finish on PC*) or presses Submit (*submitted*).

**...I want it fully automatic.** Queue → Rules → **Auto-queue jobs from every new report**, pick a
minimum resume match (say 60%) and the boards. From then on every new worldwide report and every Naukri
scan feeds the queue by itself; you only answer questions and read the Track tab.

**...I remove a job.** *Remove* takes it out on the next run (it cannot un-apply). *Pause queue* stops
applying without losing anything; *Resume* continues.

## Statuses

| Chip | Meaning |
| --- | --- |
| `sent - waits for PC` | the phone sent it; the PC has not run since |
| `queued` | in the queue, not reached yet |
| `applied` | Easy Apply / Naukri apply completed |
| `needs your answer` | stopped at a screening question; answer it on Home / Queue |
| `skipped (your rule)` | a question you marked "skip - never answer" |
| `applied earlier / closed` | already applied through the screener, or the posting is closed |
| `company site - apply by hand` | not one-click; open it from the list (or set up Simplify) |
| `form pre-filled - finish on PC` / `submitted` | Simplify modes |
| `unconfirmed` / `error` / `form failed` | retried twice more, then `failed - tap retry` |

## The pieces

| File | Role |
| --- | --- |
| `site/index.html` | the phone page (Home, Search, Jobs, Queue, Track, Settings) |
| `.github/workflows/apply.yml` | carries a request from the phone to the branch (`queue`, `remove`, `retry`, `pause`, `resume`, `settings`, `answers`, `profile`, `notes`) |
| `site/tools/run_apply_queue.py` | what that workflow runs |
| `site/tools/phone_apply.py` | the PC worker: the only writer of `data/apply/queue.enc` |
| `site/tools/offsite_apply.py` | Simplify-assisted browser for company-site postings (experimental) |
| `site/tools/phone_publish.py` | publishes Naukri scan pages **with their job list** so the phone can queue them; contacts on the way |
| `site/phone_apply.bat`, `site/schedule_phone_apply.ps1` | run / schedule the worker (every 30 min + at logon, hidden) |
| `job-hunt/scripts/jobbot/sources/apify.py` | Naukri / Indeed / LinkedIn through Apify (`APIFY_TOKEN`) |
| `job-hunt/scripts/jobbot/contacts.py` | recruiters and hiring managers per company (SignalHire / Hunter / Apollo + what the postings say) |
| `Profile_Naukri_Screener-main/` | the appliers, answers, pacing, caps, ledger, dashboard |

## Setup checklist

1. `site\setup_phone.bat` once (passphrase, secrets, `gh-pages`, Pages URL).
2. On the phone: Settings → passphrase + token → Save; add the page to the home screen.
3. Naukri screener set up on the PC with logins that work for `apply` (Naukri) and `--linkedin-login`.
4. `powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1` once, on the PC
   (`-Every 30 -Limit 5` are the defaults; `-Remove` to stop).
5. Optional, for India results: `gh secret set APIFY_TOKEN` (and repo variable `APIFY_SOURCES`, default
   `naukri,indeed`; add `linkedin` to also get the job poster as a contact).
6. Optional, for contacts on every report: any of `gh secret set SIGNALHIRE_API_KEY`, `HUNTER_API_KEY`,
   `APOLLO_API_KEY`. For Naukri scans (made on the PC) put the same keys in
   `%LOCALAPPDATA%\JobHuntPhone\config.json` under `"env": {...}`.
7. Optional, for company-site postings: install Simplify Copilot in Chrome, complete your Simplify
   profile, run `python site\tools\offsite_apply.py --setup` (sign in once), then Queue → Rules →
   Company-site postings → *Simplify fills the form, I submit on the PC*. Try *fills and submits* only
   after a few good screenshots in `%LOCALAPPDATA%\JobHuntPhone\shots`.

## Privacy and safety

* The repo is public, so every request, the queue, the profile and every report are AES-256-GCM
  encrypted with your passphrase before they are committed. Without the passphrase the site shows nothing
  readable.
* The GitHub token on the phone is fine-grained, this repo only, Actions read+write. It is sent only to
  `api.github.com`.
* LinkedIn / Naukri cookies never leave the PC. GitHub never touches either site.
* The PC applies at the screener's pace and daily caps; the phone cannot override either.
* `phone_apply.bat --dry-run` shows what a run would do without applying or pushing.
