"""Every application the agent attempted, with exactly what it said.

Applications go out in your name, so you need to be able to audit each one:
which company, which posting, when, on which board, what happened, and every
screening question with the answer that was given and where that answer came
from - so a wrong one can be corrected at its source rather than guessed at.

    data/jobs/applications.jsonl   one line per attempt, append-only. The
                                   record of truth.
    data/jobs/applications.html    the readable page, rebuilt after every run
                                   and linked from the tracker page.

    python main.py --applications  prints the latest attempts and rebuilds
                                   the page.

Each answer carries a `fix` hint: the file or profile field that produced it.
Correct it there and every later application uses the correction.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("naukri.jobs.applications")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"
LOG_PATH = JOBS_DIR / "applications.jsonl"
PAGE_PATH = JOBS_DIR / "applications.html"

# Where an answer came from (the `reason` answers.resolve returns) -> where to
# correct it. First match wins.
FIX_HINTS: list[tuple[str, str]] = [
    (r"your rule", "jobs.yaml -> answer_rules"),
    (r"your saved answer", "data/jobs/answer_bank.yaml"),
    (r"IT-skills table", "jobs.yaml -> skill_years (or the IT skills table on your Naukri profile)"),
    (r"skills list", "your Naukri key skills (python main.py --extract to refresh)"),
    (r"from (notice_period|current_ctc|total_experience|current_location)",
     "your Naukri profile header (python main.py --extract to refresh)"),
    (r"from (expected_ctc|relocate|notice_buyout)", "jobs.yaml -> answers"),
    (r"answers\.phone", "jobs.yaml -> answers.phone"),
    (r"resume", "your resume list on LinkedIn (the newest upload is used)"),
]

STATUS_LABELS = {
    "applied": "Applied",
    "would-apply": "Would apply (dry run)",
    "already": "Applied earlier",
    "offsite": "Company site - left for you",
    "questionnaire": "Needs your answer",
    "questionnaire-failed": "Form failed",
    "unconfirmed": "Unconfirmed",
    "no-button": "No apply button",
    "error": "Error",
}


def fix_hint(source: str) -> str:
    for pattern, hint in FIX_HINTS:
        if re.search(pattern, source or "", re.IGNORECASE):
            return hint
    return ""


def record(board: str, job, status: str, note: str, capture: dict | None = None,
           dry_run: bool = False, per_run: int | None = None, project: str = "naukri") -> dict:
    """Append one attempt to the log. Returns the entry written.

    `project` says which search found the job: "naukri" (this project's
    scan) or "jobhunt" (the worldwide job-hunt bot, which applies through
    this project's LinkedIn applier)."""
    capture = capture or {}
    answers = []
    for item in capture.get("answers") or []:
        source = str(item.get("source") or "")
        answers.append({
            "question": item.get("question") or "",
            "options": list(item.get("options") or []),
            "answer": "" if item.get("answer") is None else str(item.get("answer")),
            "source": source,
            "fix": fix_hint(source),
        })
    blocked = None
    if capture.get("question") and status in ("questionnaire", "questionnaire-failed"):
        blocked = {
            "question": capture.get("question"),
            "options": list(capture.get("options") or []),
            "why": capture.get("why") or "",
        }
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "board": board,
        "job_id": str(getattr(job, "job_id", "") or ""),
        "title": getattr(job, "title", "") or "",
        "company": getattr(job, "company", "") or "",
        "url": getattr(job, "url", "") or "",
        "location": getattr(job, "location", None) or "",
        "score": getattr(job, "score", None),
        "status": status,
        "note": note or "",
        "answers": answers,
        "blocked": blocked,
        "dry_run": bool(dry_run),
        "per_run": per_run,
        "project": project,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load() -> list[dict]:
    """Every logged attempt, oldest first. A damaged line is skipped, not fatal."""
    if not LOG_PATH.exists():
        return []
    entries = []
    for number, line in enumerate(LOG_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("applications.jsonl line %d is not valid JSON - skipped", number)
    return entries


def counts(entries: list[dict]) -> dict:
    today = date.today().isoformat()
    live = [e for e in entries if not e.get("dry_run")]
    applied = [e for e in live if e.get("status") == "applied"]
    return {
        "attempts": len(live),
        "applied": len(applied),
        "applied_today": sum(1 for e in applied if str(e.get("at", "")).startswith(today)),
        "naukri": sum(1 for e in applied if e.get("board") == "naukri"),
        "linkedin": sum(1 for e in applied if e.get("board") == "linkedin"),
        "waiting": sum(1 for e in live if e.get("status") == "questionnaire"),
    }


def summarise(limit: int = 12) -> str:
    entries = load()
    if not entries:
        return "\n  No applications logged yet.\n"
    totals = counts(entries)
    lines = [
        "",
        f"  {totals['applied']} application(s) sent by the agent"
        f" ({totals['naukri']} Naukri, {totals['linkedin']} LinkedIn),"
        f" {totals['applied_today']} today, {totals['waiting']} waiting on an answer from you.",
        "",
        "  Latest:",
    ]
    for entry in list(reversed(entries))[:limit]:
        label = STATUS_LABELS.get(entry.get("status"), entry.get("status"))
        via = "" if entry.get("project", "naukri") == "naukri" else f" [{entry['project']}]"
        lines.append(f"   {entry.get('at', '')[:16]}  {entry.get('board', ''):8} "
                     f"{label:26} {entry.get('title', '')[:38]:40} {entry.get('company', '')[:24]}{via}")
        for item in entry.get("answers") or []:
            lines.append(f"        Q: {item['question'][:70]}")
            lines.append(f"        A: {item['answer']}   ({item['source']})")
        if entry.get("blocked"):
            lines.append(f"        stopped at: {entry['blocked']['question'][:70]}")
    lines += ["", f"  Full record: {LOG_PATH}", f"  Page:        {PAGE_PATH}", ""]
    return "\n".join(lines)


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Applications sent</title>
<style>
  :root {
    --bg: #f6f5f1; --surface: #ffffff; --surface-2: #f0efe9; --line: #dedbd2;
    --ink: #1c1b18; --muted: #6b6860; --accent: #2b5fd9; --accent-soft: #e6edfb;
    --good: #1e7f4a; --good-soft: #e3f3e9; --warn: #a45d00; --warn-soft: #fbeedb;
    --bad: #b3261e; --bad-soft: #fbe5e3;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141413; --surface: #1d1d1b; --surface-2: #262623; --line: #34342f;
      --ink: #ece9e1; --muted: #a09d94; --accent: #7ea2f0; --accent-soft: #1b2a4a;
      --good: #6ec48c; --good-soft: #14291c; --warn: #e2a24a; --warn-soft: #2e2413;
      --bad: #ef8a83; --bad-soft: #3a1a18;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font-family: "Source Sans 3", ui-sans-serif, system-ui, -apple-system, sans-serif; font-size: 15px; line-height: 1.5; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 28px 16px 80px; }
  nav.top { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; font-size: 14px; }
  nav.top a, nav.top .here { padding: 5px 12px; border: 1px solid var(--line); border-radius: 999px; text-decoration: none; color: var(--muted); }
  nav.top .here { color: var(--ink); border-color: var(--accent); background: var(--surface-2); }
  h1 { font-weight: 700; font-size: clamp(24px, 4vw, 34px); margin: 0 0 6px; letter-spacing: -.02em; }
  .sub { color: var(--muted); max-width: 70ch; margin: 0 0 18px; }
  .stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 18px; }
  .stat { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; min-width: 110px; }
  .stat b { display: block; font-size: 22px; }
  .stat span { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 14px; }
  .chip { border: 1px solid var(--line); background: var(--surface); color: var(--muted); border-radius: 999px; padding: 5px 12px; font: inherit; font-size: 13px; cursor: pointer; }
  .chip[aria-pressed="true"] { color: var(--ink); border-color: var(--accent); background: var(--accent-soft); }
  .search { flex: 1; min-width: 180px; border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px; font: inherit; background: var(--surface); color: var(--ink); }
  .day { margin: 22px 0 8px; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
  .app { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
  .head { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: baseline; }
  .head a { color: var(--ink); font-weight: 600; text-decoration: none; font-size: 16px; }
  .head a:hover { text-decoration: underline; }
  .company { color: var(--muted); }
  .when { color: var(--muted); font-size: 13px; margin-left: auto; font-variant-numeric: tabular-nums; }
  .tag { display: inline-block; font-size: 12px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); }
  .tag.ok { color: var(--good); background: var(--good-soft); border-color: transparent; }
  .tag.warn { color: var(--warn); background: var(--warn-soft); border-color: transparent; }
  .tag.bad { color: var(--bad); background: var(--bad-soft); border-color: transparent; }
  .tag.board { color: var(--accent); background: var(--accent-soft); border-color: transparent; }
  .note { color: var(--muted); font-size: 13px; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }
  th, td { text-align: left; vertical-align: top; padding: 6px 8px; border-top: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; border-top: 0; }
  td.a { font-weight: 600; }
  td.fix { color: var(--muted); font-size: 13px; }
  .blocked { margin-top: 8px; padding: 8px 10px; border-radius: 8px; background: var(--warn-soft); color: var(--warn); font-size: 14px; }
  .empty { color: var(--muted); padding: 30px 0; text-align: center; }
  footer { margin-top: 30px; color: var(--muted); font-size: 13px; }
  code { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px; }
  @media (max-width: 640px) { .when { margin-left: 0; } th:nth-child(3), td:nth-child(3) { display: none; } }
</style>
</head>
<body>
<div class="wrap">
  <nav class="top">
    <a href="__TRACKER__">Job Scanner</a>
    <span class="here">Applications sent</span>
  </nav>
  <h1>__HEADING__</h1>
  <p class="sub">Every application the agent attempted, with each screening question, the answer it gave and where that answer came from. If an answer is wrong, correct it at the place named under <em>fix at</em> and every later application uses the correction.</p>

  <div class="stats">
    <div class="stat"><b id="s-applied">0</b><span>Applied</span></div>
    <div class="stat"><b id="s-today">0</b><span>Today</span></div>
    <div class="stat"><b id="s-naukri">0</b><span>Naukri</span></div>
    <div class="stat"><b id="s-linkedin">0</b><span>LinkedIn</span></div>
    <div class="stat"><b id="s-waiting">0</b><span>Waiting on you</span></div>
  </div>

  <div class="bar">
    <button class="chip" data-status="all" aria-pressed="true">All</button>
    <button class="chip" data-status="applied" aria-pressed="false">Applied</button>
    <button class="chip" data-status="questionnaire" aria-pressed="false">Needs your answer</button>
    <button class="chip" data-status="other" aria-pressed="false">Other outcomes</button>
    <button class="chip" data-board="all" aria-pressed="true">Both boards</button>
    <button class="chip" data-board="naukri" aria-pressed="false">Naukri</button>
    <button class="chip" data-board="linkedin" aria-pressed="false">LinkedIn</button>
    <input class="search" id="q" type="search" placeholder="Filter by title, company or question" aria-label="Filter">
  </div>

  <div id="list"></div>

  <footer>
    <p>Record of truth: <code>data/jobs/applications.jsonl</code>. Rebuild this page with <code>python main.py --applications</code>. Generated __GENERATED__.</p>
  </footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
  const ROWS = JSON.parse(document.getElementById('data').textContent);
  const LABELS = __LABELS__;
  const TODAY = '__TODAY__';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let status = 'all', board = 'all', query = '';

  function cls(s) {
    if (s === 'applied' || s === 'already') return 'ok';
    if (s === 'questionnaire' || s === 'would-apply' || s === 'offsite') return 'warn';
    if (s === 'error' || s === 'questionnaire-failed' || s === 'unconfirmed') return 'bad';
    return '';
  }
  function visible(r) {
    if (board !== 'all' && r.board !== board) return false;
    if (status === 'applied' && r.status !== 'applied') return false;
    if (status === 'questionnaire' && r.status !== 'questionnaire') return false;
    if (status === 'other' && (r.status === 'applied' || r.status === 'questionnaire')) return false;
    if (query) {
      const hay = [r.title, r.company, ...(r.answers || []).map(a => a.question + ' ' + a.answer),
                   r.blocked ? r.blocked.question : ''].join(' ').toLowerCase();
      if (!hay.includes(query)) return false;
    }
    return true;
  }
  function qa(r) {
    let html = '';
    if (r.answers && r.answers.length) {
      html += '<table><tr><th>Question</th><th>Answer given</th><th>From</th><th>Fix at</th></tr>';
      r.answers.forEach(a => {
        html += '<tr><td>' + esc(a.question) + (a.options && a.options.length ? '<div class="note">options: ' + esc(a.options.join(' / ')) + '</div>' : '') + '</td>' +
                '<td class="a">' + esc(a.answer) + '</td><td>' + esc(a.source) + '</td><td class="fix">' + esc(a.fix) + '</td></tr>';
      });
      html += '</table>';
    }
    if (r.blocked) {
      html += '<div class="blocked">Stopped at: <b>' + esc(r.blocked.question) + '</b>' +
              (r.blocked.options && r.blocked.options.length ? ' (options: ' + esc(r.blocked.options.join(' / ')) + ')' : '') +
              ' &mdash; ' + esc(r.blocked.why) + '. Answer it in <code>data/jobs/questions.yaml</code>.</div>';
    }
    return html;
  }
  function render() {
    const list = document.getElementById('list');
    const shown = ROWS.filter(visible).slice().sort((a, b) => (a.at < b.at ? 1 : -1));
    let html = '', day = '';
    shown.forEach(r => {
      const d = (r.at || '').slice(0, 10);
      if (d !== day) { day = d; html += '<div class="day">' + esc(d === TODAY ? 'Today ' + d : d) + '</div>'; }
      html += '<div class="app">' +
        '<div class="head"><a href="' + esc(r.url) + '" target="_blank" rel="noopener">' + esc(r.title) + '</a>' +
        '<span class="company">' + esc(r.company) + '</span>' +
        '<span class="tag board">' + esc(r.board) + '</span>' +
        (r.project && r.project !== 'naukri' ? '<span class="tag">via ' + esc(r.project) + '</span>' : '') +
        '<span class="tag ' + cls(r.status) + '">' + esc(LABELS[r.status] || r.status) + '</span>' +
        (r.dry_run ? '<span class="tag">dry run</span>' : '') +
        '<span class="when">' + esc((r.at || '').slice(11, 16)) + (r.score != null ? ' &middot; score ' + esc(r.score) : '') + '</span></div>' +
        (r.note ? '<div class="note">' + esc(r.note) + '</div>' : '') +
        qa(r) + '</div>';
    });
    list.innerHTML = html || '<p class="empty">Nothing matches this filter.</p>';
    const live = ROWS.filter(r => !r.dry_run);
    const applied = live.filter(r => r.status === 'applied');
    const n = (id, v) => document.getElementById(id).textContent = v;
    n('s-applied', applied.length);
    n('s-today', applied.filter(r => (r.at || '').startsWith(TODAY)).length);
    n('s-naukri', applied.filter(r => r.board === 'naukri').length);
    n('s-linkedin', applied.filter(r => r.board === 'linkedin').length);
    n('s-waiting', live.filter(r => r.status === 'questionnaire').length);
  }
  document.querySelectorAll('[data-status]').forEach(c => c.addEventListener('click', () => {
    status = c.dataset.status; document.querySelectorAll('[data-status]').forEach(x => x.setAttribute('aria-pressed', x === c)); render(); }));
  document.querySelectorAll('[data-board]').forEach(c => c.addEventListener('click', () => {
    board = c.dataset.board; document.querySelectorAll('[data-board]').forEach(x => x.setAttribute('aria-pressed', x === c)); render(); }));
  document.getElementById('q').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); render(); });
  render();
</script>
</body>
</html>
"""


def _latest_tracker() -> str:
    pages = sorted(JOBS_DIR.glob("openings-*.html"), reverse=True) if JOBS_DIR.exists() else []
    return pages[0].name if pages else "#"


def build_page() -> Path:
    """Rebuild data/jobs/applications.html from the log. Returns the path."""
    entries = load()
    totals = counts(entries)
    heading = (f"{totals['applied']} applications sent" if totals["applied"] != 1
               else "1 application sent")
    page = (TEMPLATE
            .replace("__TRACKER__", html.escape(_latest_tracker()))
            .replace("__HEADING__", heading)
            .replace("__GENERATED__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__TODAY__", date.today().isoformat())
            .replace("__LABELS__", json.dumps(STATUS_LABELS))
            .replace("__DATA__", json.dumps(entries, ensure_ascii=False).replace("<", "\\u003c")))
    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAGE_PATH.write_text(page, encoding="utf-8")
    log.info("Applications page: %d attempt(s) -> %s", len(entries), PAGE_PATH)
    return PAGE_PATH
