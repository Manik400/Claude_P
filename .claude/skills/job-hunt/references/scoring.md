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
