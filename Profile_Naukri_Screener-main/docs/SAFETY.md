# What this sends, and what it never sends

This toolkit edits a live profile and submits real job applications under your
name. That is the point of it, and it is also the reason to read this page
before turning anything on.

## The three defaults that protect you

**Every destructive command is a dry run until you add `--yes`.**

```bash
python main.py --jobs          # searches, scores, reports. Sends nothing.
python main.py --jobs --yes    # submits applications.

python main.py --apply         # prints what it would change. Changes nothing.
python main.py --apply --yes   # writes to your live profile.
```

**Screening questionnaires are off until you turn them on.**
`answer_questionnaires` defaults to `false`, and `jobs.example.yaml` ships with
it off. Run `--jobs-probe` first — it opens one real questionnaire and records
its structure without answering a single field.

**The browser is visible.** Everything that touches Naukri runs headed, because
Naukri serves "Access Denied" to headless Chromium. A side effect worth having:
you can watch what it does.

## What it will never do

- **It never invents experience.** A questionnaire answer is given only when it
  is grounded in a fact already on record — your notice period, current CTC,
  total experience, location, or a per-skill year count you wrote yourself in
  `jobs.yaml`. Anything it cannot ground, it abandons, and the job goes to your
  queue for you to handle. The daily report lists every question that blocked an
  application, so you can add a rule and the next run gets past it.
- **Interview answers never claim skills your resume does not support.** A skill
  the job descriptions want and your resume lacks is marked `Gap` and answered
  as something studied, with honest framing for "have you used it?". This is
  enforced in the prompts and checked again afterwards by
  `naukri/interview/validate.py`.
- **It does not touch anyone else's data.** It reads your profile and public
  job listings. There is no scraping of other candidates.

## What is yours to get right

**`answer_rules` in `jobs.yaml` are answers given to recruiters in your name.**
The shipped set is a starting point built around one person's situation. Read
every rule and change any you disagree with.

The distinction that matters most in that file:

```yaml
- match: "bond|service agreement|surety"
  skip: true        # queue it for me — I will decide per job
```

`skip: true` is **not** the same as answering "No". A bond, a contract role or
third-party payroll may well be acceptable to you for the right job, and a "No"
sent in your name screens you out of it silently. Replace these with a real
answer once you know your own standing position.

Rules are first-match-wins, so traps have to sit above catch-alls. A guard
placed after `comfortable (with|in|to)` never runs, because that pattern
matches "are you comfortable with a 2 year bond" perfectly well.

**`skill_years` is quoted to recruiters as your experience.** Do not round up.
A number here your resume cannot back is a bad interview waiting to happen.

**Your current employer belongs in `exclude_companies`.** Applying to your own
company's listing through Naukri is a conversation you would rather not have.

## Rate and volume

`max_auto_applies` caps applications per day and `max_apply_attempts` caps
attempts, which is not the same number — a run that keeps hitting unanswerable
questionnaires never spends its budget and would otherwise walk your whole
shortlist.

Keep the daily number low. Fifty applications a day is a pattern; it is also
fifty recruiters forming an impression of you at once. The profile refresh is
worth running once a day and no more — more often gains nothing and only makes
the traffic look automated.

## Files that are your identity

These are gitignored and must stay that way:

| File | Why |
| --- | --- |
| `data/state.json` | **this file is your Naukri login** |
| `data/linkedin_state.json` | your LinkedIn login |
| `data/` | your extracted profile, scans, applications, study pages |
| `jobs.yaml` | expected salary, notice period, answers sent in your name |
| `resume/resume.yaml` and generated resumes | your name, phone, email, history |
| `changes.yaml` | your profile rewrites |
| `scripts/profile_edits.yaml` | past employers, projects, expected salary |

Before pushing a fork, check what is actually staged:

```bash
git status --porcelain
git ls-files | sort
```

If a session file ever does get committed, changing the file is not enough —
log out of Naukri in that browser session to invalidate the cookies, then
rewrite the history.

## Terms of service

Automating a job board is against most boards' terms of service, including
Naukri's. This exists because doing your own job search by hand is tedious, not
because anyone granted permission for it. You are responsible for how you use
it on your own account. Keep the volume human, keep the answers true, and read
the report.
