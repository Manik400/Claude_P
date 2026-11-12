# Career OS directive V2.0

Added 2026-11-11. This file **adds** to the rules this project already had; nothing that was
here before is removed. Where an older rule and this file disagree, the section says which wins.
The same settings in machine-readable form are in `career_profile.json` next to this file.

The goal: a significantly better software engineering job, in India or abroad, better pay, and
in time relocation to Germany or another suitable country. Priorities when they pull apart:

**accuracy > reliability > resource efficiency > speed > features**

## 1. Profile

The newest resume is the only source of professional facts. Nothing is invented or inflated.

| | |
|---|---|
| Newest resume | `ResumeTechSpecific/MY_RESUMES/Manik_Goyal_Resume.pdf` (31 Oct 2026) |
| Pipeline master | `ResumeTechSpecific/Outreach/_master/` (23 Oct 2026, one skill behind: no Kubernetes) |
| Experience | 2.2 years (Software Engineer, I2V Systems, since Oct 2024). Written as "2+ years" in prose. |
| Location | Gurugram, India |
| Relocation target | Germany first; also NL, IE, SE, FI, DK, NO, UK, CH, AU |
| German | A1 |
| Open to | India, international, remote |

Skills that may be claimed are the ones in the resume: C#, .NET 8/7, ASP.NET Core, EF Core,
SignalR, Java, Spring Boot, Hibernate, TypeScript, JavaScript, SQL, Angular 18, Flutter,
PostgreSQL, TimescaleDB, PostGIS, Redis, RabbitMQ, MQTT, Kafka, Milvus, LLM / RAG / agentic
workflows, Docker, Kubernetes, GitHub Actions, Linux, AWS, Grafana, Prometheus, microservices,
event-driven architecture, distributed systems, system design.

**React and Python are in the directive's list but not in the resume.** They are skill gaps to
learn, not claims, until the resume names them.

## 2. Experience range and titles (updated requirement)

- Default search range: **0 to 3 years**. This replaces any 0-2 band still configured.
- Search every relevant title, whatever its seniority label: Software Engineer / Developer,
  SE I / II, SDE I / II, Backend, Senior Software Engineer, Senior Backend Engineer, Full Stack,
  .NET, C#, Java, Spring Boot, Distributed Systems, Platform, Cloud, Infrastructure, Application
  Developer, Product Engineer, API Developer, Systems Engineer, and similar.

Discovery rules:

1. Never reject a job because its title contains "Senior".
2. A senior title does not mean 5+ years. Read the stated requirement.
3. Include jobs asking 0-3 years, jobs asking 2-3 years, and jobs that state no experience.
4. Include jobs whose requirement is flexible.
5. Include stretch jobs, clearly flagged. Never drop one silently.
6. Match on responsibilities, stack and real requirements, not on the title.

Every job gets one class, decided from the description:

| Class | Name | When |
|---|---|---|
| A | DIRECT MATCH | stated experience is explicitly compatible with 2.2 years |
| B | STRONG POTENTIAL MATCH | range is compatible or flexible, or nothing is stated |
| C | STRETCH OPPORTUNITY | senior title or slightly higher requirement, work looks achievable |
| D | EXPERIENCE MISMATCH | clearly needs substantially more experience or expertise |

C is always presented, in its own group.

## 3. Freshness and verification

| Age | Label |
|---|---|
| 0-3 days | Very fresh |
| 4-7 days | Fresh |
| 8-14 days | Recent |
| 15-30 days | Older but potentially active |
| over 30 days | Verify before recommending |

Never invent a posting date and never call a job active without evidence. The employer's own
careers page is the preferred check. For each job, where the data exists: is the link live, is it
still accepting applications, is it a direct employer listing or a recruiter's, salary, work
authorisation, sponsorship and relocation. An office in Germany is not evidence of sponsorship.

## 4. Where to look

India: LinkedIn Jobs, Naukri, Instahyre, Wellfound, Indeed, Foundit, Cutshort, company career
sites, Greenhouse, Lever, Ashby. Priority cities: Gurgaon, Delhi NCR, Bangalore, Hyderabad, Pune,
Mumbai, Chennai, Noida, Remote India. Prefer product companies, high-growth tech, established
engineering organisations, global capability centres, international companies with Indian offices.

International: LinkedIn Jobs, Relocate.me, Wellfound, WeAreDevelopers, Indeed, Glassdoor, company
career sites, Greenhouse, Lever, Ashby. Prefer employers that hire from India, sponsor visas, help
with relocation, work in English and consider about 2 years of experience. Worth tracking:
companies with offices in both India and Germany, companies that transfer staff from India to
Europe, German companies recruiting from India.

The lists are a starting point, not a limit.

## 5. Platform compliance

Each platform has its own mode in `career_profile.json` -> `platforms`. Read the platform's
current terms before turning automation on, and record the date in `verified_on`.

**LinkedIn is manual-assist only.** On linkedin.com the system does not run Playwright or
extension automation, does not scrape profiles or search results, does not connect, message, like,
comment, follow, share or apply, does not touch CAPTCHA, rate limits, cookies or sessions, and does
not use extra accounts or stealth tooling. Spacing automated actions out does not make them
allowed. What it does instead: build search URLs and Boolean queries, build recruiter and
hiring-post queries, analyse job text the user supplies, draft connection notes, outreach and
follow-ups, make application checklists, open pages for the user, and track what the user confirms.

Other portals: automation only where the portal's current terms and technical limits allow it.
Nowhere: CAPTCHA bypass, rate-limit evasion, misrepresenting qualifications.

A human confirms the final submission whenever declarations, eligibility, salary, legal answers or
anything uncertain is involved.

## 6. Volume

No arbitrary caps on discovery, local records, analysis, resume comparisons or preparation. Caps
that protect a platform, a mailbox or a paid API stay. Never apply twice to one vacancy, never
send duplicates, never spam, never give an inaccurate answer. The aim is the most legitimate
applications, not the highest count.

## 7. Matching

| Part | Weight |
|---|---|
| Technical compatibility | 30% |
| Experience compatibility | 20% |
| Role relevance | 15% |
| Location and eligibility | 15% |
| Compensation | 10% |
| Career growth | 10% |

Separate scores for skills, experience, responsibilities, seniority, location, work
authorisation, sponsorship, compensation and overall. Every recommendation is explained. A strong
technical match is never rejected over a seniority label.

## 8. Resumes

Variants: .NET / C# Backend, Java / Spring Boot Backend, Full Stack, Distributed Systems, General
Software Engineer, International Software Engineer. A variant only reorders, rewords and trims
facts from the master. The original is preserved; each job gets its own copy and notes.

Per job: analyse the description, extract keywords, compare with the resume, list missing skills,
compute keyword compatibility, pick achievements and the variant, write the summary, the cover
letter where useful and the application answers.

## 9. Recruiters

A major feature. Find the people hiring for relevant roles (technical recruiters, talent
acquisition, engineering recruiters, HR partners, hiring and engineering managers), preferring
those tied to a real open vacancy. Record only what is publicly and lawfully available: name,
company, title, public profile link, hiring post, associated job, country, specialisation, source,
last verified date, outreach status. One message per real job; no mass messaging.

## 10. Tracking

States: DISCOVERED, ANALYZED, SHORTLISTED, RESUME_PREPARED, READY_TO_APPLY, SUBMITTED,
SUBMISSION_VERIFIED, RECRUITER_CONTACTED, INTERVIEW, OFFER, REJECTED, WITHDRAWN.

Clicking Apply is not SUBMITTED. SUBMISSION_VERIFIED needs evidence from the page.

Also stored: company and recruiter details, resume versions, match results, conversations,
follow-up dates, salary, visa and relocation information, skill gaps.

## 11. Models and resources

Machine: Windows, about 32 GB RAM, Intel CPU, NVIDIA MX550 (2 GB VRAM), Intel Iris Xe, Ollama at
`http://127.0.0.1:11434/v1`.

- Code, not a model: DOM interaction, field detection, deduplication, URL validation, database
  work, status tracking, basic parsing, search filtering.
- Small model: job classification, keyword extraction, basic resume matching, simple answers.
- Large model: complex job analysis, resume tailoring, assessments, cover letters, interview
  preparation, strategy, ambiguous decisions.

Never call a model when code can decide. One large model loaded at a time. Cache reusable
analysis, use structured outputs, set timeouts with a fallback, unload idle models, keep context
small. Benchmark CPU-only against GPU-assisted and report measured numbers only.

Browser automation, where allowed: reuse sessions, DOM selectors over screenshots, event-based
waits, bounded concurrency, checkpoints, idempotent steps, duplicate detection, form validation,
verified submission.

## 12. Learning

DSA, C# and .NET internals, Java and Spring Boot, SQL and database internals, distributed
systems, microservices, networking, operating systems, system design (HLD and LLD), AWS, Docker,
Kubernetes, messaging, concurrency, production debugging. The roadmap follows the skills that
keep appearing in relevant job descriptions.

## 13. Safety

No plaintext passwords, no exposed tokens. Structured logs, bounded retries, crash recovery,
validation, backups, tests. Never delete configurations, models, databases, browser profiles or
scheduled tasks without explicit permission.

## The twenty rules in one place

1. Experience is 2.2 years.
2. Default search range is 0-3 years.
3. Search all relevant titles, senior ones included.
4. Never reject on title alone.
5. Show stretch jobs separately.
6. The latest resume is the source of truth.
7. India and Germany first.
8. Search globally.
9. Recruiter discovery is a major priority.
10. Use current information and verify listings.
11. Respect each platform's current rules.
12. No unauthorised LinkedIn automation.
13. No arbitrary internal application limits.
14. No duplicate or spam applications.
15. Never fabricate professional information.
16. Keep CPU, RAM and VRAM use low.
17. No unnecessary model inference.
18. Deterministic code for predictable work.
19. Measure improvements; do not claim them.
20. No destructive change without approval.
