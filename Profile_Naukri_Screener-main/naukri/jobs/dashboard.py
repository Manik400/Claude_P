"""The dashboard: one local page to edit your answers and follow applications.

    python main.py --dashboard            http://127.0.0.1:8765, opens your browser
    python main.py --dashboard --port N

A plain page cannot write to disk, so this is a small local server (standard
library only, bound to 127.0.0.1) with four tabs:

    My answers      the common form - expected CTC, phone, notice period,
                    years per skill, your Yes/No position on the standard
                    screening questions, and every free-text answer in the
                    answer bank. Saved to data/jobs/my_answers.yaml and
                    data/jobs/answer_bank.yaml; used by the next run.
    Questions       what the last runs could not answer. Answer here, and the
                    jobs waiting on them are re-attempted next run.
    Applications    every application sent, its questions and answers, and
                    what came back - recruiter replies pulled from Gmail
                    (responses.py), plus your own status and notes.
    Settings        the Gmail app password used to read replies.

Nothing here talks to Naukri or LinkedIn; it edits the files the scheduled
runs read.
"""
from __future__ import annotations

import json
import logging
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import applications, config as config_mod, my_answers, questions, responses

log = logging.getLogger("naukri.jobs.dashboard")

ROOT = Path(__file__).resolve().parent.parent.parent
NOTES_PATH = ROOT / "data" / "jobs" / "application_notes.json"

MANUAL_STATUSES = ["", "viewed", "shortlisted", "interview", "offer", "rejected", "withdrawn"]


def _load_notes() -> dict:
    if not NOTES_PATH.exists():
        return {}
    try:
        data = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_notes(notes: dict) -> None:
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTES_PATH.write_text(json.dumps(notes, indent=1, ensure_ascii=False), encoding="utf-8")


def state() -> dict:
    """Everything the page renders, in one JSON."""
    try:
        profile = config_mod.load_profile()
        config = config_mod.load(profile=profile)
    except config_mod.ConfigError as exc:
        profile, config = {}, {"answers": {}, "skill_years": {}, "profile_skills": []}
        log.warning("Dashboard without a profile: %s", exc)
    bank = [
        {"question": e.get("question", ""), "answer": e.get("answer", ""), "options": e.get("options") or []}
        for e in questions._read_list(questions.BANK_PATH)
    ]
    apps = [a for a in applications.load() if not a.get("dry_run")]
    notes = _load_notes()
    per_app = responses.per_application()
    for app in apps:
        app["response"] = per_app.get(app.get("job_id"))
        app["manual"] = notes.get(app.get("job_id")) or {}
    store = responses.load_store()
    gmail = {"configured": responses.configured(), "email": "", "days": 30,
             "synced_at": store.get("synced_at"), "emails": len(store.get("emails") or []),
             "matched": sum(1 for m in store.get("emails") or [] if m.get("jobs"))}
    if gmail["configured"]:
        cfg = responses.load_config()
        gmail["email"], gmail["days"] = cfg["email"], cfg["days"]
    return {
        "answers": my_answers.form_state(profile, config),
        "bank": bank,
        "pending": questions.load_pending(),
        "applications": list(reversed(apps)),
        "counts": applications.counts(apps),
        "gmail": gmail,
        "manual_statuses": MANUAL_STATUSES,
        "kind_labels": responses.KIND_LABELS,
        "generated": datetime.now().isoformat(timespec="seconds"),
    }


# ------------------------------------------------------------------ actions

def save_answers(payload: dict) -> dict:
    my_answers.save({
        "facts": payload.get("facts") or {},
        "skill_years": payload.get("skill_years") or {},
        "policies": payload.get("policies") or {},
    })
    entries = []
    for item in payload.get("bank") or []:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if question and answer:
            entries.append({"question": question, "answer": answer,
                            "options": list(item.get("options") or []),
                            "answered_at": datetime.now().isoformat(timespec="seconds")})
    questions.save_bank(entries)
    return {"ok": True, "saved": str(my_answers.PATH), "bank": len(entries)}


def save_pending(payload: dict) -> dict:
    given = {questions.key(k): str(v).strip() for k, v in (payload.get("answers") or {}).items()}
    entries = questions.load_pending()
    for entry in entries:
        answer = given.get(questions.key(entry.get("question", "")))
        if answer:
            entry["answer"] = answer
    questions.save_pending(entries)
    absorbed, retry = questions.absorb()
    return {"ok": True, "absorbed": len(absorbed), "retry": len(retry)}


def save_gmail(payload: dict) -> dict:
    address = str(payload.get("email") or "").strip()
    password = str(payload.get("app_password") or "").strip()
    if not address or not password:
        return {"ok": False, "error": "Both the address and the app password are needed."}
    responses.save_config(address, password, int(payload.get("days") or 30))
    return {"ok": True}


def sync_gmail() -> dict:
    try:
        store = responses.sync([a for a in applications.load() if not a.get("dry_run")])
    except responses.GmailNotConfigured as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # imaplib raises plain exceptions on bad logins
        return {"ok": False, "error": f"Gmail sync failed: {str(exc)[:200]}"}
    return {"ok": True, "fetched": store.get("fetched", 0),
            "matched": sum(1 for m in store["emails"] if m.get("jobs")), "synced_at": store["synced_at"]}


def save_note(payload: dict) -> dict:
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        return {"ok": False, "error": "no job id"}
    notes = _load_notes()
    entry = notes.get(job_id) or {}
    if "status" in payload:
        entry["status"] = str(payload.get("status") or "")
    if "note" in payload:
        entry["note"] = str(payload.get("note") or "")
    entry["updated"] = datetime.now().isoformat(timespec="seconds")
    notes[job_id] = entry
    _save_notes(notes)
    return {"ok": True}


ACTIONS = {
    "/api/answers": save_answers,
    "/api/questions": save_pending,
    "/api/gmail": save_gmail,
    "/api/gmail/sync": lambda payload: sync_gmail(),
    "/api/note": save_note,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet; the run log is enough
        log.debug("dashboard: " + fmt, *args)

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            return self._json(state())
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        action = ACTIONS.get(path)
        if action is None:
            return self._json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "bad JSON"}, 400)
        try:
            self._json(action(payload))
        except Exception as exc:
            log.exception("dashboard action %s failed", path)
            self._json({"ok": False, "error": str(exc)[:300]}, 500)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Dashboard: {url}   (Ctrl+C to stop)\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job agent dashboard</title>
<style>
  :root { --bg:#f6f5f1; --surface:#fff; --surface-2:#f0efe9; --line:#dedbd2; --ink:#1c1b18; --muted:#6b6860;
          --accent:#2b5fd9; --accent-soft:#e6edfb; --good:#1e7f4a; --good-soft:#e3f3e9; --warn:#a45d00; --warn-soft:#fbeedb; --bad:#b3261e; --bad-soft:#fbe5e3; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#141413; --surface:#1d1d1b; --surface-2:#262623; --line:#34342f; --ink:#ece9e1; --muted:#a09d94;
            --accent:#7ea2f0; --accent-soft:#1b2a4a; --good:#6ec48c; --good-soft:#14291c; --warn:#e2a24a; --warn-soft:#2e2413; --bad:#ef8a83; --bad-soft:#3a1a18; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family:"Source Sans 3",ui-sans-serif,system-ui,sans-serif; font-size:15px; line-height:1.5; }
  .wrap { max-width:1100px; margin:0 auto; padding:24px 16px 80px; }
  h1 { font-size:clamp(22px,4vw,30px); margin:0 0 4px; letter-spacing:-.02em; }
  h2 { font-size:18px; margin:26px 0 8px; }
  .sub { color:var(--muted); margin:0 0 16px; max-width:75ch; }
  nav { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 20px; }
  nav button { border:1px solid var(--line); background:var(--surface); color:var(--muted); border-radius:999px; padding:7px 14px; font:inherit; cursor:pointer; }
  nav button[aria-pressed="true"] { color:var(--ink); border-color:var(--accent); background:var(--accent-soft); }
  section { display:none; } section.on { display:block; }
  .card { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin-bottom:12px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px; }
  label { display:block; font-size:13px; color:var(--muted); margin-bottom:3px; }
  input[type=text], input[type=number], input[type=email], input[type=password], select, textarea {
    width:100%; border:1px solid var(--line); border-radius:8px; padding:7px 10px; font:inherit; background:var(--surface); color:var(--ink); }
  textarea { min-height:60px; }
  .hint { font-size:12px; color:var(--muted); margin-top:2px; }
  .btn { border:1px solid var(--accent); background:var(--accent); color:#fff; border-radius:8px; padding:8px 16px; font:inherit; cursor:pointer; }
  .btn.ghost { background:transparent; color:var(--accent); }
  .btn.small { padding:4px 10px; font-size:13px; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; vertical-align:top; padding:7px 8px; border-top:1px solid var(--line); }
  th { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; border-top:0; }
  .tag { display:inline-block; font-size:12px; padding:1px 8px; border-radius:999px; border:1px solid var(--line); color:var(--muted); white-space:nowrap; }
  .tag.ok { color:var(--good); background:var(--good-soft); border-color:transparent; }
  .tag.warn { color:var(--warn); background:var(--warn-soft); border-color:transparent; }
  .tag.bad { color:var(--bad); background:var(--bad-soft); border-color:transparent; }
  .tag.board { color:var(--accent); background:var(--accent-soft); border-color:transparent; }
  .status { position:fixed; right:16px; bottom:16px; background:var(--ink); color:var(--bg); padding:8px 14px; border-radius:8px; opacity:0; transition:opacity .2s; }
  .status.show { opacity:1; }
  .app { border-top:1px solid var(--line); padding:10px 0; }
  .app .head { display:flex; flex-wrap:wrap; gap:6px 12px; align-items:baseline; }
  .app .head a { color:var(--ink); font-weight:600; text-decoration:none; }
  .app .when { color:var(--muted); font-size:13px; margin-left:auto; }
  .app details { margin-top:6px; } summary { cursor:pointer; color:var(--muted); font-size:13px; }
  .mail { padding:6px 0 6px 10px; border-left:3px solid var(--line); margin-top:6px; font-size:13px; }
  .mail b { display:block; }
  .policy { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; padding:6px 0; border-top:1px solid var(--line); }
  .policy .opts label { display:inline; margin-right:10px; font-size:14px; color:var(--ink); }
  .stats { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; }
  .stat { background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:8px 14px; min-width:100px; }
  .stat b { display:block; font-size:20px; } .stat span { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
  .empty { color:var(--muted); padding:16px 0; }
  code { font-family:ui-monospace,monospace; font-size:12px; }
  @media (max-width:640px) { .app .when { margin-left:0; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>Job agent dashboard</h1>
  <p class="sub">What the agent says on your behalf, and what comes back. Everything you save here is used by the next scheduled run.</p>
  <nav>
    <button data-tab="answers" aria-pressed="true">My answers</button>
    <button data-tab="questions" aria-pressed="false">Questions waiting <span id="n-pending" class="tag"></span></button>
    <button data-tab="applications" aria-pressed="false">Applications <span id="n-apps" class="tag"></span></button>
    <button data-tab="settings" aria-pressed="false">Settings</button>
  </nav>

  <section id="tab-answers" class="on">
    <div class="card">
      <h2 style="margin-top:0">Facts about you</h2>
      <p class="sub">Blank fields fall back to what your Naukri profile or jobs.yaml says (shown as the placeholder). Type a value to override it.</p>
      <div class="grid" id="facts"></div>
    </div>
    <div class="card">
      <h2 style="margin-top:0">Years per skill</h2>
      <p class="sub">Quoted to recruiters for every "how many years of X" question. Do not round up.</p>
      <table id="skills"><tr><th>Skill</th><th style="width:120px">Years</th><th style="width:60px"></th></tr></table>
      <div class="row" style="margin-top:8px"><input type="text" id="skill-name" list="skill-suggest" placeholder="skill" style="max-width:260px"><datalist id="skill-suggest"></datalist>
        <input type="number" id="skill-years" step="0.5" min="0" placeholder="years" style="max-width:120px"><button class="btn ghost small" id="skill-add">Add</button></div>
    </div>
    <div class="card">
      <h2 style="margin-top:0">Your position on the standard questions</h2>
      <p class="sub">"Ask me" leaves that question for you (it lands in Questions waiting) instead of answering it.</p>
      <div id="policies"></div>
    </div>
    <div class="card">
      <h2 style="margin-top:0">Answers to specific questions</h2>
      <p class="sub">Free-text answers, matched to the exact question. Everything you answer under Questions waiting ends up here too. Edit or delete as you like.</p>
      <table id="bank"><tr><th>Question</th><th style="width:34%">Answer</th><th style="width:60px"></th></tr></table>
      <div class="row" style="margin-top:8px"><input type="text" id="bank-q" placeholder="question, as the recruiter words it"><input type="text" id="bank-a" placeholder="answer" style="max-width:280px"><button class="btn ghost small" id="bank-add">Add</button></div>
    </div>
    <div class="row"><button class="btn" id="save-answers">Save all answers</button><span class="hint" id="answers-path"></span></div>
  </section>

  <section id="tab-questions">
    <div class="card">
      <h2 style="margin-top:0">Questions the agent could not answer</h2>
      <p class="sub">Answer and save. The jobs listed under each question are re-attempted on the next run, and the answer is remembered for every later job that asks it. Type <code>skip</code> to never answer one.</p>
      <div id="pending"></div>
      <div class="row" style="margin-top:12px"><button class="btn" id="save-questions">Save answers</button></div>
    </div>
  </section>

  <section id="tab-applications">
    <div class="stats" id="app-stats"></div>
    <div class="card">
      <div class="row"><button class="btn ghost small" id="sync">Check Gmail for replies</button><span class="hint" id="sync-info"></span>
        <span style="flex:1"></span><input type="text" id="app-q" placeholder="filter by company or title" style="max-width:260px"></div>
      <div id="apps"></div>
    </div>
  </section>

  <section id="tab-settings">
    <div class="card">
      <h2 style="margin-top:0">Gmail, for reading recruiter replies</h2>
      <p class="sub">Uses an <b>app password</b>, not your Google password. Create one at <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener">myaccount.google.com/apppasswords</a> (needs 2-Step Verification on), paste it here, and revoke it there whenever you like. The mailbox is opened read-only; nothing is sent, moved or deleted. Saved to <code>data/gmail.yaml</code> on this PC only.</p>
      <div class="grid">
        <div><label>Gmail address</label><input type="email" id="gm-email"></div>
        <div><label>App password</label><input type="password" id="gm-pass" placeholder="xxxx xxxx xxxx xxxx"></div>
        <div><label>Look back (days)</label><input type="number" id="gm-days" value="30" min="1" max="120"></div>
      </div>
      <div class="row" style="margin-top:10px"><button class="btn" id="save-gmail">Save Gmail settings</button><span class="hint" id="gm-state"></span></div>
    </div>
  </section>
</div>
<div class="status" id="status"></div>

<script>
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let S = null, bank = [], skills = {}, appQuery = '';
  const $ = id => document.getElementById(id);
  function toast(msg, bad) { const t = $('status'); t.textContent = msg; t.style.background = bad ? 'var(--bad)' : 'var(--ink)'; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 2600); }
  async function post(path, body) { const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {})}); return r.json(); }
  async function load() { S = await (await fetch('/api/state')).json(); bank = S.bank.slice(); skills = Object.assign({}, S.answers.skill_years); render(); }

  document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('nav button').forEach(x => x.setAttribute('aria-pressed', x === b));
    document.querySelectorAll('section').forEach(s => s.classList.toggle('on', s.id === 'tab-' + b.dataset.tab));
  }));

  function render() {
    $('n-pending').textContent = S.pending.filter(p => !(p.answer || '').trim()).length;
    $('n-apps').textContent = S.counts.applied;
    renderFacts(); renderSkills(); renderPolicies(); renderBank(); renderPending(); renderApps(); renderSettings();
    $('answers-path').textContent = 'saved to ' + S.answers.path;
  }
  function renderFacts() {
    const a = S.answers;
    $('facts').innerHTML = a.fields.map(f => {
      const v = a.facts[f.id] || {}; const ph = v.from_profile || v.from_jobs_yaml || f.hint || '';
      if (f.kind === 'bool') {
        const cur = v.value === '' ? (v.from_jobs_yaml === '' ? '' : String(v.from_jobs_yaml)) : String(v.value);
        return '<div><label>' + esc(f.label) + '</label><select data-fact="' + f.id + '"><option value="">not set</option><option value="true"' + (cur === 'true' || cur === 'True' ? ' selected' : '') + '>Yes</option><option value="false"' + (cur === 'false' || cur === 'False' ? ' selected' : '') + '>No</option></select></div>';
      }
      return '<div><label>' + esc(f.label) + '</label><input type="text" data-fact="' + f.id + '" value="' + esc(v.value) + '" placeholder="' + esc(ph) + '">' + (f.override && v.from_profile ? '<div class="hint">profile says: ' + esc(v.from_profile) + '</div>' : (f.hint ? '<div class="hint">' + esc(f.hint) + '</div>' : '')) + '</div>';
    }).join('');
  }
  function renderSkills() {
    const t = $('skills'); t.querySelectorAll('tr:not(:first-child)').forEach(r => r.remove());
    Object.keys(skills).sort().forEach(name => {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + esc(name) + '</td><td><input type="number" step="0.5" min="0" value="' + esc(skills[name]) + '" data-skill="' + esc(name) + '"></td><td><button class="btn ghost small" data-del-skill="' + esc(name) + '">remove</button></td>';
      t.appendChild(tr);
    });
    $('skill-suggest').innerHTML = (S.answers.profile_skills || []).map(s => '<option value="' + esc(s) + '">').join('');
  }
  function renderPolicies() {
    $('policies').innerHTML = S.answers.policies.map(p => '<div class="policy"><div>' + esc(p.label) + '<div class="hint">matches: ' + esc(p.match) + '</div></div><div class="opts">' +
      ['yes','no','ask'].map(o => '<label><input type="radio" name="pol-' + p.id + '" value="' + o + '"' + (p.choice === o ? ' checked' : '') + '> ' + (o === 'ask' ? 'Ask me' : o[0].toUpperCase() + o.slice(1)) + '</label>').join('') + '</div></div>').join('');
  }
  function renderBank() {
    const t = $('bank'); t.querySelectorAll('tr:not(:first-child)').forEach(r => r.remove());
    if (!bank.length) { const tr = document.createElement('tr'); tr.innerHTML = '<td colspan="3" class="empty">Nothing saved yet.</td>'; t.appendChild(tr); }
    bank.forEach((e, i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = '<td>' + esc(e.question) + (e.options && e.options.length ? '<div class="hint">options: ' + esc(e.options.join(' / ')) + '</div>' : '') + '</td><td><input type="text" value="' + esc(e.answer) + '" data-bank="' + i + '"></td><td><button class="btn ghost small" data-del-bank="' + i + '">delete</button></td>';
      t.appendChild(tr);
    });
  }
  function renderPending() {
    const waiting = S.pending.filter(p => !(p.answer || '').trim());
    if (!waiting.length) { $('pending').innerHTML = '<p class="empty">Nothing waiting. The agent could answer everything it was asked.</p>'; return; }
    $('pending').innerHTML = waiting.map((p, i) => {
      const jobs = (p.jobs || []).map(j => '<a href="' + esc(j.url) + '" target="_blank" rel="noopener">' + esc(j.title) + '</a> - ' + esc(j.company) + ' <span class="tag board">' + esc(j.board) + '</span>').join('<br>');
      const input = (p.options && p.options.length)
        ? '<select data-pending="' + i + '"><option value="">choose</option>' + p.options.map(o => '<option>' + esc(o) + '</option>').join('') + '<option value="skip">skip - never answer</option></select>'
        : '<input type="text" data-pending="' + i + '" placeholder="your answer (or skip)">';
      return '<div class="card"><b>' + esc(p.question) + '</b><div class="hint">first asked ' + esc(p.first_asked) + ' on ' + esc(p.board) + '</div><div style="margin:8px 0">' + input + '</div><div class="hint">asked by:<br>' + jobs + '</div></div>';
    }).join('');
    $('pending').dataset.map = JSON.stringify(waiting.map(p => p.question));
  }
  function cls(s) { return s === 'applied' || s === 'already' ? 'ok' : (s === 'questionnaire' || s === 'offsite' ? 'warn' : (s === 'error' || s === 'questionnaire-failed' || s === 'unconfirmed' ? 'bad' : '')); }
  function kindCls(k) { return k === 'rejected' ? 'bad' : (k === 'interview' || k === 'shortlisted' || k === 'offer' ? 'ok' : (k === 'viewed' ? 'warn' : '')); }
  const LABELS = {applied:'Applied', already:'Applied earlier', offsite:'Company site', questionnaire:'Needs your answer', 'questionnaire-failed':'Form failed', unconfirmed:'Unconfirmed', 'no-button':'No apply button', error:'Error'};
  function renderApps() {
    const c = S.counts;
    const replied = S.applications.filter(a => a.response || (a.manual && a.manual.status)).length;
    $('app-stats').innerHTML = [['Applied', c.applied], ['Today', c.applied_today], ['Naukri', c.naukri], ['LinkedIn', c.linkedin], ['With a reply', replied], ['Waiting on you', c.waiting]]
      .map(([l, v]) => '<div class="stat"><b>' + v + '</b><span>' + l + '</span></div>').join('');
    const g = S.gmail;
    $('sync-info').textContent = g.configured ? (g.synced_at ? 'last checked ' + g.synced_at.slice(0, 16).replace('T', ' ') + ' - ' + g.emails + ' job mails, ' + g.matched + ' matched' : 'not checked yet') : 'add your Gmail app password under Settings first';
    const q = appQuery.toLowerCase();
    const rows = S.applications.filter(a => !q || (a.title + ' ' + a.company).toLowerCase().includes(q));
    if (!rows.length) { $('apps').innerHTML = '<p class="empty">No applications logged yet.</p>'; return; }
    $('apps').innerHTML = rows.map(a => {
      const r = a.response, m = a.manual || {};
      const reply = m.status ? '<span class="tag ' + kindCls(m.status) + '">' + esc(m.status) + ' (you)</span>' : (r ? '<span class="tag ' + kindCls(r.kind) + '">' + esc(r.label) + '</span>' : '<span class="tag">no reply yet</span>');
      const qa = (a.answers || []).length ? '<table><tr><th>Question</th><th>Answer</th><th>From</th><th>Fix at</th></tr>' + a.answers.map(x => '<tr><td>' + esc(x.question) + '</td><td><b>' + esc(x.answer) + '</b></td><td>' + esc(x.source) + '</td><td class="hint">' + esc(x.fix) + '</td></tr>').join('') + '</table>' : '<div class="hint">One-click apply, no questions asked.</div>';
      const blocked = a.blocked ? '<div class="mail" style="border-color:var(--warn)"><b>Stopped at: ' + esc(a.blocked.question) + '</b>' + esc(a.blocked.why) + '</div>' : '';
      const mails = r ? r.emails.map(e => '<div class="mail"><b>' + esc(e.subject) + ' <span class="tag ' + kindCls(e.kind) + '">' + esc(S.kind_labels[e.kind] || e.kind) + '</span></b>' + esc((e.date || '').slice(0, 16).replace('T', ' ')) + ' - ' + esc(e.from) + '<div class="hint">' + esc(e.snippet) + '</div></div>').join('') : '';
      const manual = '<div class="row" style="margin-top:8px"><label style="margin:0">Your status</label><select data-note-status="' + esc(a.job_id) + '" style="max-width:170px">' + S.manual_statuses.map(s => '<option value="' + s + '"' + (m.status === s ? ' selected' : '') + '>' + (s || 'none') + '</option>').join('') + '</select>' +
        '<input type="text" data-note-text="' + esc(a.job_id) + '" placeholder="note (interview date, recruiter name...)" value="' + esc(m.note || '') + '" style="max-width:420px"><button class="btn ghost small" data-note-save="' + esc(a.job_id) + '">Save</button></div>';
      return '<div class="app"><div class="head"><a href="' + esc(a.url) + '" target="_blank" rel="noopener">' + esc(a.title) + '</a><span class="hint">' + esc(a.company) + '</span><span class="tag board">' + esc(a.board) + '</span>' + (a.project && a.project !== 'naukri' ? '<span class="tag">via ' + esc(a.project) + '</span>' : '') + '<span class="tag ' + cls(a.status) + '">' + esc(LABELS[a.status] || a.status) + '</span>' + reply + '<span class="when">' + esc((a.at || '').slice(0, 16).replace('T', ' ')) + '</span></div>' +
        '<details><summary>questions, answers and replies</summary>' + qa + blocked + mails + manual + '</details></div>';
    }).join('');
  }
  function renderSettings() { $('gm-email').value = S.gmail.email || ''; $('gm-days').value = S.gmail.days || 30; $('gm-state').textContent = S.gmail.configured ? 'configured for ' + S.gmail.email : 'not configured'; }

  document.addEventListener('click', async e => {
    const t = e.target;
    if (t.dataset.delSkill) { delete skills[t.dataset.delSkill]; renderSkills(); }
    if (t.dataset.delBank) { bank.splice(+t.dataset.delBank, 1); renderBank(); }
    if (t.id === 'skill-add') { const n = $('skill-name').value.trim(), y = $('skill-years').value; if (n && y !== '') { skills[n] = +y; $('skill-name').value = ''; $('skill-years').value = ''; renderSkills(); } }
    if (t.id === 'bank-add') { const q = $('bank-q').value.trim(), a = $('bank-a').value.trim(); if (q && a) { bank.push({question: q, answer: a, options: []}); $('bank-q').value = ''; $('bank-a').value = ''; renderBank(); } }
    if (t.id === 'save-answers') {
      document.querySelectorAll('[data-skill]').forEach(i => { skills[i.dataset.skill] = +i.value; });
      document.querySelectorAll('[data-bank]').forEach(i => { bank[+i.dataset.bank].answer = i.value; });
      const facts = {}; document.querySelectorAll('[data-fact]').forEach(i => { facts[i.dataset.fact] = i.value === 'true' ? true : (i.value === 'false' ? false : i.value); });
      const policies = {}; S.answers.policies.forEach(p => { const c = document.querySelector('input[name="pol-' + p.id + '"]:checked'); if (c) policies[p.id] = c.value; });
      const r = await post('/api/answers', {facts, skill_years: skills, policies, bank});
      toast(r.ok ? 'Saved. The next run uses these answers.' : 'Save failed: ' + r.error, !r.ok); if (r.ok) load();
    }
    if (t.id === 'save-questions') {
      const map = JSON.parse($('pending').dataset.map || '[]'); const answers = {};
      document.querySelectorAll('[data-pending]').forEach(i => { if (i.value.trim()) answers[map[+i.dataset.pending]] = i.value.trim(); });
      if (!Object.keys(answers).length) return toast('Nothing to save yet.', true);
      const r = await post('/api/questions', {answers});
      toast(r.ok ? 'Saved ' + r.absorbed + ' answer(s); ' + r.retry + ' job(s) will be re-attempted next run.' : 'Failed: ' + r.error, !r.ok); if (r.ok) load();
    }
    if (t.id === 'save-gmail') {
      const r = await post('/api/gmail', {email: $('gm-email').value, app_password: $('gm-pass').value, days: $('gm-days').value});
      toast(r.ok ? 'Gmail settings saved.' : r.error, !r.ok); if (r.ok) { $('gm-pass').value = ''; load(); }
    }
    if (t.id === 'sync') {
      t.disabled = true; t.textContent = 'Checking...';
      const r = await post('/api/gmail/sync', {});
      t.disabled = false; t.textContent = 'Check Gmail for replies';
      toast(r.ok ? 'Read ' + r.fetched + ' job-related mail(s), ' + r.matched + ' matched to applications.' : r.error, !r.ok); if (r.ok) load();
    }
    if (t.dataset.noteSave) {
      const id = t.dataset.noteSave;
      const r = await post('/api/note', {job_id: id, status: document.querySelector('[data-note-status="' + CSS.escape(id) + '"]').value, note: document.querySelector('[data-note-text="' + CSS.escape(id) + '"]').value});
      toast(r.ok ? 'Saved.' : r.error, !r.ok); if (r.ok) load();
    }
  });
  $('app-q').addEventListener('input', e => { appQuery = e.target.value.trim(); renderApps(); });
  load();
</script>
</body>
</html>
"""
