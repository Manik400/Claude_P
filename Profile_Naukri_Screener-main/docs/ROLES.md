# Role packs

Everything in this toolkit is field-agnostic except three things: which
keywords to search, which words mean *this is my field*, and which skills to
count across ten job descriptions. Those three live in `roles/*.yaml`, so
switching the whole toolkit from testing to security is one line of config.

```yaml
# jobs.yaml
role: cybersecurity
```

```bash
python main.py --roles     # what is available, and which one is active
```

```
  Active role: qa-automation   (set `role:` in jobs.yaml to change it)

   cybersecurity    Cyber Security
                    84 skills (Language 11, Defensive 9, Offensive 9, ...)
                    seeds: Cyber Security Analyst, SOC Analyst, ...

   developer        Software Developer
                    84 skills (Language 11, Process 7, Infrastructure 6, ...)
                    seeds: Software Engineer, Backend Developer, ...

*  qa-automation    QA Automation / SDET
                    95 skills (Automation 15, Process 14, Language 11, ...)
                    seeds: SDET, QA Automation, Automation Test Engineer, ...

   support          Technical / Application Support
                    77 skills (Process 14, Language 11, Infrastructure 6, ...)
                    seeds: Technical Support Engineer, Application Support, ...
```

## Shipped packs

| `role:` | Covers |
| --- | --- |
| `qa-automation` | QA, SDET, test automation, manual and performance testing |
| `developer` | backend, frontend, full stack; frameworks, system design, CS fundamentals |
| `support` | L1–L3 technical, application and production support; service desk, NOC |
| `cybersecurity` | SOC, VAPT, GRC and security engineering |

Every pack inherits `roles/_common.yaml`, which holds the ~50 skills that turn
up in adverts for all four — Git, Docker, Linux, SQL, cloud, Agile, JIRA. A
pack only describes what makes its field different, which is why the four
shipped files are short enough to read in one sitting.

## What a pack decides

Three separate things, and it is worth knowing which is which, because when a
scan comes back wrong the fix is usually in only one of them.

**1. What gets searched and what gets thrown away.** `seed_keywords` and
`searches` become your queries when `jobs.yaml` lists none. `must_have_any` is
the gate: a job that mentions none of those words is dropped before scoring
ever runs. `exclude_title_keywords` drops on the title alone.

**2. How jobs are scored.** `synonyms` folds spellings together before
comparison, so "CI/CD", "CICD" and "continuous integration" score as one thing
rather than three misses. Which spellings mean the same job is a fact about a
field: `sdet → software development engineer in test` is right for a tester and
meaningless to a SOC analyst, who needs `vapt` folded instead.

**3. What the interview-prep module counts.** `lexicon` is the vocabulary the
skill matrix is built from. It is matched against the ten highest-scoring job
descriptions by exact term matching — arithmetic, not a model's opinion — and
the counts decide what you are told to study first.

That last one is why a generic lexicon would be worse than a narrow one. Asked
to extract skills freely, a model pulls "communication" and "stakeholder
management" out of every advert and buries the three tools that actually decide
the interview.

## Writing your own

Copy the closest shipped pack and edit it:

```bash
cp roles/developer.yaml roles/data-engineer.yaml
# edit it, then in jobs.yaml:  role: data-engineer
python main.py --roles          # confirm it loads and looks sane
```

The filename is the name you put in `jobs.yaml`. Files starting with `_` are
treated as shared includes and are not offered as roles.

### The format

```yaml
label: Data Engineer                 # shown in --roles and in prompts
primary_role: Data Engineer          # the role named on the study page

# Fallback search terms, used when jobs.yaml lists no searches of its own.
seed_keywords: [Data Engineer, ETL Developer, Big Data Engineer]

# Ready-made searches. Copy these into jobs.yaml and set your own locations.
searches:
  - {keyword: Data Engineer, location: null}     # null = all of India
  - {keyword: ETL Developer, location: remote}

# The "is this even my field" gate. A job mentioning none of these is dropped
# before scoring. MERGED with _common.yaml's list.
must_have_any: [data engineer, etl, data pipeline, big data]

# Dropped on the title alone. MERGED with _common.yaml's list.
exclude_title_keywords: [data entry, sales]

# Folded together before scoring compares anything.
synonyms:
  etl: extract transform load

# Terms whose bare form is too common to trust a loose match on.
tight_terms: [etl, dag, olap]

# Appended to every interview-question prompt. Optional; say what a good
# question set for this field actually weights.
interview_focus: >-
  Weight questions toward pipeline failure recovery, schema evolution and the
  cost of a design choice at volume.

# The skill vocabulary. This is the bulk of a pack.
lexicon:
  Airflow:
    category: Orchestration
    aliases: [airflow, apache airflow, dag, dags]
  Spark:
    category: Processing
    aliases: [spark, pyspark, apache spark, databricks]
```

**Canonical name** (the `Airflow:` key) is what the study page and the prompts
print, so write it the way people say it out loud.

**`category`** groups the skill on the study page. Invent your own; they are
labels, not an enum.

**`aliases`** is every spelling a recruiter might type, lowercase. Matching is
case-insensitive and uses word boundaries, so `java` will not match
`javascript` and `api` will not match `rapid`. A skill with no aliases can
never match and is dropped with a warning.

There is a shorthand if you are typing a lot of them — first item is the
category, the rest are aliases:

```yaml
lexicon:
  Kafka: [Streaming, kafka, apache kafka]
```

### Inheritance

`must_have_any`, `exclude_title_keywords` and `tight_terms` are **merged** with
`_common.yaml`, de-duplicated, common first. `synonyms` and `lexicon` are
**layered**: a name defined in both takes your pack's definition, in the common
file's original position. So redefining `Python` in your pack to add scripting
aliases replaces the common entry rather than fighting it.

Set `extends: none` at the top of a pack to inherit nothing at all. You will
then need to list Git, Linux and the rest yourself, which is rarely what you
want.

## Tuning a pack against real scans

The first scan is the diagnostic. Run a dry run and read the report:

```bash
python main.py --jobs        # sends nothing
```

- **Too few results, or obviously wrong ones** — `must_have_any` is too narrow
  or too wide. This gate runs before scoring, so anything it drops never
  appears in the report at all.
- **Right jobs, low scores** — the `lexicon` is missing the terms these adverts
  actually use. Open one JD, find the skills you have that scored nothing, and
  add them as aliases.
- **Junk titles surviving** — add to `exclude_title_keywords`. The security
  pack drops `security guard` for exactly this reason; the developer pack drops
  `mechanical`, `civil` and `site engineer`, all of which match "engineer".
- **Study page full of Gaps for things you have done** — the lexicon term is
  right but your resume never uses that word. Fix the resume, not the pack: a
  recruiter's keyword search has the same problem.

A pack is data. Editing one costs nothing and nothing else has to change.

## Sharing a pack

If you write a good one, it is a single self-contained file — send it to
whoever else does that job and they drop it in `roles/` and set one line. That
is the whole reason the packs are files rather than code.
