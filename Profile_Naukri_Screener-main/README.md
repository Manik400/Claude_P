# Naukri profile toolkit

Extract your Naukri profile, rewrite it with evidence in hand, push the
rewrites back, keep it surfacing in recruiter searches — then scan, score and
apply to the jobs that actually match it, and turn the day's best ten into an
interview study page.

Playwright handles the fetching and the typing. The judgement — what your
headline should actually say — happens between steps 2 and 3, with the
extracted profile in front of you.

**It is not a QA tool.** The field-specific parts — search keywords, the "is
this even my field" gate, the skill vocabulary — live in `roles/*.yaml`, and
switching fields is one line of config. Four packs ship: `qa-automation`,
`developer`, `support`, `cybersecurity`. Writing a fifth is one YAML file and
no code.

| Start here | |
| --- | --- |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | set-up, in order, for your own account |
| [docs/ROLES.md](docs/ROLES.md) | pick a role pack, or write one for your field |
| [docs/SAFETY.md](docs/SAFETY.md) | what it sends in your name, and what it never sends |

## Setup

```bash
git clone https://github.com/Sagar8633/Profile_Naukri_Screener.git
cd Profile_Naukri_Screener

python -m venv .venv
.venv\Scriptsctivate          # Windows
source .venv/bin/activate        # macOS / Linux

pip install -r requirements.txt
python -m playwright install chromium

cp jobs.example.yaml jobs.yaml   # then set `role:` in it
python main.py --roles           # confirm which pack is active
```

Needs Python 3.9+. Everything that touches Naukri runs headed — Akamai serves
"Access Denied" to headless Chromium — so the machine needs a desktop session.

## Pick your role

One line in `jobs.yaml` decides which searches run, which jobs are dropped
before scoring, and which skills the interview module counts:

```yaml
role: developer      # or support, cybersecurity, qa-automation
```

```bash
python main.py --roles
```

```
  Active role: qa-automation   (set `role:` in jobs.yaml to change it)

   cybersecurity    Cyber Security
                    84 skills (Language 11, Defensive 9, Offensive 9, ...)
   developer        Software Developer
                    84 skills (Language 11, Process 7, Infrastructure 6, ...)
*  qa-automation    QA Automation / SDET
                    95 skills (Automation 15, Process 14, Language 11, ...)
   support          Technical / Application Support
                    77 skills (Process 14, Language 11, Infrastructure 6, ...)
```

Each pack inherits `roles/_common.yaml` — the ~50 skills every technical advert
shares — and adds its own field vocabulary on top. Full format and tuning
guidance in [docs/ROLES.md](docs/ROLES.md).

## Use

```bash
python main.py --roles      # which role packs exist, and which is active
python main.py --login      # once: sign in by hand, session is saved
python main.py --extract    # scrape profile -> data/
python main.py --apply      # dry run of changes.yaml
python main.py --apply --yes
python main.py --refresh    # daily nudge
```

Add `--show` to `--extract` or `--refresh` to watch the browser work.
`--apply` is always headed — you want eyes on a live profile being edited.

### 1. Login, once

`--login` opens a real browser and waits for you to sign in. Your password
never enters this codebase; OTP and captcha work because a human is there.
Cookies land in `data/state.json`, which is gitignored and *is* your login —
treat it like a password.

Sessions expire every few weeks. When commands start returning
`Saved session has expired`, re-run `--login`.

### 2. Extract

`--extract` writes three files:

| File | What it is |
| --- | --- |
| `data/profile.json` | structured fields |
| `data/profile.txt` | raw visible text of the page |
| `data/profile.png` | full-page screenshot |

The raw text dump is the safety net. Naukri reships its markup regularly, and
when a selector stops matching, that field degrades to `null` rather than
killing the run — but the words are still in the `.txt`. The summary printed
after a run flags every `MISSING` field.

### 3. Rewrite

Read `data/profile.json`, decide what should change, put it in `changes.yaml`
(start from `changes.example.yaml`). What tends to matter:

- **Resume headline** — 220 chars, the single highest-leverage field. It is
  matched against recruiter search terms. Front-load role and stack; drop
  adjectives like "hardworking" that nobody searches for.
- **Key skills** — ordered; earlier entries weigh more in matching. Mirror the
  exact wording of job postings you want, including the spellings recruiters
  actually type.
- **Profile summary** — recruiters skim two lines. Lead with proof, not
  personality.
- **Employment bullets** — numbers beat duties. "Cut regression suite runtime
  from 40 to 9 minutes" outperforms "responsible for automation testing".

### 4. Refresh, daily

Recruiter search ranks heavily on when a profile was last modified. An
untouched profile sinks below otherwise identical ones edited today.
`--refresh` toggles a trailing full stop on your headline: a real edit that
bumps the timestamp and changes nothing a human reads.

Schedule `daily_refresh.bat` once a day via Task Scheduler. More often gains
nothing and only makes the traffic look automated. Outcomes append to
`data/refresh_log.json` so a silently-broken job is visible.

## Daily job agent

Searches Naukri, scores every result against your extracted profile, applies to
the strong one-click matches and queues everything else for you to read.

```bash
python main.py --jobs          # dry run: search, score, report. Sends nothing.
python main.py --jobs --yes    # live: applies to the strong matches.
```

Criteria and thresholds live in `jobs.yaml`, copied from
[jobs.example.yaml](jobs.example.yaml) — the real file is gitignored because it
ends up holding your expected salary and the answers given to recruiters in
your name. Anything you leave out falls back to your role pack and then to
`data/profile.json`, so the file stays small and does not go stale when you
edit your profile. Run `--extract` first.

### What it does per run

1. Runs each search in `jobs.yaml` plus Naukri's own recommendations for you.
   Breadth beats depth - five distinct queries return more usable jobs than
   paging five deep into one, because page 5 is the tail of a ranking that put
   its best matches on page 1.
2. Scores each job 0-100: skills 45, title 25, experience 15, location 10,
   freshness 5. Hard rejects come first. The breakdown for every job is in the
   report, so when it applies to something you would not have, the reason is
   legible rather than buried.
3. Applies to jobs at or above `auto_apply_min_score` **that one click can
   complete**. Queues everything else above `review_min_score`.

### Why it cannot just apply to 50 a day

Of a typical 30 jobs clearing the quality bar, roughly:

| | |
| --- | --- |
| ~20 | open a recruiter **questionnaire** - the application is not submitted until it is answered |
| ~7 | **apply on the company's own site**, a bespoke form on a different domain |
| ~3 | complete in a single click |

Both blockers are flagged in Naukri's own payload (`questionnaireIdPresent`,
`companyApplyJob`), so they are detected before a page is opened rather than
discovered halfway through applying.

The agent does not answer screening questions. Finishing that drawer means
inventing answers about your notice period, your expected salary or your
willingness to relocate, and those are yours to give. It closes the drawer and
queues the job instead.

So the honest shape of a day is **a handful applied automatically and several
dozen queued**, each one click from done. The queue is
`data/jobs/review_queue.json`, ranked.

### Answering screening questions

Off by default. The agent answers a question only when the answer is a fact
already on record - notice period, current CTC, total experience, current
location and per-skill years come straight off your profile; expected CTC and
willingness to relocate come from the `answers:` block in `jobs.yaml`, in your
words. Anything it cannot ground in a fact it abandons, and the job goes to the
queue for you.

The distinction that matters: asked "how many years of Playwright", it answers
1.25 from your IT-skills table, never 6.25 from your total. Asked "why do you
want to join us", it refuses. `tests/test_answers.py` pins both behaviours.

Before turning it on, capture a real questionnaire:

```bash
python main.py --jobs-probe
```

That opens the highest-scoring queued job with a questionnaire, clicks Apply
once so the drawer appears, records its structure to
`data/jobs/questionnaire-probe.json`, and closes without answering anything.
The application is not submitted - a questionnaire posting only completes once
its questions are answered. Then set `answer_questionnaires: true`.

### A spreadsheet to work through by hand

```bash
python main.py --jobs-export --locations "Pune,Ahmedabad,Gurgaon" --top 30
```

Writes `data/jobs/job-matches-<date>.xlsx`: the top N matches across those
cities, ranked, with the Naukri apply link and a LinkedIn search link on every
row, plus `Applied? / Where / Applied on / Notes` columns as dropdowns.

The tracking columns are the point. Applications go out through two portals and
the same job is listed on both, so without one sheet recording which you used
you either apply twice or skip it on both. Jobs the agent has already applied to
are pre-filled and highlighted, so its work and yours stay in one picture.

A second tab, "Why these ranked", carries each job's score breakdown.

Two things this command does that the daily run does not:

- **City aliases.** Naukri labels a Gurgaon job "Gurugram", so filtering on the
  word you searched for silently drops every job in the city you asked about.
- **Equal weighting for the cities you named.** `preferred_locations` in
  jobs.yaml lists only Pune, which costs every other city 8 points. On a list
  you asked to span three cities that is just a Pune list with extra steps, so
  the export scores all the cities you passed equally.

### LinkedIn

```bash
python main.py --linkedin-login    # once: sign in by hand, session is saved
```

Same shape as the Naukri login and for the same reasons - a real browser, a
human present for 2FA, no password in this codebase. Cookies land in
`data/linkedin_state.json`, which is gitignored and *is* your login.

LinkedIn is stricter about automation than Naukri, and a restriction there
costs you your professional network rather than one job board. So the LinkedIn
side only ever **reads**: it navigates search pages in a visible browser at
human pace and parses what renders. It never applies, messages or connects.

LinkedIn cards carry no skills list and no experience range - the two
components worth 60 of the 100-point Naukri score - so they get their own tab
ranked by **title match** instead. Putting both on one scale would be fake
precision.

### Worldwide, remote first

```bash
python main.py --jobs-export --worldwide --top 60
```

Drops the city filter, searches everywhere, and sorts remote roles to the top.
On LinkedIn it uses `f_WT=2`, LinkedIn's own remote workplace-type filter,
rather than searching for the word "remote" - which also matches on-site jobs
whose description merely mentions remote working.

Naukri is an India-only board, so "worldwide" only really applies to the
LinkedIn side; for Naukri the widest available is a national search.

### Today only: a digest, not a standing list

```bash
python main.py --jobs-export --worldwide --top 60 --posted-days 1 --new-only
```

This is what `jobs_scan.bat` runs, and it answers "what came up since
yesterday" rather than "what is open right now". Two independent cuts:

| Flag | Keeps |
| --- | --- |
| `--posted-days 1` | listings the board says went up in the last 24 hours |
| `--new-only` | jobs that have not appeared on an earlier day's page |

`--posted-days` is asked for at each board's own search filter first - Naukri's
`jobAge` freshness facet, LinkedIn's `f_TPR` window - and then enforced again
on the results. Asking the board matters: a query returns ~20 results ranked by
relevance, not by date, so filtering a stale page afterwards leaves almost
nothing. Both cuts run **before** the top-N truncation, so the shortlist fills
with fresh unseen jobs instead of being trimmed down to a handful.

A Naukri listing with no readable date is dropped - a freshness filter that
keeps undated rows is not a freshness filter. A LinkedIn card with no date is
kept, because LinkedIn already applied its window server-side and shows
"Promoted" where the date would be.

**A short list is the normal result.** Most mornings there are genuinely only a
handful of brand-new 24-hour-old postings. Drop both flags for the full
standing list.

### The daily tracker page

Every export writes `data/jobs/openings-<date>.html` alongside the spreadsheet:
one page per day, every opening from both boards, remote first, with the ones
seen for the first time today marked **NEW**.

Uniqueness comes from `data/jobs/seen.json`, which records the first date each
job id appeared. Without it "today's openings" would be the same standing
postings every morning and the page would be useless by Thursday.

Tick a row when you have applied. Ticks are stored under one shared
localStorage key, so they carry across every day's page instead of resetting.
Filters: new today, remote, one-click apply, not yet applied, and a separate
Posted axis (1 / 2 / 7 days) that combines with the others. When the scan was
itself filtered, the page header says so - otherwise a deliberately narrow day
reads as a thin one.

### Three runs a day

```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1
```

Registers three Task Scheduler entries at 08:52, 13:23 and 18:11 (pass `-Times`
to change them, `-Remove` to unschedule). Off-the-hour on purpose.

The runs share state through `data/jobs/ledger.json`:

- a job applied to in the morning is never re-applied to in the evening
- `max_auto_applies` is a **daily** cap counted across all three runs, so a
  re-run after a failure cannot restart the day's quota
- the queue accumulates across runs and sheds anything later resolved

Each run rewrites `data/jobs/report-<date>.md`, which opens with the line you
actually want:

```
**51 matches found - 4 applied to - 47 waiting for you.**
```

The tasks run interactively rather than in the background, for the same Akamai
reason as `--refresh`: headless Chromium gets "Access Denied".

## AI interview preparation

```powershell
interview_prep.bat                  # or: python main.py --interview-prep
```

Reads the scan you already ran, takes the **ten highest-scoring jobs**, and turns
them into a study page: what those employers collectively want, how your resume
measures against it, and 100 interview questions with answers.

The ten are re-sorted by score here rather than taken in the order the scan wrote
them. Under `--worldwide` the scan sorts remote-first and score second, which is
right for a list you apply from and wrong for choosing what to study — on
2026-08-25 it put a 56.9 remote role at the head of the file and pushed a 62.5
out of the ten. When the two orderings disagree, the run logs which job the scan
would have included, so a page that differs from the morning's terminal output is
explained rather than mysterious.

It is a separate module — `naukri/interview/`, its own data directory, its own
page. It reads `data/jobs/results-<date>.json` and writes nothing the scanner
reads, so a failed prep run costs you nothing but the prep.

### Run the scan first

The prep analyses a specific day's results file. Without one it stops and says
so rather than analysing a stale day. `--date 2026-08-24` analyses an older
scan; `--reuse-jds` re-runs the analysis without re-opening the ten job pages.

**Each scan overwrites that day's results file.** If you have the scheduled
scans running (08:52, 13:23, 18:11), the Top 10 is different after each one, so
run the prep after the last scan you care about — or accept that it captured a
morning snapshot. It does capture one: the ten job records, their full JDs and
the whole analysis are copied into `prep-<date>.json`, so the study page never
goes stale underneath you. `source.results_mtime` and `source.top10_job_ids`
record which version of the scan it was built from, which is how you tell "the
tracker and the prep disagree" from "something is broken".

### It fetches the real JDs

The scan does not have them. Naukri's search endpoint returns `jobDescription`
as a teaser — on one recent Top 10 that ranged from **31 to 811 characters**,
and a 31-character JD analysed for "required skills" produces nothing worth
studying. So the prep opens each of the ten postings and reads the full text
from the job's own API. That is ten navigations, headed, at human pace, and it
roughly doubles the amount of JD text the analysis sees.

### The skill matrix is arithmetic, not a model's opinion

Counting how many of ten documents contain a term is arithmetic, and a language
model asked to do it produces a plausible number rather than a correct one —
which matters when the count is the whole basis of "study this first". So the
matrix is built by matching a curated QA/SDET lexicon, and the model is handed
the finished counts to reason about.

Where a skill appears in *your* resume decides how strong the claim is:

| Match | Means |
|---|---|
| **Strong** | described in your experience bullets or projects, or 3+ stated years |
| **Moderate** | appears only in a skills list — a claim you have made, not one you have described |
| **Gap** | not in the resume or profile at all |

Study order is demand weighted by exposure, so a Critical skill you have never
used outranks a Critical skill you use daily. The interview risk is not in what
you know.

### 100 questions, no concept asked twice

30 basic, 40 intermediate, 30 advanced, generated in six batches — one call for
a hundred questions sags in the middle and starts rewording what it asked at
question forty. Each batch is handed the full text of everything written so far.

Duplicates are then caught in two passes. The first is deterministic: every
question reduces to a **concept key** of an intent (define, troubleshoot,
compare, design, tradeoff…) and a lemmatised subject. These two collide exactly,
despite sharing two words out of seven:

```
"How do you troubleshoot a database connection failure?"
"What steps would you take when a database connection is not working?"
    -> (troubleshoot, {database, connection, fail})
```

The second pass asks the model to find what that missed. Anything flagged by
either is **regenerated**, not dropped — the set stays at 100.

`data/interview/bank.json` remembers every question ever asked, so tomorrow's
run cannot re-derive today's obvious question from the same recurring skill, and
so a question carried forward keeps whatever you marked it.

### It will not invent experience for you

An answer that opens "In my four years with Kubernetes…" is worse than no answer
— it is a script for saying something false in an interview. Gap skills are
answered as study topics with honest framing, and every answer on a Gap skill is
scanned for first-person experience claims before the page is written. Anything
that trips it is regenerated.

The check is tense-aware: *"I would use Kubernetes"* passes, *"I have used
Kubernetes"* does not, and *"I have used Docker, though not Kubernetes"* passes
because it names the gap.

### The study page

`data/interview/interview-prep-<date>.html`, linked from the scanner's nav bar
(**Job Scanner | Top 10 Jobs | Interview Preparation**) and back again.

Answers start collapsed, so you can attempt a question before reading it. Mark
each **Learned** or **Needs revision**; progress is keyed on a hash of the
question text rather than its position, so it survives renumbering and carries
across days. Search, filter by level / skill / status, expand-all, and `j` `k`
`n` `/` for keyboard navigation. The date picker moves between past analyses.

### Validation, before anything is written

Every run checks the fourteen conditions — ten JDs, exactly 30/40/30, every
question answered and traceable to a JD and to your resume, no duplicates, no
invented experience, every Critical/High skill covered — and **regenerates only
the questions that failed**, up to three rounds. The results are printed and
also sit in the page footer, so you can see what passed on the day you study.

### Cost and engine

Generation is roughly ten model calls. By default it shells out to the `claude`
CLI, reusing your existing Claude Code login — no API key, no extra dependency.
For unattended runs set `ANTHROPIC_API_KEY`, `pip install anthropic`, and pass
`--engine anthropic`.

`python main.py --interview-page` rebuilds the HTML from saved data with no
model calls at all.

## When a selector breaks

Every selector lives in [naukri/selectors.py](naukri/selectors.py) and nowhere
else. Each field lists candidates tried in order, plus a heading-based
fallback that keys off visible text like "Resume headline" — class names churn,
the words on the page don't. To fix a broken field, add a candidate there.

## Worth knowing

Automating access is against Naukri's terms of service. This runs against your
own account, from a real browser, at human frequency, which keeps the practical
risk low — but it isn't zero, and the call is yours.

Every destructive command is a dry run until you add `--yes`, questionnaire
answering is off until you turn it on, and nothing is ever answered that is not
grounded in a fact already on your profile. [docs/SAFETY.md](docs/SAFETY.md)
covers what gets sent in your name and which config lines are yours to get
right before going live.

## Layout

```
main.py                CLI
LICENSE                MIT
jobs.example.yaml      template for jobs.yaml (yours is gitignored)
changes.example.yaml   template for --apply
daily_refresh.bat      scheduled profile nudge
jobs_scan.bat          daily scan -> openings page + spreadsheet
interview_prep.bat     Top 10 -> skill matrix + 100 Q&A study page

roles/                 THE FIELD VOCABULARY - one file per career
  _common.yaml         skills every technical advert shares; all packs inherit
  qa-automation.yaml   QA, SDET, test automation
  developer.yaml       backend, frontend, full stack
  support.yaml         L1-L3 technical / application / production support
  cybersecurity.yaml   SOC, VAPT, GRC, security engineering

naukri/
  roles.py             loads a pack, merges it over _common
  selectors.py         every DOM selector
  session.py           manual login, saved session
  extract.py           scrape -> data/
  apply.py             changes.yaml -> live profile
  refresh.py           daily timestamp nudge
  jobs/                search, score, apply, export, tracker page
    config.py          jobs.yaml over the role pack over your profile
    score.py           0-100, with the breakdown attached to every job
    answers.py         questionnaires - only ever from facts on record
  interview/           the prep module - reads jobs/ output, writes its own
    jdfetch.py         full JD text for the Top 10 (the scan only has teasers)
    profile.py         resume + profile, with provenance kept
    skills.py          the skill matrix, built from the active role pack
    engine.py          the model call - claude CLI, or the Anthropic API
    prompts.py         every prompt, in one reviewable place
    dedupe.py          concept keys: the semantic duplicate check
    generate.py        the pipeline
    validate.py        the gate, and what it makes repairable
    page.py            the study page
    store.py           prep files, the date index, the question bank

resume/
  resume.example.yaml  template; resume.yaml and every output are gitignored
  build_resume.py      ATS-safe .docx + the .txt the interview module reads

scripts/               one-offs for profile sections with bespoke dialogs
  README.md            what each one does, and which ones delete things
  profile_edits.example.yaml   their data; your copy is gitignored

docs/
  GETTING_STARTED.md   set-up in order, for your own account
  ROLES.md             the role pack format, and tuning one
  SAFETY.md            what gets sent in your name

data/                  gitignored: session, profile, scans, prep
tests/                 pytest - no network, no model calls
```

## Contributing a role pack

The packs are the part most worth sharing. If you write one for a field that
isn't covered — data engineering, DevOps, business analysis, network
engineering — it is a single self-contained YAML file with no code attached.
Open a pull request with just that file and a line in the table in
[docs/ROLES.md](docs/ROLES.md).

## Licence

MIT. See [LICENSE](LICENSE).
