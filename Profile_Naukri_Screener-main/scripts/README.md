# scripts/

One-off tools for the parts of a Naukri profile that have their own dialogs and
no equivalent in `changes.yaml`.

**For everyday edits — headline, summary, key skills — use `changes.yaml` and
`python main.py --apply` instead.** That path is dry-run by default and has
selectors maintained in one place. These scripts are the exceptions: sections
Naukri only exposes through a bespoke modal.

They all type into your **live profile** and none of them have a dry-run mode.
Read what you have configured before running one.

## Setup

```bash
cp scripts/profile_edits.example.yaml scripts/profile_edits.yaml
# edit it, then run whichever script you need
python scripts/add_project.py
```

`profile_edits.yaml` is gitignored — past employers, project write-ups and your
expected salary are personal. Only the example is tracked. Each script reads
one section and refuses to start if that section is missing, so a configuration
mistake stops before a browser opens rather than halfway through a dialog.

## What each one does

| Script | Section it reads | What it does |
| --- | --- | --- |
| `add_past_employment.py` | `past_employment` | Adds previous roles so employment matches your resume |
| `add_project.py` | `project` | Adds an entry to the Projects section |
| `fix_worksample.py` | `work_sample` | Fixes a Work Sample's URL and fills its description |
| `repair_skills.py` | `key_skills` | Keeps an allowlist, **deletes everything else**, adds targets in order |
| `career_profile.py` | `career_profile` | Sets the role you want to be found for, and expected salary |
| `set_total_experience.py` | — argv | `python scripts/set_total_experience.py "6 Years" "3 Months"` |
| `trim_personal.py` | — | Clears doorstep-level address fields from Personal details |
| `apply_summary.py` | — reads `changes.yaml` | Applies the profile summary alone, verifying the dialog first |
| `schedule_jobs_agent.ps1` | — | Registers the scan runs in Windows Task Scheduler |

## Two things worth knowing

**`repair_skills.py` deletes.** It removes every key skill not in your `keep`
list. It refuses to run when both lists are empty, but it will happily empty
your profile if you write a short `keep` list and mean a long one. Key skills
are ordered and earlier entries weigh more in recruiter matching, so `add` is
applied in the order you write it.

**Total experience is a separate field.** Naukri does not derive the
total-experience header from your employment entries, and recruiter search
filters on the header. So after `add_past_employment.py`, run
`set_total_experience.py` or the additions buy you no visibility at all.

## A note on the `assert`s

Several of these check the current value before changing it —
`career_profile.py` refuses to run unless your profile currently shows the role
named in `expect_current_role`. That is not paranoia: Naukri's edit icons are
near-identical between sections, and a mis-click opens a different dialog that
would otherwise be overwritten silently. Delete the `expect_current_role` line
to skip the check.

## Removed

`fix_experience.py` was a one-time migration with its before-and-after values
hardcoded, and it asserted on the author's old numbers — it could not run for
anyone else. `set_total_experience.py` does the same job properly:

```bash
python scripts/set_total_experience.py "6 Years" "3 Months"
```
