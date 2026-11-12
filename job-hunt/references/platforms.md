# Platforms

How each source is fetched, what it covers, and where it tends to break. Adapters live in `scripts/jobbot/sources/<key>.py`. Verified working on 2026-09-10.

## Direct sources (no key)

| Key | Platform | Countries | Method | Notes |
|---|---|---|---|---|
| linkedin | LinkedIn | all | Guest API `jobs-guest/jobs/api/seeMoreJobPostings/search` (HTML cards, 10/page); details via `jobs-guest/jobs/api/jobPosting/<id>` | Uses `f_E` experience codes and `f_TPR` recency. Throttles if hammered, keep `--interval` ≥ 0.8s. |
| seek | Seek AU/NZ, JobsDB TH/HK, JobStreet SG/MY | AU, NZ, TH, HK, SG, MY | JSON `/api/jobsearch/v5/search` with `siteKey` + `locale` | Very reliable. `v4` endpoints are gone (404). |
| xing | XING | DE, AT, CH | HTML `xing.com/jobs/search`, `article[data-testid=job-search-result]` | Styled-components class names change, selectors use stable prefixes. |
| arbeitnow | Arbeitnow | DE | JSON `api/job-board-api` (no search, filtered client-side) | Mostly German-language postings. |
| duunitori | Duunitori | FI | JSON `api/v1/jobentries?search=` | Search is AND per word, bot also queries single strong terms. |
| tecnoempleo | Tecnoempleo | ES | HTML listing `ofertas-trabajo/?te=`, `div.p-3.border.rounded` cards | IT-only board, dates dd/mm/yyyy. |
| infojobs | InfoJobs | ES | HTML results, only ~5 cards server-rendered per page | Paginated to compensate. May show a bot check occasionally. |
| wellfound | Wellfound | all | `/role/l/<role-slug>/<country-slug>` pages, jobs in `__NEXT_DATA__` apolloState | Unknown role slugs redirect to a generic location page, so there's a `software-engineer` fallback plus relevance filter. |
| tokyodev | TokyoDev | JP | HTML `/jobs` grouped by company (no search) | English-speaking roles. Tags include salary and "No Japanese required". |
| japandev | Japan Dev | JP | HTML `/jobs?page=N`, `li.job-item` | Shows Japanese-level tags. |
| daijob | Daijob | JP | HTML `en/jobs/search_result?keywords=`, `article.job-card` | Bilingual jobs, includes Japanese level. |
| wantedly | Wantedly | JP | JSON `api/v1/projects?q=` | Mostly Japanese-language posts. |
| jobthai | JobThai | TH | `__NEXT_DATA__` apolloState `searchJobs(...)` | Salary in THB. |
| themuse | The Muse | all (city lists in config) | JSON `api/public/jobs?location=` (no keyword search) | Mostly large companies. |
| landingjobs | Landing.jobs | EU | JSON `api/v1/jobs?q=` | Country from `locations[].country_code`, shows relocation flag. |
| relocateme | Relocate.me | all | HTML `/international-jobs?page=N`, country from URL path | Jobs with relocation support. |
| instahyre | Instahyre | IN | JSON `api/v1/job_search?q=` | Only used when India is requested. |
| remotive, remoteok, jobicy, workingnomads | Remote boards | Remote tab | JSON feeds | `remote_util.assign_country` maps "Europe", "APAC", "Worldwide", city names to the user's countries, and drops US-only jobs. Jobicy's `geo` param is ignored server-side, so location filtering is client-side. |
| himalayas | Himalayas | Remote tab | JSON `jobs/api/search?q=&page=` (no key) | ~100k remote postings; `locationRestrictions` goes through `assign_country`; seniority kept in `extra`. |
| weworkremotely | We Work Remotely | Remote tab | RSS per category (programming, full-stack, back-end, front-end, devops) | Titles are `Company: Role`; `region` goes through `assign_country`. |

## Keyed sources (enabled when env vars exist)

| Key | Env vars | Notes |
|---|---|---|
| adzuna | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Free at developer.adzuna.com. Covers DE, NL, ES, AU, IN, SG, GB, … (not FI/JP/TH). |
| jooble | `JOOBLE_API_KEY` | Free at jooble.org/api/about. All countries. |
| jsearch | `RAPIDAPI_KEY` | JSearch on RapidAPI (Google for Jobs), endpoint `/search-v2`. Surfaces Indeed/Glassdoor/LinkedIn postings with apply links. Free plan ~200 calls/month, so calls are capped per day (`JSEARCH_DAILY_MAX`, default 6). |
| firecrawl | `FIRECRAWL_API_KEY` | Runs the fallback `site:` queries automatically. |

## Blocked for scripts (links + web-search fallback)

| Platform | Why | Fallback |
|---|---|---|
| Indeed (all country domains) | "Security Check" page (403) | direct link + `site:<cc>.indeed.com` with `viewjob` URLs |
| Glassdoor | 403 security page | direct link + `site:glassdoor.com` with `job-listing` URLs |
| Naukri | API answers `recaptcha required`, SSR page has no jobs | direct link + `site:naukri.com` with `job-listings` URLs |
| StepStone | Akamai "Access Denied" | direct link + `site:stepstone.de` |
| Hirist | page renders jobs client-side, API host not reachable | direct link + `site:hirist.tech` with `/j/` URLs |
| Jobly (FI), CareerCross (JP) | Cloudflare challenge | direct link + site query |
| GaijinPot (JP), Nationale Vacaturebank (NL) | Access Denied | direct link + site query |
| Jora (AU) | Works for a few pages, then challenges | direct link + site query |
| Bundesagentur Jobsuche (DE), EURES | API keys/endpoints rotated (403/404) | direct links only |

## Debugging a source

```bash
python scripts/job_bot.py selftest --countries DE --role "python developer"
python scripts/job_bot.py search --role "python developer" --countries DE --sources xing --details 0 --out ./dbg
```

The per-source status table in `run.log` and the report's "Sources" panel show `ok / blocked / error` per country with the error text.

## Career OS directive V2.0: platform modes (added 2026-11-11)

Source: `../../career/career_profile.json` -> `platforms` and `../../career/CAREER_OS_DIRECTIVE.md` section 5. `scripts/jobbot/compliance.py` reads that file: `mode(platform)`, `automation_allowed(platform)` (True / False / None = not evaluated), `may_automate(platform)` (True only on an explicit true), `platform_for_url(url)`. `verified_on` is null for every platform today: nobody has recorded reading the current terms yet.

| Platform | Mode | Automation allowed |
|---|---|---|
| linkedin | manual_assist | no |
| greenhouse | automation_permitted | yes (public Job Board API; a human confirms the final submission when declarations, eligibility, salary or legal answers are involved) |
| lever | automation_permitted | yes (public Postings API; same confirmation rule) |
| ashby | evaluate | no |
| company_career_sites | evaluate_per_site | not decided |
| naukri, indeed, glassdoor | links_only | no |
| instahyre, wellfound, foundit, cutshort, relocate_me, wearedevelopers | evaluate | not decided |

Nowhere: CAPTCHA bypass, rate-limit evasion, misrepresenting qualifications.

### Open conflict, left as it is pending the owner's decision

The compliance helper is **advisory only**. No code path calls it, and nothing was disabled, removed or gated when the directive was added, because the owner also asked that current behaviour be kept. These existing features do not match the modes above:

1. **LinkedIn guest-endpoint source** (`scripts/jobbot/sources/linkedin.py`, key `linkedin`, on by default). It sends logged-out HTTP GETs to `linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` and `.../jobPosting/<id>` and parses the returned HTML cards. No login, no cookies, no account, no browser. It is still automated reading of LinkedIn search results, which the directive lists under "does not scrape ... search results" for LinkedIn.
2. **Apify LinkedIn source** (`scripts/jobbot/sources/apify.py`, key `apify-linkedin`, only with `APIFY_TOKEN`). A third-party actor scrapes LinkedIn job listings, and the job poster's name and profile link, on the bot's behalf.
3. **LinkedIn Easy Apply** (`scripts/jobbot/autoapply.py` -> `Profile_Naukri_Screener-main/naukri/jobs/linkedin_apply.py`, reached by `job_bot.py apply` and `run --apply-found`). With `--yes` it drives a Playwright browser on the owner's saved, logged-in LinkedIn session, opens each posting, fills the Easy Apply dialog and clicks "Submit application". Without `--yes` it is a dry run that opens the pages and clicks nothing. This is the directive's "auto-submitting LinkedIn applications" and "Playwright ... automation on linkedin.com".
4. The same `apply` pass also sends every non-LinkedIn posting URL (other boards, company sites) to the screener's company-site form filler, whatever the platform's mode above (naukri / indeed / glassdoor are `links_only`, ashby is `evaluate`).
5. The links-only platforms are already handled as links by this bot's search (see "Blocked for scripts" above); the Naukri screener project next door automates Naukri itself, which is outside this file.

To bring the bot in line, the natural switch points are: drop `linkedin` / `apify-linkedin` from the selected sources in `job_bot.py: do_search` when `compliance.may_automate("linkedin")` is false (the fallback already builds LinkedIn search links for the report), and skip `linkedin_cards` in `autoapply.apply_run` on the same test. Neither is wired in.
