# Getting started

For anyone setting this up on their own machine and their own Naukri account.
Budget about twenty minutes for the first run, most of it spent editing your
own config rather than waiting on anything.

The order below matters. Each step needs the one before it.

---

## Before you start

- **Python 3.9 or newer** and **Git**.
- **A Naukri account you already use.** This does not create accounts, and it
  does not scrape anyone's profile but yours.
- **A machine you can leave logged in.** Naukri serves "Access Denied" to
  headless Chromium, so a real browser window opens while the tools work. That
  is not a bug you can configure around.

Read [SAFETY.md](SAFETY.md) before you turn on anything that submits. The short
version: every command defaults to a dry run, applications are sent in your
name, and it is worth knowing what gets sent before it is sent.

---

## 1. Install

```bash
git clone https://github.com/Sagar8633/Profile_Naukri_Screener.git
cd Profile_Naukri_Screener

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

## 2. Pick your role

This is the single most important line of configuration in the project. It
decides which searches run, which jobs are thrown away before scoring, and
which skills the interview-prep module counts.

```bash
cp jobs.example.yaml jobs.yaml
python main.py --roles
```

Then set one line in `jobs.yaml`:

```yaml
role: developer          # or support, cybersecurity, qa-automation
```

| You do | Use |
| --- | --- |
| Backend / frontend / full-stack development | `developer` |
| Technical, application or production support; service desk; NOC | `support` |
| SOC, VAPT, GRC, security engineering | `cybersecurity` |
| QA, SDET, test automation | `qa-automation` |

Doing something else? [docs/ROLES.md](ROLES.md) covers writing your own pack —
it is one YAML file and no code.

Leave the rest of `jobs.yaml` alone for now. Every key is optional and the
defaults come from your role pack and your own profile.

## 3. Log in, once

```bash
python main.py --login
```

A real browser opens and waits for you to sign in by hand. Your password never
enters this codebase, and OTP and captcha work because a human is there.

Cookies land in `data/state.json`. **That file is your login** — it is
gitignored, and it should be treated like a password. Sessions last a few
weeks; when commands start saying `Saved session has expired`, run this again.

## 4. Extract your profile

```bash
python main.py --extract
```

Writes `data/profile.json` (structured fields), `data/profile.txt` (the raw
page text) and `data/profile.png` (a screenshot). Everything downstream scores
jobs against this, so it has to happen before any scan.

The summary printed afterwards flags every field that came back `MISSING`. One
or two is normal. Half the fields missing means Naukri reshipped its markup —
see "When a selector breaks" in the main README.

## 5. Add your resume

The interview-prep module reads a plain-text resume to decide which skills you
can honestly claim. Two ways to give it one:

**Generate it here** (also produces an ATS-safe .docx you can send out):

```bash
cp resume/resume.example.yaml resume/resume.yaml
# edit resume/resume.yaml
python resume/build_resume.py
```

**Or bring your own** — drop a `.txt` export of your existing resume into
`resume/`. Use ALL-CAPS section headings (`PROFESSIONAL EXPERIENCE`,
`TECHNICAL SKILLS`), because the loader splits on them.

Why the headings matter: a skill described in an experience bullet counts as
**Strong** evidence, the same skill sitting only in a comma-separated skills
list counts as **Moderate**, and one that appears nowhere is a **Gap**. Gap
skills get answered as study topics rather than as experience — which is the
whole point, because an answer that opens "in my four years with Kubernetes…"
when you have none is a script for a bad interview.

Both `resume/resume.yaml` and the generated files are gitignored.

## 6. First scan — dry run

```bash
python main.py --jobs
```

Searches, scores everything against your profile, prints a report, **and sends
nothing**. Run this for a few days before going anywhere near `--yes`.

What you are checking in the report:

| What you see | What to change |
| --- | --- |
| Barely any results | `must_have_any` is too narrow — it drops jobs before scoring, so they never reach the report |
| Jobs from the wrong field | `must_have_any` too wide, or wrong `role:` |
| Right jobs, low scores | your role pack's lexicon is missing the words these adverts use — see [ROLES.md](ROLES.md) |
| Junk titles | add to `exclude_title_keywords` |
| It wants to apply to things you would not | raise `auto_apply_min_score` |

Every score comes with its breakdown, so you can always see why a job got the
number it did.

## 7. A spreadsheet, before you automate anything

```bash
python main.py --jobs-export --top 30
```

Writes a ranked `.xlsx` with apply links to `data/jobs/`. Nothing is submitted;
you work through it by hand. This is the honest recommendation for your first
week — you will learn more about your own thresholds from thirty ranked jobs
than from any amount of config tuning.

## 8. Screening questionnaires

Most good matches open a recruiter questionnaire, and the application is not
submitted until it is answered. Before enabling any of that:

```bash
python main.py --jobs-probe
```

Opens exactly one real questionnaire and records its structure **without
answering anything**, so you can see what would be filled in.

Then, in `jobs.yaml`, fill in `skill_years` and `answers`, read every
`answer_rule`, and only then set `answer_questionnaires: true`.

Take the `answer_rules` seriously. They are answers given to recruiters in your
name. The shipped set is a starting point built around one person's situation,
not advice about yours — in particular, rules marked `skip: true` mean "queue
this for me to decide", which is deliberately different from answering "No".

## 9. Going live

```bash
python main.py --jobs --yes --limit 3
```

`--limit 3` caps it at three applications for the run. Read what it sent.
Increase only when you agree with its choices.

## 10. Interview prep (optional, costs model tokens)

```bash
python main.py --interview-prep
```

Takes the top ten jobs from the day's scan, fetches the real job descriptions,
builds a skill-frequency matrix by exact term matching, and generates 100
questions with answers as a study page in `data/interview/`.

Needs either the `claude` CLI installed, or `pip install anthropic` and an
`ANTHROPIC_API_KEY`. Run a scan first — it analyses that scan's results.

## 11. Schedule it (optional)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs_agent.ps1
```

Registers scan runs via Task Scheduler. Default mode sends nothing. Register as
"Run only when the user is logged on" — there is no desktop for the browser
otherwise and it fails every day.

---

## Where things live

| Path | What |
| --- | --- |
| `jobs.yaml` | your search criteria and thresholds — gitignored |
| `roles/*.yaml` | field vocabulary; pick one with `role:` |
| `resume/resume.yaml` | your resume content — gitignored |
| `changes.yaml` | profile rewrites to push back to Naukri — gitignored |
| `data/` | everything extracted or generated — gitignored |
| `scripts/profile_edits.yaml` | data for the one-off profile scripts — gitignored |

The pattern throughout: the **example** is tracked, your filled-in copy is not.
If you add a config file, add its ignore rule in the same commit.

## If you fork this

Check what you are about to publish before your first push:

```bash
git status --porcelain
git ls-files | sort
```

Nothing personal should be in that list. `data/`, `logs/`, `jobs.yaml`,
`changes.yaml`, `resume/resume.yaml`, `scripts/profile_edits.yaml` and every
generated resume are already ignored.

## Common problems

**`Access Denied` / blank pages.** Naukri blocks headless Chromium. Every
command that touches it already runs headed; don't try to force headless.

**`Saved session has expired`.** Run `python main.py --login` again.

**`No profile at data/profile.json`.** Run `python main.py --extract` first.

**`No role pack '<name>'`.** Typo in `role:`. Run `python main.py --roles` for
the valid names.

**Half the profile fields come back `MISSING`.** Naukri changed its markup.
The raw text is still in `data/profile.txt`; selectors live in
`naukri/selectors.py`, which lists several candidates per field so a fix is
usually one line.

**Scan finds only a handful of jobs.** Normal on a 24-hour filter, and it exits
2 rather than erroring. Widen `searches`, or drop `posted_days`.
