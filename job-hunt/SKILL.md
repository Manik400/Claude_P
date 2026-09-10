---
name: job-hunt
description: Job search bot that finds openings across many job platforms (LinkedIn, Seek, JobsDB, XING, Wellfound, Instahyre, Tecnoempleo, InfoJobs, Duunitori, TokyoDev, Japan Dev, Daijob, JobThai, remote boards, with Indeed / Naukri / Glassdoor / Hirist / StepStone covered by web-search fallback), filters them by the user's role and years of experience, scores each posting against the user's resume, and produces an HTML report grouped by country with a one-click Apply button per job. Default countries are Germany, Netherlands, Spain, Finland, Australia, Japan and Thailand, and any other country can be added. Use this skill whenever the user wants to find jobs, search openings, look for work abroad, hunt for roles matching their experience, compare jobs across countries, get a job list with apply links, or check how well their CV/resume matches postings — even if they don't say "skill" or "bot", and even for a single country or platform.
---

# Job Hunt

A local Python bot (`scripts/job_bot.py`) does the heavy lifting: it queries ~20 job sources concurrently, dedups, filters by experience, optionally scores against a resume, and writes a self-contained `report.html`. Your job is to collect the search criteria, run the bot, fill gaps for platforms that block scripts, and hand the user the report.

The resume is used **only** to compute a match score, locally. Never upload it anywhere, never paste its contents into web searches, and never submit applications on the user's behalf — the Apply button opens the posting and the user applies themselves.

## 1. Collect the criteria

Get these from the conversation. Ask only for what is missing and matters; don't interrogate.

| Criterion | Needed? | Default |
|---|---|---|
| Role / job title(s) | required | — (several roles → repeat `--role`) |
| Years of experience | strongly recommended (drives the fit filter) | none → fit shown as "unknown" |
| Countries | optional | DE, NL, ES, FI, AU, JP, TH + a Remote tab |
| Resume file (.pdf / .docx / .txt) | optional, only for match scores | no scores |
| Recency | optional | last 30 days (`--days`) |
| Words to exclude / require in titles | optional | none (`--exclude`, `--must`) |

If the user pastes a job description instead of a title, extract the role title and core skills from it and use the title as `--role` (add a second `--role` for a common synonym, e.g. "backend engineer" + "python developer").

Experience accepts `3`, `2-4`, or `5+`. If the user only gives a resume, you may estimate years from its dates — say what you assumed.

## 2. Check dependencies (first run only)

```bash
python -c "import requests, bs4, pypdf, docx" || python -m pip install --user requests beautifulsoup4 pypdf python-docx
```

Python 3.8+ is required. On Windows use `python`; elsewhere `python3` may be needed.

## 3. Run the bot

```bash
python <skill-dir>/scripts/job_bot.py run --role "flutter developer" --experience 3 \
  --countries "Germany,Netherlands,Spain,Finland,Australia,Japan,Thailand" \
  --resume "C:/Users/me/Documents/cv.pdf" --open
```

- A full default run takes roughly 3–8 minutes (polite rate limiting). Run it with a long timeout (10 min) or in the background, and tell the user it's running.
- Output goes to `~/Documents/JobHunt/<date>_<role>/` unless `--out` is given: `report.html`, `jobs.json`, `run.json`, `fallback_plan.json`, `run.log`.
- The last stdout line is JSON with `run_dir` and `report`. Progress goes to stderr.
- `--fit strict` keeps only jobs the user qualifies for; `--fit all` keeps everything (default drops clearly-too-senior roles only).
- `--details 0` skips description fetching (faster, weaker scores). The default fetches the top 40.
- Other sub-commands: `score` (add/replace resume scores on an existing run), `render`, `merge`, `fallback-queries`, `sources`, `countries`, `selftest`. Run `job_bot.py <cmd> -h` for flags.

Countries outside the default list work too (India, Singapore, UK, UAE, Canada, US, Ireland, Poland, Portugal, Sweden, Switzerland, …) — `job_bot.py countries` lists them. India additionally uses Instahyre.

## 4. Cover the platforms that block scripts

Indeed, Glassdoor, Naukri, StepStone, Hirist, Jobly, CareerCross, GaijinPot and a few others return bot checks to scripts. The bot handles them two ways:

1. **Always**: each country tab in the report has one-click "Search directly on" links for them.
2. **When worth it** (the user named one of these platforms, or a country has few results): run the web-search plan yourself.
   - Read `<run_dir>/fallback_plan.json` (or `job_bot.py fallback-queries --run <run_dir> --platforms indeed,naukri`). Each entry has `query`, `platform`, `platform_name`, `country`, `url_must_contain`.
   - Run the queries with whatever web search tool is available (WebSearch, or `firecrawl_search`). Prioritise platforms the user asked for; ~1–2 queries per platform per country is plenty.
   - Keep results whose URL contains `url_must_contain` (that filters out category pages). Parse title/company from the result title (e.g. "Flutter Developer - Gurugram - Qloron Technology - 3 to 5 years").
   - Naukri, Glassdoor, StepStone and Hirist searches usually surface individual postings. Indeed searches mostly return category pages ("Python Developer Jobs in Berlin"), so for Indeed rely on the direct link in the report rather than burning queries.
   - Write them to a JSON list and merge:

```json
[{"title": "Python Developer", "company": "Acme GmbH", "url": "https://de.indeed.com/viewjob?jk=...",
  "country": "DE", "location": "Berlin", "source": "indeed", "source_name": "Indeed",
  "snippet": "result description", "posted": null}]
```

```bash
python <skill-dir>/scripts/job_bot.py merge --run "<run_dir>" --file extra.json
```

`merge` dedups against existing jobs, parses experience, re-scores with the run's resume and re-renders the report. If `FIRECRAWL_API_KEY` is set, the bot runs this plan itself (`firecrawl` source).

Optional API keys unlock more coverage automatically: `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`, `RAPIDAPI_KEY` (JSearch — includes Indeed/Glassdoor listings via Google Jobs). Mention them only if the user wants broader coverage; they are free tiers the user signs up for themselves.

## 5. Present the result

Open the report (`--open`, or share the path) and give a short summary:

- jobs per country (a small table),
- the 3–5 best matches with score, fit and company,
- which sources were unavailable and that direct links are in the report,
- any assumption you made (experience estimated from resume, roles inferred from a JD).

If the host supports publishing HTML artifacts and the user wants a shareable page, the report is self-contained and can be published as-is; otherwise the local file is the deliverable.

The report itself offers country tabs, search, min-score slider, fit/remote/source filters, sort, "Mark applied / Save / Hide" (stored in the browser), CSV export, and light/dark themes.

## How scoring and fit work

Read `references/scoring.md` when the user asks why a job scored the way it did or wants the weights changed. In short: skills overlap (vocabulary in `assets/skills_vocab.txt`, extendable), TF-IDF text similarity, title alignment and experience fit, 0–100. Jobs with no description are scored on title and teaser only and labelled "title only".

Fit labels: **Fit** (meets the stated requirement), **Stretch** (≤2 years short), **Overqualified**, **Too senior** (hidden by default), **Unknown** (posting doesn't state experience).

## When a source breaks

Job sites change markup often. If `run.log` shows a source with `ERROR` or 0 results everywhere, check `references/platforms.md` for how that adapter works, test it with `job_bot.py selftest --countries <cc>`, and fix the adapter in `scripts/jobbot/sources/`. A failing source never stops the run, so a quick fix can wait until the user asks.
