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

## Keyed sources (enabled when env vars exist)

| Key | Env vars | Notes |
|---|---|---|
| adzuna | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Free at developer.adzuna.com. Covers DE, NL, ES, AU, IN, SG, GB, … (not FI/JP/TH). |
| jooble | `JOOBLE_API_KEY` | Free at jooble.org/api/about. All countries. |
| jsearch | `RAPIDAPI_KEY` | JSearch on RapidAPI (Google for Jobs). Surfaces Indeed/Glassdoor/LinkedIn postings with apply links. |
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
