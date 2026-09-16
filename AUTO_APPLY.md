# Auto-apply from the phone

**What it is:** on the phone site (<https://manik400.github.io/Claude_P/#reports>) every worldwide
search report has an **auto-apply** chip. It opens a panel that lists the report's LinkedIn
postings, and one tap asks your PC to apply to them for you with your LinkedIn login. The phone
never applies by itself and GitHub never does either - it only carries the request home.

## Why the PC does the applying

* **The phone can't.** A web page on github.io has no access to your LinkedIn session.
* **GitHub's runners mustn't.** They have no LinkedIn login, and even if they had, a datacenter IP
  logging into your account is exactly what gets it restricted.
* **The PC already can.** The Naukri screener on it has the LinkedIn Easy Apply walker, your saved
  answers, the pacing rules and the daily cap. Auto-apply just feeds it postings from the phone.

So the phone drops an encrypted request on the `gh-pages` branch, the PC picks it up on a
schedule, applies from home with the real session, and publishes the result back so the phone
can show it.

```
phone ──auto-apply chip──▶ apply.yml (GitHub Actions)
                              │  writes  data/apply/queue/<request>.enc   (encrypted, gh-pages)
                              ▼
        PC: site\phone_apply.bat  (every 30 min, scheduled by site\schedule_phone_apply.ps1)
                              │  reads the queue, applies on LinkedIn via the Naukri screener
                              │  writes  data/apply/status.enc   (per-posting outcome, open questions)
                              │  writes  data/apply/profile.enc  (your answers form, applications, replies)
                              ▼
phone ◀── auto-apply panel shows applied / needs your answer / apply on company site
phone ◀── Track tab shows every application, its Q&A, Gmail replies, your notes
```

## Step by step

### 1. You tap on the phone

Reports → a worldwide report → **auto-apply**. The panel shows:

* how many LinkedIn postings the report has and how many are not requested yet,
* a tally of what already happened (`3 applied`, `1 needs your answer`, …),
* **Apply to all (N)** and **Apply to selected (N)** - tap rows to tick them,
* one row per posting with its company, location, resume match and a status chip
  (`new`, `queued`, `applied`, `needs your answer`, `apply on company site`, `error`, …),
* **Questions waiting for you** - screening questions the agent could not answer from your profile,
  with a box or a dropdown each and a **Send answers** button,
* when the PC last checked in and how many it applied today.

Only LinkedIn postings are listed (they are the ones the Easy Apply walker can do). Jobs marked
"not a fit" by the search are left out. Everything else in the report (Indeed, company boards,
Seek, …) stays manual: open the report and tap its Apply button.

Reports made before auto-apply existed have no job list attached; the panel says so and asks you
to run the search again.

### 2. The request is queued on GitHub

The tap calls the GitHub API with your fine-grained token and starts the
**Auto-apply request (phone)** workflow (`.github/workflows/apply.yml`) with
`action=apply`, the report id and the job ids (or `all`). The workflow runs
`site/tools/run_apply_queue.py`, which encrypts the request with the site passphrase
(`SITE_PASSPHRASE` secret) and commits it to `data/apply/queue/` on `gh-pages`.

That is all GitHub does. The same workflow carries three other request kinds from the phone:

| `action` | Sent from | What it carries |
| --- | --- | --- |
| `apply` | auto-apply panel | report id + LinkedIn job ids |
| `answers` | auto-apply panel, "Questions waiting for you" | `{question: answer}` |
| `profile` | Track tab, "My answers" form | CTC, phone, notice period, skill years, Yes/No answers |
| `notes` | Track tab, an application | your status and notes for that application |

### 3. The PC carries it out

`site\phone_apply.bat` runs `site/tools/phone_apply.py` (with the Naukri screener's venv).
`site\schedule_phone_apply.ps1` registers it as a hidden Windows scheduled task every 30 minutes
(`-Every`, `-Limit` to change; `-Remove` to stop). Each run:

1. refreshes the local `gh-pages` clone and reads `data/apply/queue/*.enc`;
2. **answers** → written into the Naukri screener's `data/jobs/questions.yaml`, exactly as if you had
   typed them in its dashboard, so they are reused for every later application;
3. **profile / notes** → saved through the dashboard's own save functions;
4. **apply** → the report's postings (`data/jobhunt/<report>.jobs.enc`) become cards for the
   screener's applier: same Easy Apply walker, same answers, same pacing (a minute or more
   between applications), same daily LinkedIn cap from `Profile_Naukri_Screener-main\jobs.yaml`
   (`linkedin_max_applies_per_day`), same applications log - entries are tagged `phone`;
5. writes `data/apply/status.enc`: every requested posting's outcome, the requests' progress,
   the screening questions that are waiting for you, applied-today count and the cap;
6. writes `data/apply/profile.enc`: what the PC dashboard shows (answers form, answer bank,
   every application with its questions, answers, Gmail replies and your notes);
7. moves finished requests to `data/apply/done/` and pushes - only when something changed.

A request is not done in one go. At most `--limit` postings (default 5) are applied per run; a
request for 60 postings stays in the queue and is continued every 30 minutes until every posting
is settled, while the daily cap still bounds the total. So "Apply to all (60)" is safe to tap - it
is spread over hours or days, the same way the screener's own runs are.

The PC must be on and you logged in (lock screen is fine): the headless browser needs a desktop
session. Nothing appears on screen; output goes to `Profile_Naukri_Screener-main\logs\scheduled.log`.

### 4. What comes back

Open the panel again (or refresh the Track tab). Statuses per posting:

| Chip | Meaning |
| --- | --- |
| `new` | not requested yet |
| `queued` | requested, the PC has not got to it yet |
| `applied` | Easy Apply completed |
| `needs your answer` | the form asked something not in your profile; answer it in the panel and the PC re-applies on its next run |
| `skipped (your rule)` | a question you marked "skip - never answer" |
| `applied earlier / closed` | already applied through the screener, or the posting closed |
| `apply on company site` | no Easy Apply - the posting redirects to the employer's own site; do it by hand from the report |
| `unconfirmed` | the walker finished but LinkedIn did not show the confirmation; check LinkedIn |
| `error` / `form failed` | something broke; the row can be requested again |

The **Track** tab (`#track`) shows the fuller picture: your answers form, the questions waiting,
and every application (phone or PC) with its Q&A, Gmail replies and your own status and notes.
Edits made there travel back the same way (`apply.yml` → queue → PC) and are saved as the dashboard
would save them.

## Privacy and safety

* The repo is public, so every request, status and profile file is AES-256-GCM encrypted with
  your passphrase before it is committed. Without the passphrase the site shows nothing readable.
* The GitHub token on the phone is fine-grained, this repo only, Actions read+write. It is sent
  only to `api.github.com`.
* LinkedIn cookies never leave the PC. GitHub never touches LinkedIn.
* The PC applies at the screener's pace and daily cap; the phone cannot override either.
* `phone_apply.bat --dry-run` shows what a run would do without applying or pushing.

## Setup checklist

1. `site\setup_phone.bat` once (passphrase, secrets, `gh-pages`, Pages URL).
2. On the phone: Settings → passphrase + token → Save; add the page to the home screen.
3. Naukri screener set up on the PC with a LinkedIn login that works for `apply`.
4. `powershell -ExecutionPolicy Bypass -File site\schedule_phone_apply.ps1` once, on the PC.
5. Run a worldwide search from the phone; when the report appears, tap **auto-apply**.

## Files

| File | Role |
| --- | --- |
| `site/index.html` | the panel (`openApply`, `renderApply`, `requestApply`) and the Track tab |
| `.github/workflows/apply.yml` | the request workflow the phone starts |
| `site/tools/run_apply_queue.py` | encrypts the request and commits it to the queue |
| `site/tools/phone_apply.py` | PC poller: applies, publishes status and profile |
| `site/phone_apply.bat` | runs the poller with the screener's Python |
| `site/schedule_phone_apply.ps1` | schedules the poller every 30 minutes |
| `site/tools/vault.py` | the encryption both sides use |
| `Profile_Naukri_Screener-main/` | the Easy Apply walker, answers, pacing, cap, dashboard |
