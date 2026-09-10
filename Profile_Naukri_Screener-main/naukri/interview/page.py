"""Build the interview preparation HTML.

A study page, not a report. The difference shows in the defaults: answers start
collapsed so you can attempt a question before reading it, progress is per
question rather than per session, and the two marks you can leave - Learned and
Needs revision - are the two a revision pass actually produces.

Progress is keyed on a hash of the question text, not on its position. Question
17 today may be question 3 tomorrow, and questions carried over from a previous
day keep whatever you marked them. That is the whole point of the bank: the
corpus grows, and what you have already learned stays learned.

Design tokens are copied from naukri/jobs/page.py deliberately. The two pages
link to each other and are read minutes apart; they should look like one thing.
"""
from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from . import dedupe, skills

log = logging.getLogger("naukri.interview.page")

ROOT = Path(__file__).resolve().parent.parent.parent
PREP_DIR = ROOT / "data" / "interview"
JOBS_DIR = ROOT / "data" / "jobs"

LEVEL_LABELS = {"basic": "Basic", "intermediate": "Intermediate", "advanced": "Advanced"}


def qkey(question: str) -> str:
    """A stable per-question id, so progress survives renumbering.

    The same id the question bank is keyed on, deliberately: a question carried
    forward from an earlier day should keep whatever you marked it, and that
    only holds if both sides agree on what "the same question" means.
    """
    return dedupe.stable_id(question)


def _safe_json(payload) -> str:
    """JSON for a <script type=application/json> block.

    The only sequence that can break out of that block is "</script", so the
    left angle bracket is escaped. json.dumps does not do this and a JD
    containing "<script" would otherwise end the block early.
    """
    return (json.dumps(payload, ensure_ascii=False)
            .replace("<", "\\u003c").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


# A RAW string, deliberately. The template carries backslashes that belong to
# CSS and to JavaScript regex literals, and a normal string hands Python's
# escape rules a first pass at them: "\n" inside a JS regex becomes an actual
# newline, which turns /^\n+/ into a regex literal broken across two lines and
# takes the whole script down with it. Raw means what is written here is what
# the browser receives. Nothing below may use Python escapes.
TEMPLATE = r"""<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=Source+Sans+3:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root {
    --bg: #f2f4f7; --surface: #ffffff; --surface-2: #fafbfc; --line: #dde2e9;
    --ink: #161b22; --muted: #5b6675;
    --accent: #1f5c8b; --accent-soft: #e8f0f7; --accent-on: #ffffff;
    --good: #166534; --good-soft: #e6f4ea;
    --warn: #a15c07; --warn-soft: #fdf3e3;
    --bad: #9b2c2c; --bad-soft: #fdecec;
    --shadow: 0 1px 2px rgba(22,27,34,.06), 0 4px 12px rgba(22,27,34,.04);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0e1218; --surface: #161c25; --surface-2: #1b222c; --line: #2a3441;
      --ink: #e7ecf3; --muted: #8d99a9;
      --accent: #6aa9d8; --accent-soft: #17293a; --accent-on: #0e1218;
      --good: #6ec48c; --good-soft: #14291c;
      --warn: #e0a54a; --warn-soft: #2e2413;
      --bad: #e88b8b; --bad-soft: #2e1717;
      --shadow: 0 1px 2px rgba(0,0,0,.4), 0 4px 14px rgba(0,0,0,.3);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0e1218; --surface: #161c25; --surface-2: #1b222c; --line: #2a3441;
    --ink: #e7ecf3; --muted: #8d99a9;
    --accent: #6aa9d8; --accent-soft: #17293a; --accent-on: #0e1218;
    --good: #6ec48c; --good-soft: #14291c;
    --warn: #e0a54a; --warn-soft: #2e2413;
    --bad: #e88b8b; --bad-soft: #2e1717;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 4px 14px rgba(0,0,0,.3);
  }

  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: "Source Sans 3", ui-sans-serif, system-ui, -apple-system, sans-serif;
    font-size: 15px; line-height: 1.55;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 20px 20px 96px; }
  h1, h2, h3 { font-family: Archivo, ui-sans-serif, system-ui, sans-serif; margin: 0; }
  a { color: var(--accent); }

  /* --- nav ------------------------------------------------------------- */
  nav.top {
    display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
    border-bottom: 1px solid var(--line); margin-bottom: 22px; padding-bottom: 0;
  }
  nav.top a, nav.top span.here {
    font: 600 13.5px/1 Archivo, sans-serif; text-decoration: none;
    padding: 11px 15px; border-bottom: 2px solid transparent; color: var(--muted);
    border-radius: 6px 6px 0 0;
  }
  nav.top a:hover { color: var(--ink); background: var(--surface-2); }
  nav.top span.here { color: var(--ink); border-bottom-color: var(--accent); }
  nav.top .nav-right { margin-left: auto; display: flex; align-items: center; gap: 8px; padding-bottom: 6px; }
  nav.top select {
    font: 400 13px "Source Sans 3", sans-serif; color: var(--ink);
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 7px; padding: 6px 9px;
  }
  .nav-label {
    font-family: "IBM Plex Mono", monospace; font-size: 10.5px; letter-spacing: .08em;
    text-transform: uppercase; color: var(--muted);
  }

  /* --- header ---------------------------------------------------------- */
  .eyebrow {
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px;
    letter-spacing: .09em; text-transform: uppercase; color: var(--muted);
  }
  h1 { font-weight: 700; font-size: clamp(25px, 4vw, 34px); letter-spacing: -.02em; margin: 6px 0 8px; }
  .sub { color: var(--muted); max-width: 68ch; margin: 0; }

  .stats { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0 8px; }
  .stat {
    background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
    padding: 11px 15px; min-width: 112px; box-shadow: var(--shadow);
  }
  .stat b {
    display: block; font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums;
    font-size: 23px; font-weight: 500; line-height: 1.15;
  }
  .stat span {
    font-size: 10.5px; letter-spacing: .07em; text-transform: uppercase; color: var(--muted);
    font-family: "IBM Plex Mono", monospace;
  }
  .stat.is-good b { color: var(--good); }
  .stat.is-warn b { color: var(--warn); }

  .progress-wrap { margin: 14px 0 4px; }
  .pbar { height: 9px; background: var(--surface-2); border: 1px solid var(--line);
          border-radius: 999px; overflow: hidden; display: flex; }
  .pbar i { display: block; height: 100%; transition: width .25s ease; }
  .pbar i.learned { background: var(--good); }
  .pbar i.revise { background: var(--warn); }
  .plegend { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 8px;
             font-size: 12.5px; color: var(--muted); font-family: "IBM Plex Mono", monospace; }
  .plegend b { color: var(--ink); font-weight: 500; }

  /* --- sections -------------------------------------------------------- */
  section { margin-top: 34px; scroll-margin-top: 12px; }
  .sec-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
              margin-bottom: 12px; padding-bottom: 7px; border-bottom: 2px solid var(--ink); }
  .sec-head h2 { font-size: 14.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
  .sec-head .count { font-family: "IBM Plex Mono", monospace; font-size: 12.5px; color: var(--muted); }
  .sec-note { color: var(--muted); font-size: 13.5px; margin: -4px 0 14px; max-width: 74ch; }

  .card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
          padding: 15px 17px; box-shadow: var(--shadow); }
  .grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(268px, 1fr)); gap: 11px; }
  .grid3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(258px, 1fr)); gap: 11px; }
  .card h3 { font-size: 12px; letter-spacing: .07em; text-transform: uppercase;
             color: var(--muted); margin-bottom: 9px; font-weight: 700; }

  .pills { display: flex; flex-wrap: wrap; gap: 5px; }
  .pill {
    font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .03em;
    padding: 3px 9px; border-radius: 999px; border: 1px solid var(--line);
    background: var(--surface-2); color: var(--ink);
  }
  .pill.accent { color: var(--accent); background: var(--accent-soft);
                 border-color: color-mix(in srgb, var(--accent) 32%, var(--line)); }
  .pill.good { color: var(--good); background: var(--good-soft);
               border-color: color-mix(in srgb, var(--good) 32%, var(--line)); }
  .pill.warn { color: var(--warn); background: var(--warn-soft);
               border-color: color-mix(in srgb, var(--warn) 32%, var(--line)); }
  .pill.bad  { color: var(--bad); background: var(--bad-soft);
               border-color: color-mix(in srgb, var(--bad) 32%, var(--line)); }
  ul.tight { margin: 0; padding-left: 18px; }
  ul.tight li { margin-bottom: 4px; }
  .market { margin-top: 12px; }

  /* --- job list -------------------------------------------------------- */
  .job { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
         padding: 13px 16px; margin-bottom: 8px; box-shadow: var(--shadow); }
  .job-head { display: grid; grid-template-columns: 30px 1fr auto; gap: 12px; align-items: baseline; }
  .job-rank { font-family: "IBM Plex Mono", monospace; font-size: 15px; color: var(--muted); }
  .job-title { font-family: Archivo, sans-serif; font-weight: 600; font-size: 15.5px; line-height: 1.3; }
  .job-title a { color: var(--ink); text-decoration: none; }
  .job-title a:hover { color: var(--accent); text-decoration: underline; }
  .job-company { color: var(--muted); font-size: 13.5px; margin-top: 1px; }
  .job-score { font-family: "IBM Plex Mono", monospace; font-size: 17px; color: var(--accent); text-align: right; }
  .job-score small { display: block; font-size: 9.5px; letter-spacing: .06em;
                     text-transform: uppercase; color: var(--muted); }
  .job-summary { margin: 9px 0 0; font-size: 14px; }
  .job-meta { color: var(--muted); font-size: 13px; margin-top: 5px; }
  details.jd { margin-top: 10px; }
  details.jd > summary {
    cursor: pointer; font: 500 12.5px/1 "IBM Plex Mono", monospace;
    letter-spacing: .05em; text-transform: uppercase; color: var(--accent);
    padding: 6px 0; list-style: none;
  }
  details.jd > summary::-webkit-details-marker { display: none; }
  details.jd > summary::before { content: "\25B8  "; display: inline-block; transition: transform .15s; }
  details.jd[open] > summary::before { content: "\25BE  "; }
  .jd-text {
    white-space: pre-wrap; font-size: 13.5px; line-height: 1.6; color: var(--ink);
    background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px;
    padding: 13px 15px; margin-top: 4px; max-height: 460px; overflow: auto;
  }

  /* --- skill matrix ---------------------------------------------------- */
  .matrix { overflow-x: auto; }
  table.skills { width: 100%; border-collapse: collapse; font-size: 13.5px; min-width: 620px; }
  table.skills th {
    text-align: left; font-family: "IBM Plex Mono", monospace; font-size: 10.5px;
    letter-spacing: .07em; text-transform: uppercase; color: var(--muted);
    padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap;
  }
  table.skills td { padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: middle; }
  table.skills tr:last-child td { border-bottom: none; }
  table.skills tbody tr:hover { background: var(--surface-2); }
  .bar { display: flex; align-items: center; gap: 8px; min-width: 132px; }
  .bar .track { flex: 1; height: 7px; background: var(--surface-2);
                border: 1px solid var(--line); border-radius: 999px; overflow: hidden; }
  .bar .fill { display: block; height: 100%; background: var(--accent); }
  .bar .fill.gap { background: var(--bad); }
  .bar .fill.moderate { background: var(--warn); }
  .bar .fill.strong { background: var(--good); }
  .bar .n { font-family: "IBM Plex Mono", monospace; font-size: 12px;
            color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .skill-name { font-weight: 600; }
  .evidence { color: var(--muted); font-size: 12.5px; }

  /* --- toolbar --------------------------------------------------------- */
  .bar-tools {
    position: sticky; top: 0; z-index: 20; background: var(--bg);
    display: flex; flex-wrap: wrap; gap: 7px; align-items: center;
    padding: 11px 0; border-bottom: 1px solid var(--line); margin-bottom: 12px;
  }
  .chip {
    font: 500 13px/1 Archivo, sans-serif; border: 1px solid var(--line);
    background: var(--surface); color: var(--ink);
    padding: 8px 13px; border-radius: 999px; cursor: pointer;
  }
  .chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--accent-on); }
  .chip small { font-family: "IBM Plex Mono", monospace; opacity: .75; margin-left: 4px; }
  .chip:focus-visible, input:focus-visible, select:focus-visible, button:focus-visible {
    outline: 2px solid var(--accent); outline-offset: 2px;
  }
  .spacer { flex: 1 1 auto; }
  .search, .picker {
    font: 400 14px "Source Sans 3", sans-serif; color: var(--ink);
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 8px; padding: 8px 11px;
  }
  .search { min-width: 190px; }
  .ghost {
    font: 500 12.5px/1 Archivo, sans-serif; border: 1px solid var(--line);
    background: var(--surface); color: var(--muted);
    padding: 8px 11px; border-radius: 8px; cursor: pointer;
  }
  .ghost:hover { color: var(--ink); }

  /* --- questions ------------------------------------------------------- */
  .q {
    background: var(--surface); border: 1px solid var(--line); border-left-width: 3px;
    border-radius: 10px; margin-bottom: 8px; box-shadow: var(--shadow); scroll-margin-top: 70px;
  }
  .q.lv-basic { border-left-color: var(--accent); }
  .q.lv-intermediate { border-left-color: var(--warn); }
  .q.lv-advanced { border-left-color: var(--bad); }
  .q.is-learned { background: var(--good-soft); border-color: color-mix(in srgb, var(--good) 28%, var(--line)); }
  .q.is-revise { background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 28%, var(--line)); }

  .q-head { display: grid; grid-template-columns: 52px 1fr; gap: 12px; padding: 13px 16px 11px; }
  .q-num {
    font-family: "IBM Plex Mono", monospace; font-size: 13px; color: var(--muted);
    font-variant-numeric: tabular-nums; padding-top: 2px;
  }
  .q-text {
    font-family: Archivo, sans-serif; font-weight: 600; font-size: 15.5px; line-height: 1.4;
    cursor: pointer; text-wrap: pretty;
  }
  .q-text:hover { color: var(--accent); }
  .q-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; align-items: center; }
  .q-why { color: var(--muted); font-size: 12.5px; margin-top: 7px; }

  .q-answer {
    margin: 0 16px 14px 80px; padding: 13px 15px; border-radius: 8px;
    background: var(--surface-2); border: 1px solid var(--line);
    font-size: 14.2px; line-height: 1.62;
  }
  /* Prose keeps its line breaks; code blocks bring their own whitespace rules,
     which a pre-wrap on the whole answer would fight with. */
  .q-answer .prose { display: block; white-space: pre-wrap; }
  .q-answer pre {
    margin: 10px 0; padding: 11px 13px; border-radius: 7px; overflow-x: auto;
    background: var(--surface); border: 1px solid var(--line);
    font: 400 12.6px/1.6 "IBM Plex Mono", ui-monospace, monospace; white-space: pre;
  }
  .q-answer code {
    font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .92em;
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 4px; padding: 1px 5px;
  }
  .q-answer pre code { background: none; border: none; padding: 0; font-size: inherit; }
  .q-answer .lead {
    display: block; font-family: "IBM Plex Mono", monospace; font-size: 10.5px;
    letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-bottom: 7px;
  }
  .q-answer .link {
    display: block; margin-top: 11px; padding-top: 9px; border-top: 1px dashed var(--line);
    color: var(--muted); font-size: 12.8px; white-space: normal;
  }
  .q-actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 16px 13px 80px; }
  .mark {
    font: 500 12.5px/1 Archivo, sans-serif; border: 1px solid var(--line);
    background: var(--surface); color: var(--muted);
    padding: 7px 12px; border-radius: 7px; cursor: pointer;
  }
  .mark:hover { color: var(--ink); }
  .mark[aria-pressed="true"].learned { background: var(--good); border-color: var(--good); color: #fff; }
  .mark[aria-pressed="true"].revise { background: var(--warn); border-color: var(--warn); color: #fff; }

  .empty { color: var(--muted); padding: 30px 0; text-align: center; }
  .jump {
    position: fixed; right: 18px; bottom: 18px; z-index: 30; display: flex; gap: 6px;
    background: var(--surface); border: 1px solid var(--line); border-radius: 999px;
    padding: 6px; box-shadow: var(--shadow);
  }
  .jump button {
    font: 500 12.5px/1 Archivo, sans-serif; border: none; background: transparent;
    color: var(--muted); padding: 7px 11px; border-radius: 999px; cursor: pointer;
  }
  .jump button:hover { background: var(--surface-2); color: var(--ink); }

  footer { margin-top: 44px; padding-top: 18px; border-top: 1px solid var(--line);
           color: var(--muted); font-size: 13px; }
  footer code { font-family: "IBM Plex Mono", monospace; font-size: 12px; }
  footer .checks { margin-top: 8px; font-family: "IBM Plex Mono", monospace; font-size: 12px; }
  footer .checks div { padding: 1px 0; }
  footer .checks .fail { color: var(--bad); }

  @media (max-width: 760px) {
    .q-head { grid-template-columns: 40px 1fr; gap: 9px; }
    .q-answer, .q-actions { margin-left: 16px; padding-left: 0; }
    .q-answer { padding: 12px 14px; }
    .q-actions { padding: 0 16px 13px; }
    .job-head { grid-template-columns: 26px 1fr; }
    .job-score { grid-column: 2; text-align: left; }
    .jump { right: 10px; bottom: 10px; }
  }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
  @media print {
    .bar-tools, .jump, nav.top, .q-actions { display: none !important; }
    .q-answer { display: block !important; }
    .q { break-inside: avoid; }
  }
</style>

<div class="wrap">
  <nav class="top">
    <a href="__SCANNER_HREF__">Job Scanner</a>
    <a href="#jobs">Top 10 Jobs</a>
    <span class="here">Interview Preparation</span>
    <span class="nav-right">
      <span class="nav-label">Analysis date</span>
      <select class="picker" id="datepick" aria-label="Choose a preparation date">__DATE_OPTIONS__</select>
    </span>
  </nav>

  <header>
    <div class="eyebrow">AI Interview Preparation &middot; __DATELINE__</div>
    <h1>__HEADING__</h1>
    <p class="sub">__SUBTITLE__</p>
  </header>

  <div class="stats">
    <div class="stat"><b>__JD_COUNT__</b><span>JDs analysed</span></div>
    <div class="stat"><b>__Q_COUNT__</b><span>Questions</span></div>
    <div class="stat"><b>__SKILL_COUNT__</b><span>Skills found</span></div>
    <div class="stat is-warn"><b>__GAP_COUNT__</b><span>Skill gaps</span></div>
    <div class="stat is-good"><b id="s-learned">0</b><span>Learned</span></div>
    <div class="stat"><b id="s-left">0</b><span>Remaining</span></div>
  </div>

  <div class="progress-wrap">
    <div class="pbar" role="img" aria-label="Preparation progress">
      <i class="learned" id="p-learned" style="width:0"></i>
      <i class="revise" id="p-revise" style="width:0"></i>
    </div>
    <div class="plegend">
      <span>Preparation progress: <b id="p-total">0 / __Q_COUNT__</b></span>
      <span>Basic <b id="p-basic">0 / 0</b></span>
      <span>Intermediate <b id="p-intermediate">0 / 0</b></span>
      <span>Advanced <b id="p-advanced">0 / 0</b></span>
      <span>Needs revision <b id="p-revise-n">0</b></span>
    </div>
  </div>

  <!-- 1 ------------------------------------------------------------------ -->
  <section id="target">
    <div class="sec-head"><h2>1 &middot; Target job profile</h2>
      <span class="count">__PRIMARY_ROLE__</span></div>
    <p class="sec-note">What these ten employers are asking for this week, read across all
      ten postings rather than one at a time.</p>
    <div class="grid2">__TARGET_CARDS__</div>
    <div class="card market"><h3>How the market reads against your profile</h3>
      <p style="margin:0">__MARKET_SUMMARY__</p></div>
  </section>

  <!-- 2 ------------------------------------------------------------------ -->
  <section id="jobs">
    <div class="sec-head"><h2>2 &middot; Top 10 job analysis</h2>
      <span class="count">the ten highest-scoring jobs from __DATELINE__</span></div>
    <p class="sec-note">These are the postings every question below was derived from.
      Expand a job to read the description the analysis actually saw.</p>
    __JOB_CARDS__
  </section>

  <!-- 3 ------------------------------------------------------------------ -->
  <section id="skills">
    <div class="sec-head"><h2>3 &middot; Collective skill analysis</h2>
      <span class="count">__SKILL_COUNT__ skills across __JD_COUNT__ JDs</span></div>
    <p class="sec-note">Frequency is an exact term match across the ten descriptions, not an
      estimate. Your match comes from the resume: <em>Strong</em> means the skill is
      described in your experience or projects, <em>Moderate</em> means it appears only in a
      skills list, <em>Gap</em> means it is not there at all.</p>
    <div class="card matrix">
      <table class="skills">
        <thead><tr>
          <th>Skill</th><th>Category</th><th>JDs mentioning it</th>
          <th>Importance</th><th>Your match</th><th>Evidence</th>
        </tr></thead>
        <tbody>__SKILL_ROWS__</tbody>
      </table>
    </div>
  </section>

  <!-- 4 ------------------------------------------------------------------ -->
  <section id="gaps">
    <div class="sec-head"><h2>4 &middot; Skill gaps</h2>
      <span class="count">what to study before an interview</span></div>
    <p class="sec-note">Ordered by interview risk: how much of the market wants it, weighted by
      how little of it your resume supports.</p>
    <div class="grid3">__GAP_CARDS__</div>
  </section>

  <!-- questions ---------------------------------------------------------- -->
  <section id="questions">
    <div class="sec-head"><h2>5 &middot; Interview questions</h2>
      <span class="count">__Q_COUNT__ unique questions, no concept repeated</span></div>
    <p class="sec-note">Answers are hidden by default &mdash; read the question, answer it in your
      head, then reveal. Marks are saved in this browser and follow the question, so a
      question carried into tomorrow&rsquo;s set stays marked.</p>

    <div class="bar-tools">
      <button class="chip" data-level="all" aria-pressed="true">All <small id="n-all">0</small></button>
      <button class="chip" data-level="basic" aria-pressed="false">Basic <small id="n-basic">0</small></button>
      <button class="chip" data-level="intermediate" aria-pressed="false">Intermediate <small id="n-intermediate">0</small></button>
      <button class="chip" data-level="advanced" aria-pressed="false">Advanced <small id="n-advanced">0</small></button>
      <span class="spacer"></span>
      <select class="picker" id="skillpick" aria-label="Filter by skill">__SKILL_OPTIONS__</select>
      <select class="picker" id="statuspick" aria-label="Filter by progress">
        <option value="all">Any status</option>
        <option value="todo">Not marked</option>
        <option value="learned">Learned</option>
        <option value="revise">Needs revision</option>
      </select>
      <input class="search" id="q" type="search" placeholder="Search questions and answers" aria-label="Search questions and answers">
      <button class="ghost" id="expand-all">Expand all</button>
      <button class="ghost" id="collapse-all">Collapse all</button>
    </div>

    <div id="list"></div>
  </section>

  <div class="jump">
    <button id="prev-q" title="Previous question (k)">&uarr; Prev</button>
    <button id="next-q" title="Next question (j)">&darr; Next</button>
    <button id="next-todo" title="Next unmarked question (n)">Next unmarked</button>
  </div>

  <footer>
    <p>Generated __GENERATED__ from __JD_COUNT__ job descriptions and your resume
      (<code>__RESUME_NAME__</code>) by __ENGINE__.
      Frequency counts are computed by term matching; the questions, answers and the
      written analysis are model-generated from those counts and the JD text.</p>
    <p>Progress is stored in this browser under <code>interviewprep.marks</code>.
      Clearing site data clears it. Nothing on this page is sent anywhere.</p>
    <div class="checks">__CHECKS__</div>
  </footer>
</div>

<script id="prep-data" type="application/json">__DATA__</script>
<script>
  const DATA = JSON.parse(document.getElementById('prep-data').textContent);
  const QUESTIONS = DATA.questions;
  const KEY = 'interviewprep.marks';
  const OPEN_KEY = 'interviewprep.open';

  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };

  let marks = load(KEY, {});          // qkey -> 'learned' | 'revise'
  let opened = new Set(load(OPEN_KEY, []));
  let level = 'all', skill = 'all', status = 'all', query = '';

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // Answers arrive with fenced code blocks, inline `code` and the odd **bold**.
  // Rendering them as literal backticks in a page built for reading commands and
  // config would be a strange thing to hand someone. Escaping happens FIRST, so
  // the markup below is only ever applied to text that can no longer be markup.
  function inlineMd(escaped) {
    return escaped
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  }

  function fmt(text) {
    const parts = String(text == null ? '' : text).split('```');
    return parts.map((part, index) => {
      if (index % 2 === 0) return '<span class="prose">' + inlineMd(esc(part)) + '</span>';
      // A fenced block's first line is usually a language tag, not code.
      const brk = part.indexOf('\n');
      const tag = brk === -1 ? '' : part.slice(0, brk).trim();
      const body = (tag && /^[a-z0-9+#_-]{1,14}$/i.test(tag)) ? part.slice(brk + 1) : part;
      return '<pre><code>' + esc(body.replace(/^\n+|\n+$/g, '')) + '</code></pre>';
    }).join('');
  }

  function visible(q) {
    if (level !== 'all' && q.level !== level) return false;
    if (skill !== 'all' && q.skill !== skill && !(q.secondary_skills || []).includes(skill)) return false;
    const mark = marks[q.qkey] || '';
    if (status === 'todo' && mark) return false;
    if (status === 'learned' && mark !== 'learned') return false;
    if (status === 'revise' && mark !== 'revise') return false;
    if (query) {
      const hay = (q.question + ' ' + q.answer + ' ' + q.skill + ' ' +
                   (q.secondary_skills || []).join(' ')).toLowerCase();
      if (!hay.includes(query)) return false;
    }
    return true;
  }

  function questionHtml(q) {
    const mark = marks[q.qkey] || '';
    const isOpen = opened.has(q.qkey);
    const cls = 'q lv-' + q.level + (mark === 'learned' ? ' is-learned' : mark === 'revise' ? ' is-revise' : '');
    const jds = (q.jd_numbers || []);
    const jdLabel = jds.length ? jds.length + '/' + DATA.jd_count + ' jobs &middot; JD' + jds.join(', JD') : '';
    const secondary = (q.secondary_skills || []).map(s =>
      '<span class="pill">' + esc(s) + '</span>').join('');
    const reused = q.reused ? '<span class="pill">carried from ' + esc(q.reused_from || 'an earlier day') + '</span>' : '';

    return '' +
      '<article class="' + cls + '" id="' + esc(q.qkey) + '" data-key="' + esc(q.qkey) + '">' +
        '<div class="q-head">' +
          '<div class="q-num">' + esc(q.id) + '</div>' +
          '<div>' +
            '<div class="q-text" role="button" tabindex="0" aria-expanded="' + isOpen + '">' +
              esc(q.question) + '</div>' +
            '<div class="q-tags">' +
              '<span class="pill ' + (q.level === 'basic' ? 'accent' : q.level === 'intermediate' ? 'warn' : 'bad') + '">' +
                esc(DATA.level_labels[q.level] || q.level) + '</span>' +
              '<span class="pill">' + esc(q.skill) + '</span>' +
              secondary +
              (jdLabel ? '<span class="pill accent">' + jdLabel + '</span>' : '') +
              reused +
            '</div>' +
            (q.why_asked ? '<div class="q-why">' + esc(q.why_asked) + '</div>' : '') +
          '</div>' +
        '</div>' +
        (isOpen ?
          '<div class="q-answer"><span class="lead">Answer</span>' + fmt(q.answer) +
            (q.profile_link ? '<span class="link">Your angle: ' + esc(q.profile_link) + '</span>' : '') +
          '</div>' : '') +
        '<div class="q-actions">' +
          '<button class="mark learned" data-mark="learned" aria-pressed="' + (mark === 'learned') + '">Learned</button>' +
          '<button class="mark revise" data-mark="revise" aria-pressed="' + (mark === 'revise') + '">Needs revision</button>' +
          '<button class="mark toggle">' + (isOpen ? 'Hide answer' : 'Show answer') + '</button>' +
        '</div>' +
      '</article>';
  }

  function render() {
    const shown = QUESTIONS.filter(visible);
    document.getElementById('list').innerHTML =
      shown.length ? shown.map(questionHtml).join('')
                   : '<p class="empty">No question matches these filters.</p>';
    stats();
  }

  function stats() {
    const n = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const levels = ['basic', 'intermediate', 'advanced'];
    let learned = 0, revise = 0;
    QUESTIONS.forEach(q => {
      if (marks[q.qkey] === 'learned') learned++;
      else if (marks[q.qkey] === 'revise') revise++;
    });
    const total = QUESTIONS.length || 1;
    n('s-learned', learned);
    n('s-left', QUESTIONS.length - learned);
    n('p-total', learned + ' / ' + QUESTIONS.length);
    n('p-revise-n', revise);
    document.getElementById('p-learned').style.width = (learned / total * 100) + '%';
    document.getElementById('p-revise').style.width = (revise / total * 100) + '%';

    levels.forEach(lv => {
      const group = QUESTIONS.filter(q => q.level === lv);
      const done = group.filter(q => marks[q.qkey] === 'learned').length;
      n('p-' + lv, done + ' / ' + group.length);
      n('n-' + lv, group.length);
    });
    n('n-all', QUESTIONS.length);
  }

  function setMark(key, value) {
    if (marks[key] === value) delete marks[key];
    else marks[key] = value;
    save(KEY, marks);
  }

  document.getElementById('list').addEventListener('click', (e) => {
    const card = e.target.closest('.q');
    if (!card) return;
    const key = card.getAttribute('data-key');

    if (e.target.matches('.q-text') || e.target.matches('.mark.toggle')) {
      if (opened.has(key)) opened.delete(key); else opened.add(key);
      save(OPEN_KEY, [...opened]);
      render();
      document.getElementById(key)?.scrollIntoView({ block: 'nearest' });
      return;
    }
    const button = e.target.closest('.mark[data-mark]');
    if (button) {
      setMark(key, button.getAttribute('data-mark'));
      // Re-rendering under a status filter would make the card vanish
      // mid-click, so only the visible state changes unless it must.
      if (status === 'all') { render(); document.getElementById(key)?.scrollIntoView({ block: 'nearest' }); }
      else render();
    }
  });

  document.getElementById('list').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    if (!e.target.matches('.q-text')) return;
    e.preventDefault();
    e.target.click();
  });

  function wire(selector, apply) {
    document.querySelectorAll(selector).forEach(chip => {
      chip.addEventListener('click', () => {
        apply(chip);
        document.querySelectorAll(selector).forEach(c =>
          c.setAttribute('aria-pressed', String(c === chip)));
        render();
      });
    });
  }
  wire('.chip[data-level]', chip => { level = chip.dataset.level; });

  document.getElementById('skillpick').addEventListener('change', e => { skill = e.target.value; render(); });
  document.getElementById('statuspick').addEventListener('change', e => { status = e.target.value; render(); });
  document.getElementById('q').addEventListener('input', e => {
    query = e.target.value.trim().toLowerCase(); render();
  });

  document.getElementById('expand-all').addEventListener('click', () => {
    QUESTIONS.filter(visible).forEach(q => opened.add(q.qkey));
    save(OPEN_KEY, [...opened]); render();
  });
  document.getElementById('collapse-all').addEventListener('click', () => {
    opened.clear(); save(OPEN_KEY, []); render();
  });

  const datepick = document.getElementById('datepick');
  if (datepick) datepick.addEventListener('change', e => {
    if (e.target.value) window.location.href = e.target.value;
  });

  // --- quick navigation
  function cards() { return [...document.querySelectorAll('.q')]; }
  function step(delta) {
    const all = cards();
    if (!all.length) return;
    const top = window.scrollY + 90;
    let index = all.findIndex(c => c.offsetTop > top);
    if (index === -1) index = all.length - 1;
    if (delta < 0) index = Math.max(0, index - 2);
    all[Math.min(Math.max(index, 0), all.length - 1)]
      .scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function nextTodo() {
    const target = cards().find(c => !marks[c.getAttribute('data-key')] &&
                                     c.offsetTop > window.scrollY + 90);
    (target || cards()[0])?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  document.getElementById('next-q').addEventListener('click', () => step(1));
  document.getElementById('prev-q').addEventListener('click', () => step(-1));
  document.getElementById('next-todo').addEventListener('click', nextTodo);

  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea')) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'j') step(1);
    else if (e.key === 'k') step(-1);
    else if (e.key === 'n') nextTodo();
    else if (e.key === '/') { e.preventDefault(); document.getElementById('q').focus(); }
  });

  render();
</script>
"""


# ------------------------------------------------------------------ fragments

def _target_cards(target: dict) -> str:
    blocks = [
        ("Common job titles", target.get("common_titles") or [], "accent"),
        ("Most important skills", target.get("core_skills") or [], "good"),
        ("Most demanded technologies", target.get("technologies") or [], ""),
        ("Domain knowledge", target.get("domains") or [], "warn"),
        ("Keywords worth echoing", target.get("keywords") or [], ""),
    ]
    cards = []
    for heading, items, tone in blocks:
        if not items:
            continue
        pills = "".join(
            f'<span class="pill {tone}">{html.escape(str(item))}</span>' for item in items[:16])
        cards.append(f'<div class="card"><h3>{html.escape(heading)}</h3>'
                     f'<div class="pills">{pills}</div></div>')

    responsibilities = target.get("responsibilities") or []
    if responsibilities:
        items = "".join(f"<li>{html.escape(str(r))}</li>" for r in responsibilities[:10])
        cards.append(f'<div class="card"><h3>Recurring responsibilities</h3>'
                     f'<ul class="tight">{items}</ul></div>')
    return "\n".join(cards)


def _job_cards(jobs: list[dict]) -> str:
    cards = []
    for index, job in enumerate(jobs, start=1):
        skills_pills = "".join(
            f'<span class="pill">{html.escape(str(s))}</span>'
            for s in (job.get("key_skills") or job.get("skills") or [])[:10])
        requirements = "".join(
            f"<li>{html.escape(str(r))}</li>" for r in (job.get("key_requirements") or [])[:8])
        meta = " &middot; ".join(html.escape(str(part)) for part in (
            job.get("location") or "location not stated",
            job.get("experience_label") or "experience not stated",
            job.get("salary_label") or "salary not stated",
            job.get("posted_label") or "",
        ) if part)

        jd_text = (job.get("jd_text") or job.get("description") or "").strip()
        jd_block = (
            f'<details class="jd"><summary>Full job description '
            f'({len(jd_text):,} characters)</summary>'
            f'<div class="jd-text">{html.escape(jd_text)}</div></details>'
            if jd_text else
            '<p class="job-meta">No description text was available for this posting.</p>')

        cards.append(f"""<article class="job">
  <div class="job-head">
    <div class="job-rank">{index}</div>
    <div>
      <div class="job-title"><a href="{html.escape(job.get('url') or '#')}" target="_blank" rel="noopener">{html.escape(job.get('title') or '')}</a></div>
      <div class="job-company">{html.escape(job.get('company') or '')}</div>
    </div>
    <div class="job-score">{job.get('score', '-')}<small>score</small></div>
  </div>
  <p class="job-summary">{html.escape(job.get('summary') or '')}</p>
  <div class="job-meta">{meta}</div>
  {f'<div class="q-tags">{skills_pills}</div>' if skills_pills else ''}
  {f'<div class="job-meta" style="margin-top:9px"><strong>Insists on:</strong></div><ul class="tight">{requirements}</ul>' if requirements else ''}
  {f'<p class="job-meta"><strong>Your fit:</strong> {html.escape(job.get("fit_note") or "")}</p>' if job.get('fit_note') else ''}
  {jd_block}
</article>""")
    return "\n".join(cards)


def _skill_rows(matrix: list[dict]) -> str:
    tone = {"strong": "good", "moderate": "warn", "gap": "bad"}
    rows = []
    for row in matrix:
        share = row["jd_count"] / max(row["jd_total"], 1) * 100
        rows.append(f"""<tr>
  <td class="skill-name">{html.escape(row['skill'])}</td>
  <td class="evidence">{html.escape(row['category'])}</td>
  <td><div class="bar"><span class="track"><i class="fill {row['status']}" style="width:{share:.0f}%"></i></span>
      <span class="n">{row['jd_count']}/{row['jd_total']}</span></div></td>
  <td><span class="pill">{html.escape(row['importance'])}</span></td>
  <td><span class="pill {tone[row['status']]}">{html.escape(row['profile_match'])}</span></td>
  <td class="evidence">{html.escape(row['evidence'])}</td>
</tr>""")
    return "\n".join(rows)


def _gap_cards(matrix: list[dict], gap_analysis: dict) -> str:
    notes: dict[str, dict] = {}
    for bucket in ("strong", "moderate", "gaps"):
        for entry in gap_analysis.get(bucket) or []:
            if isinstance(entry, dict) and entry.get("skill"):
                notes[entry["skill"].strip().lower()] = entry

    def card(heading, blurb, rows, tone, note_keys):
        if not rows:
            return (f'<div class="card"><h3>{html.escape(heading)}</h3>'
                    f'<p class="evidence" style="margin:0">Nothing in this bucket.</p></div>')
        items = []
        for row in rows[:14]:
            note = notes.get(row["skill"].lower()) or {}
            detail = next((note.get(key) for key in note_keys if note.get(key)), "")
            items.append(
                f'<li><strong>{html.escape(row["skill"])}</strong> '
                f'<span class="evidence">&mdash; {row["jd_count"]}/{row["jd_total"]} JDs</span>'
                + (f'<br><span class="evidence">{html.escape(str(detail))}</span>' if detail else "")
                + "</li>")
        return (f'<div class="card"><h3>{html.escape(heading)}</h3>'
                f'<p class="evidence" style="margin:-4px 0 9px">{html.escape(blurb)}</p>'
                f'<ul class="tight">{"".join(items)}</ul></div>')

    strong = [r for r in matrix if r["status"] == "strong"]
    moderate = [r for r in matrix if r["status"] == "moderate"]
    gaps = [r for r in matrix if r["status"] == "gap"]

    return "\n".join([
        card("Strong skills", "Backed by your experience bullets - lead with these.",
             strong, "good", ("why",)),
        card("Skills to strengthen", "Claimed on your profile but not evidenced in the "
             "narrative. Have a concrete example ready.", moderate, "warn",
             ("how_to_strengthen", "why")),
        card("Important missing skills", "Wanted by these employers and absent from your "
             "resume. Study these first, and answer them honestly.", gaps, "bad",
             ("study_plan", "why_it_matters")),
    ])


def _checks(prep: dict) -> str:
    result = prep.get("validation") or {}
    rows = []
    for check in result.get("checks") or []:
        mark = "PASS" if check.get("ok") else "FAIL"
        css = "" if check.get("ok") else ' class="fail"'
        rows.append(f'<div{css}>[{mark}] {html.escape(check.get("check", ""))} '
                    f'&mdash; {html.escape(check.get("detail", ""))}</div>')
    return "\n".join(rows) or "<div>No validation record.</div>"


def _date_options(current: str, stamps: list[str], index: dict | None = None) -> str:
    """The history picker: every run, labelled by day and scan time.

    Three runs a day means three entries per date, so a bare date is not
    enough to tell them apart. Each option carries the run number and, where
    the index recorded it, the clock time of the scan it was built from -
    which is the thing you actually remember ("the one from lunchtime").
    """
    from . import store

    index = index or {}
    options = []
    for stamp in stamps:
        day, run = store.split_run(stamp)
        meta = index.get(stamp) or {}
        scan_at = (meta.get("scan_at") or "")[11:16]
        label = f"{day} · run {run}" + (f" · {scan_at}" if scan_at else "")
        jobs = meta.get("jobs")
        if jobs and jobs != 10:
            label += f" ({jobs} JDs)"
        selected = " selected" if stamp == current else ""
        options.append(
            f'<option value="interview-prep-{stamp}.html"{selected}>{html.escape(label)}</option>')
    return "\n".join(options) or f'<option selected>{html.escape(current)}</option>'


def _skill_options(matrix: list[dict]) -> str:
    options = ['<option value="all">Any skill</option>']
    for row in matrix:
        options.append(f'<option value="{html.escape(row["skill"])}">'
                       f'{html.escape(row["skill"])} ({row["jd_count"]}/{row["jd_total"]})</option>')
    return "\n".join(options)


# ---------------------------------------------------------------------- build

def build(prep: dict, out_path: Path | None = None, dates: list[str] | None = None) -> Path:
    """Write the preparation page for one run's prep dict. Returns the path."""
    from . import store

    day = prep["date"]
    # Files are per RUN, not per day - see store.py. A prep written before run
    # ids existed has no run_id and keeps its bare-date filename.
    stamp = prep.get("run_id") or day
    jobs = prep.get("jobs") or []
    matrix = prep.get("skill_matrix") or []
    questions = prep.get("questions") or []
    target = prep.get("target_profile") or {}
    gaps = [row for row in matrix if row["status"] == "gap"]

    # The page keys progress on the question text, so it survives renumbering
    # and carries over to a later day that reuses the same question.
    payload_questions = []
    for question in questions:
        item = dict(question)
        item["qkey"] = qkey(question["question"])
        payload_questions.append(item)

    data = {
        "date": day,
        "jd_count": len(jobs),
        "level_labels": LEVEL_LABELS,
        "questions": payload_questions,
    }

    dates = dates or store.prep_runs() or [stamp]
    if stamp not in dates:
        dates = sorted(set(dates + [stamp]), key=store._sort_key, reverse=True)

    # The scanner claims a run slot per scan, like this module does, so the
    # page for a day is openings-<day>-r3.html and not openings-<day>.html.
    # Link to that day's newest run; days before the slot scheme have the
    # un-suffixed name, which day_runs() still returns.
    from ..jobs.page import day_runs
    same_day = day_runs(day)
    if same_day:
        scanner = f"../jobs/{same_day[-1].name}"
    else:
        existing = sorted(JOBS_DIR.glob("openings-*.html"), reverse=True)
        scanner = f"../jobs/{existing[0].name}" if existing else "#"

    resume_name = Path(prep.get("profile", {}).get("resume_path") or "resume.txt").name
    engine_label = prep.get("engine") or "a local model"
    if prep.get("model"):
        engine_label += f" ({prep['model']})"

    counts = (prep.get("validation") or {}).get("counts") or {}
    heading = (f"{len(questions)} questions for the {day} Top 10"
               if questions else f"Preparation for {day}")
    subtitle = (
        f"Built from the {len(jobs)} highest-scoring jobs in the {day} scan and your resume. "
        f"{counts.get('basic', 0)} basic, {counts.get('intermediate', 0)} intermediate and "
        f"{counts.get('advanced', 0)} advanced questions, each traceable to the job "
        f"descriptions that motivated it.")

    page = (TEMPLATE
            .replace("__TITLE__", f"Interview Prep {day}")
            .replace("__HEADING__", html.escape(heading))
            .replace("__SUBTITLE__", html.escape(subtitle))
            .replace("__DATELINE__", day)
            .replace("__GENERATED__", prep.get("generated_at") or day)
            .replace("__JD_COUNT__", str(len(jobs)))
            .replace("__Q_COUNT__", str(len(questions)))
            .replace("__SKILL_COUNT__", str(len(matrix)))
            .replace("__GAP_COUNT__", str(len(gaps)))
            .replace("__PRIMARY_ROLE__", html.escape(target.get("primary_role") or skills.PRIMARY_ROLE))
            .replace("__MARKET_SUMMARY__", html.escape(target.get("market_summary") or
                                                       "No market summary was produced."))
            .replace("__TARGET_CARDS__", _target_cards(target))
            .replace("__JOB_CARDS__", _job_cards(jobs))
            .replace("__SKILL_ROWS__", _skill_rows(matrix))
            .replace("__GAP_CARDS__", _gap_cards(matrix, prep.get("gap_analysis") or {}))
            .replace("__SKILL_OPTIONS__", _skill_options(matrix))
            .replace("__DATE_OPTIONS__", _date_options(stamp, dates, store.load_index()))
            .replace("__SCANNER_HREF__", html.escape(scanner))
            .replace("__RESUME_NAME__", html.escape(resume_name))
            .replace("__ENGINE__", html.escape(engine_label))
            .replace("__CHECKS__", _checks(prep))
            .replace("__DATA__", _safe_json(data)))

    out_path = out_path or (PREP_DIR / f"interview-prep-{stamp}.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    log.info("Wrote %d question(s) to %s", len(questions), out_path)
    return out_path


def build_from_file(prep_path: Path, out_path: Path | None = None) -> Path:
    prep = json.loads(Path(prep_path).read_text(encoding="utf-8"))
    return build(prep, out_path)


def rebuild_all() -> list[Path]:
    """Rebuild every run's page, so the picker on each lists all the others."""
    from . import store

    stamps = store.prep_runs()
    written = []
    for stamp in stamps:
        prep = store.load_prep(stamp)
        if prep:
            written.append(build(prep, dates=stamps))
    return written
