# Job Hunt bot + Claude skill

Searches ~20 job platforms by role and experience, groups jobs by country, adds an Apply button per job,
and scores each job against your resume (resume stays on your computer).

## Setup (once)
1. Install Python 3.8+ from python.org (tick "Add Python to PATH").
2. Double-click `install.bat` (or run `python -m pip install --user -r requirements.txt`).

## Use without Claude
Double-click `jobhunt.bat` and answer the questions, or run:

    python scripts/job_bot.py run --role "flutter developer" --experience 3 --resume "C:\path\cv.pdf" --open

Reports are saved in `Documents\JobHunt\<date>_<role>\report.html`.
Other commands: `python scripts/job_bot.py -h`.

## How fresh, and from where
Default: **posted in the last 7 days, every platform**.

    --hours 2                 only postings put up in the last 2 hours
    --allow-undated           ...and keep the ones the board gave no time for
    --sources "linkedin,instahyre,seek"     only these platforms (keys or names)

Under a day, a posting whose exact time the board never stated is dropped - nothing shows it is inside
the window. Boards that can filter server-side are told the window (LinkedIn takes it to the second),
and `python scripts/job_bot.py sources` lists every platform, whether it is on, and whether it
publishes posting times.

The platform list lives in **`assets/sites.txt`**, next to the company list: one line per site,
`key | on/off | note`. Switch a site off there and no run touches it; `--sources` (and the phone's
Platforms chips) still override the file for a single run.

API keys for the keyed platforms go in `.env` (see `.env.example` in the repo root), never in these files.

## Applying (LinkedIn Easy Apply)
The report's Apply buttons open each posting. LinkedIn postings can also be applied to for you:

    python scripts/job_bot.py apply --run "%USERPROFILE%\Documents\JobHunt\<run>" --limit 5 --yes
    python scripts/job_bot.py run --like-last --apply-found --yes          what jobhunt_apply.bat runs

This reuses the Naukri screener next door (`../Profile_Naukri_Screener-main`): its LinkedIn login,
its Easy Apply walker, the answers you keep in its dashboard (`dashboard.bat` there), its
`data/jobs/questions.yaml` for questions it cannot answer, its applications log, and its daily
LinkedIn cap - so both projects together never exceed `linkedin_max_applies_per_day`. Run it with
that project's virtualenv (Playwright lives there); `jobhunt_apply.bat` does. The other boards (Seek,
XING, Wellfound, JobsDB, TokyoDev ...) each have their own login and form and stay manual. Every
application shows up in that project's dashboard tagged "via jobhunt", and the report marks the
posting *Applied by agent* / *Needs your answer*. Schedule it with `scripts\schedule_jobhunt.ps1`
(two small batches a day, hidden window). The phone/GitHub Actions run cannot apply - there is no
LinkedIn session on the runner.

## Company career pages (careers bot)
Reads the career pages of the companies in `assets/companies.txt` directly (Greenhouse, Lever, Ashby,
SmartRecruiters, Workable, Recruitee and Workday boards), keeps the jobs that match your role, experience range and countries,
checks each posting for relocation / visa sponsorship (and quotes the sentence), and scores it against your resume:

    python scripts/careers_bot.py run --role "software engineer" --experience 3-5 --countries worldwide --relocation strict --resume "C:\path\cv.pdf"

`--relocation strict` keeps only postings that offer relocation, `visa` also keeps visa sponsorship, `any` keeps all.
From the phone this is the **Careers** tab (see `../site/README.md`).

### Boards that move, and rows that are only a link
A slug in `companies.txt` is right until the company switches board (OpenAI: Greenhouse -> Ashby,
Hugging Face -> Workable, Snowflake -> Ashby...). A row that stops answering is no longer lost with a
404: it is re-resolved during the run, in this order, and the answer cached in `assets/boards_cache.json`:

1. **the link in the row** - a careers URL that names a board (`https://jobs.ashbyhq.com/openai`) wins
   over the `ats`/`board` columns, so pasting the link is how you pin a company for good;
2. **that link's page** - a company's own `/careers` page names the board it embeds;
3. **the company name** - slug variants probed against Greenhouse, Ashby, Lever, SmartRecruiters,
   Workable and Recruitee;
4. **the local model** (Ollama, else the bundled GGUF) - asked which board the company uses;
5. **a LinkedIn company search** - nothing answered, so the report still carries a link you can click.

Guessed boards are asked whose they are before they are accepted (`meta.recruitee.com` answers - with
the jobs of Addis Ababa University). A board pinned by a link is taken as given.

    python scripts/careers_bot.py resolve           check every row, print what is wrong
    python scripts/careers_bot.py resolve --write   fix companies.txt from what answered (keeps a .bak)
    python scripts/careers_bot.py find "<company>"  the line to paste for one company
    python scripts/careers_bot.py check             does every row still answer?

## Use with Claude
Put this folder in `%USERPROFILE%\.claude\skills\job-hunt` (or install `job-hunt.skill`),
then ask Claude e.g. "find python developer jobs in Germany and Japan, 3 years experience, here is my CV".

## Optional API keys (more coverage)
ADZUNA_APP_ID + ADZUNA_APP_KEY, JOOBLE_API_KEY, RAPIDAPI_KEY (JSearch), FIRECRAWL_API_KEY.

**India (and any board that blocks scripts):** `APIFY_TOKEN` rents real scrapers on Apify -
`apify-naukri` (India), `apify-indeed` (60+ countries), `apify-linkedin` (everywhere; also returns the
job poster as a contact). `APIFY_SOURCES` picks which run, default `naukri,indeed`. A search costs a
few cents. Get a token at <https://console.apify.com/account/integrations>.

Store any of these with `python scripts/set_key.py APIFY_TOKEN` (hidden input): it writes `.env`
for the PC, sets the GitHub secret for the phone-triggered runs, and runs `check_keys.py`.
JSearch's free plan is ~200 calls a month, so each day (PC) or run (GitHub) spends at most
`JSEARCH_DAILY_MAX` of them (6 on the PC, repo variable default 4). Apify is paced against the
account's real usage: `APIFY_MONTHLY_USD` (default 4.5, under the free $5) spread over the billing
cycle, and at most `APIFY_DAILY_USD` a day (default monthly / 30); a call is cut to the results the
budget still pays for, or skipped.

## The free local model (optional)
`..i_setup.bat` (repo root) installs a small open model that runs on the CPU - Qwen 3.5 2B via
`llama-cpp-python` and a `bge-small` embedding model, ~1.4 GB downloaded once, no key, no cloud
(`scripts/jobbot/localai.py`). With it installed, every run gets:

* **semantic ranking** - the whole posting is compared with the whole resume, blended into the text
  term of the score (`scoring.py`), so a "test automation lead" no longer looks unrelated to "SDET";
* a **"Fit: ... Gap: ..."** line on the report cards for the top 30 jobs (`LOCAL_AI_SUMMARY_TOP`);
* in the careers bot, a **second opinion** on postings the relocation patterns left as *maybe* /
  *unknown* - accepted only when the sentence the model quotes is really in the posting;
* in the Naukri screener, **screening answers** no rule covers, from your facts sheet only
  (see that README);
* in the careers bot, a **board for a company nothing else could place** - the model names the ATS and
  slug, and the guess is verified against the live board before it is used (`--no-ai-boards` turns
  this off).

Generation is capped per run (`LOCAL_AI_BUDGET_SECONDS`, default 600 s); when the budget is spent
the rest of the run simply goes without. Without the packages nothing changes.

**On GitHub Actions** the same model runs in the phone-triggered searches: set the repo variable
`LOCAL_AI` to `1` (`gh variable set LOCAL_AI --body 1`). The workflow installs the prebuilt CPU wheels,
caches the model files between runs, and reads `LOCAL_AI_MODEL` / `LOCAL_AI_BUDGET_SECONDS` from repo
variables too. The free 4-vCPU runner does about 20-30 fit lines inside the default budget.

## Contacts per company
After every search the best companies are looked up for recruiters, engineering managers and heads
of engineering (`scripts/jobbot/contacts.py`): what the postings themselves reveal (emails, the
LinkedIn poster, the company site) plus, when a key is set, SignalHire (`SIGNALHIRE_API_KEY`, people
by title), Hunter.io (`HUNTER_API_KEY`, named emails + the company's email pattern) and Apollo.io
(`APOLLO_API_KEY`, people with LinkedIn URLs). The result lands in `contacts.json` in the run folder
and on each job (`extra.contacts`), which the phone shows under **Contacts**. Without keys you still
get ready-made LinkedIn / Google people searches per role. `--no-contacts` skips it.
