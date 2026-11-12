# Match score and experience fit

Implemented in `scripts/jobbot/scoring.py` and `scripts/jobbot/experience.py`.

## Score (0–100)

When the job text names at least two known skills:

| Part | Weight | What it measures |
|---|---|---|
| Skill coverage | 45% | Half "share of distinct job skills found in the resume", half "share of skill mentions covered" (skills repeated in the posting count more). Platform tags count double. |
| Text similarity | 25% | TF-IDF cosine between resume and job text, scaled so 0.30 cosine = full marks. |
| Title alignment | 15% | Share of the job title's content words (excluding developer/engineer/senior/junior) that appear in the resume. |
| Experience fit | 15% | fit 1.0 · over 0.7 · stretch 0.65 · unknown 0.55 · too senior 0.15 |

When the job names fewer than two skills (usually no description was fetched), the score falls back to 45% similarity, 35% title alignment, 20% experience fit, and the card says "title only".

Confidence: `high` with a full description (>400 chars), `medium` with skills but a short text, `low` for the fallback formula.

Skills come from `assets/skills_vocab.txt` (one per line, `canonical | alias | alias`). Add domain skills there if the user's field is missing (e.g. medical devices, SAP modules). Matching is case-insensitive and accent-insensitive, and respects boundaries so `c` doesn't match `c++` and `java` doesn't match `javascript`.

## Experience parsing

`parse_experience` finds "N years", "N-M years", "N+ years" and translations (Jahre, jaar, años, vuotta, 年, ปี, …) when experience-related words are nearby. Company-age phrases ("founded 12 years ago") are ignored. "Minimum/at least/mindestens/mínimo/以上" turn "N years" into "N or more".

If no number is found, the title's seniority word sets a default range: intern 0, junior 0–2, mid 2–5, senior 5+, lead/principal/staff/architect 7+.

## Fit

With user experience `U` and requirement `lo..hi`:

- **fit**: `U ≥ lo` and (`hi` unknown or `U ≤ hi + 2`)
- **over**: `U > hi + 2`, or an internship when `U > 1`
- **stretch**: `lo − U ≤ 2`
- **no** ("too senior"): `lo − U > 2`, dropped unless `--fit all`
- **unknown**: nothing stated

`--experience 2-4` uses the midpoint, 3.

## Career OS directive V2.0 (added 2026-11-11)

Source: `../../career/CAREER_OS_DIRECTIVE.md` section 7 and `../../career/career_profile.json` -> `match_weights`. The formula above is NOT changed by this section; this records the target and how today's score relates to it.

Target weights:

| Part | Target | Where it is today |
|---|---|---|
| Technical compatibility | 30% | Skill coverage (45%) + text similarity (25%) = 70% of the current score |
| Experience compatibility | 20% | Experience fit (15%) |
| Role relevance | 15% | Title alignment (15%); the title relevance filter also runs before scoring |
| Location and eligibility | 15% | Not in the score. Handled by filters: `--countries`, `--relocation strict / visa / any` |
| Compensation | 10% | Not in the score. Handled by the `--min-salary` floor and the pay badge on the card |
| Career growth | 10% | Not measured anywhere |

So the current 45 / 25 / 15 / 15 formula covers three of the six target parts and over-weights technical match (70% against a target of 30%). Moving to 30 / 20 / 15 / 15 / 10 / 10 needs per-job location, compensation and growth sub-scores that the bot does not compute yet; until then scores are comparable with earlier runs and the three missing parts stay as filters.

Changes that did land with the directive (in `scripts/jobbot/experience.py`):

- A posting with a "senior" title and no stated number is **stretch**, not **no**. Before 2026-11-11 the title's default range (senior = 5+) made it "no" for anyone more than 2 years short. A stated number still decides: "Senior Engineer, 6+ years" is "no" for a 2.2-year candidate. Lead / principal / staff / architect titles keep their 7+ default.
- `exp_class(fit, exp_min, exp_max)` adds the directive's class next to the fit label: A (fit, requirement stated), B (unknown, or fit from the title only, or over), C (stretch), D (no). "over" is B because the posting asks for less than the candidate has, so experience is no barrier; the fit label still says Overqualified. No class is set when the run was given no `--experience`.
- Wording such as "flexible" or "or equivalent experience" is not detected; such postings are classed from their stated number like any other.

Note on `--experience 0-3`: a range says which jobs to search for, not how experienced the candidate is. `job_bot.py` used to turn it into its midpoint (1.5 years), which labelled every "2-3 years" posting stretch (class C). Since 2026-11-11 `experience.candidate_years` uses the real figure from `career/career_profile.json` (2.2) whenever it lies inside the range, so "2-3 years" is fit (class A) and 4+ is stretch (class C). A range that does not contain the real figure still uses its midpoint, and a single figure (`--experience 2.2`) is used as given. `careers_bot.py` keeps the range and compares a posting's minimum with its top (3).
