"""Capture the structure of a live screening questionnaire, without answering.

The answering code needs to know what the drawer actually looks like - how a
question is marked up, whether choices are chips or a dropdown, which control
advances to the next question. That cannot be read off a logged-out page: the
drawer only exists after Apply is clicked on a real posting.

So this opens the highest-scoring queued job that has a questionnaire, clicks
Apply once, writes everything it can see to data/jobs/questionnaire-probe.json,
and closes the drawer without typing a single answer. The application is not
submitted - a questionnaire posting only completes once its questions are
answered.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .. import selectors as S

log = logging.getLogger("naukri.jobs.probe")

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "data" / "jobs"
QUEUE_PATH = JOBS_DIR / "review_queue.json"
OUT_PATH = JOBS_DIR / "questionnaire-probe.json"
SHOT_PATH = JOBS_DIR / "questionnaire-probe.png"

# Dumps the drawer: its own markup, every question-looking block, and every
# control that could hold or advance an answer.
_DUMP_JS = """
() => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const desc = n => {
    const cls = String(n.className && n.className.baseVal !== undefined
      ? n.className.baseVal : n.className || '');
    return `${n.tagName}${n.id ? '#' + n.id : ''}` +
           (cls ? '.' + cls.trim().split(/\\s+/).slice(0, 4).join('.') : '');
  };
  const drawer = document.querySelector(
    '#chatbot_Drawer, .chatbot_DrawerContentWrapper, [class*="chatbot" i]');
  if (!drawer) {
    return {found: false, bodyTail: norm(document.body.innerText).slice(-800)};
  }
  const controls = [];
  drawer.querySelectorAll('input, textarea, select, button, li, [role="button"]').forEach((n, i) => {
    if (i > 120) return;
    controls.push({
      sel: desc(n),
      tag: n.tagName,
      type: n.type || null,
      placeholder: n.placeholder || null,
      text: norm(n.innerText || n.value || '').slice(0, 90),
      visible: n.checkVisibility ? n.checkVisibility() : true,
    });
  });
  const blocks = [];
  drawer.querySelectorAll('div, p, span, label').forEach((n, i) => {
    if (i > 300 || n.children.length > 2) return;
    const t = norm(n.innerText);
    if (t.length > 8 && t.length < 220) blocks.push({sel: desc(n), text: t});
  });
  // Naukri's Save/Next control is a styled div, not a <button>, so it has to
  // be found by its text across every tag rather than by element type.
  const actions = [];
  drawer.querySelectorAll('*').forEach(n => {
    if (n.children.length > 1) return;
    const t = norm(n.innerText);
    if (/^(save|submit|next|send|continue|done|skip)$/i.test(t)) {
      actions.push({sel: desc(n), tag: n.tagName, text: t,
                    visible: n.checkVisibility ? n.checkVisibility() : true});
    }
  });
  // The current question is the last thing the bot said.
  const asked = Array.from(drawer.querySelectorAll('li.botItem .botMsg, li.botItem'))
    .map(n => norm(n.innerText)).filter(Boolean);
  return {
    found: true,
    drawerSel: desc(drawer),
    text: norm(drawer.innerText).slice(0, 2000),
    controls,
    blocks: blocks.slice(0, 60),
    actions,
    questions: asked,
    currentQuestion: asked.length ? asked[asked.length - 1] : null,
    html: drawer.innerHTML.slice(0, 40000),
  };
}
"""


def _pick_target(url: str | None) -> dict:
    if url:
        return {"url": url, "title": "(supplied)", "company": "", "score": None}
    if not QUEUE_PATH.exists():
        raise FileNotFoundError(
            f"No queue at {QUEUE_PATH}. Run: python main.py --jobs"
        )
    queue = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    candidates = [e for e in queue if "questionnaire" in (e.get("reason") or "")]
    if not candidates:
        raise ValueError("No queued job has a questionnaire. Run --jobs again.")
    return max(candidates, key=lambda e: e.get("score") or 0)


def probe(url: str | None = None, headless: bool = False) -> dict:
    """Open one questionnaire and record its shape. Answers nothing."""
    from playwright.sync_api import sync_playwright

    from ..session import DEFAULT_STATE, open_profile

    target = _pick_target(url)
    log.info("Probing: %s @ %s (score %s)",
             target.get("title"), target.get("company"), target.get("score"))
    log.info("  %s", target["url"])

    with sync_playwright() as p:
        browser, _ctx, page = open_profile(p, DEFAULT_STATE, headless=headless)
        try:
            page.goto(target["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)

            button = None
            for selector in S.JOB_APPLY_BUTTON:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible(timeout=3000):
                    button = locator
                    break
            if button is None:
                raise RuntimeError("No apply button on the page - posting may have closed.")

            label = (button.inner_text(timeout=3000) or "").strip()
            log.info("  apply button reads: %r", label)
            if any(m in label.lower() for m in S.APPLY_OFFSITE_LABELS):
                raise RuntimeError(f"That job applies off-site ({label!r}); pick another.")

            button.click(timeout=8000)
            page.wait_for_timeout(6000)

            result = page.evaluate(_DUMP_JS)
            result["job"] = target
            result["apply_button_label"] = label

            JOBS_DIR.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOT_PATH))
            OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

            # Leave without answering anything.
            for selector in S.JOB_CHATBOT_CLOSE:
                locator = page.locator(selector).first
                try:
                    if locator.count() and locator.is_visible(timeout=1500):
                        locator.click(timeout=3000)
                        break
                except Exception:
                    continue
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(1500)
        finally:
            browser.close()

    return result


def summarise(result: dict) -> str:
    if not result.get("found"):
        return (
            "\n  No questionnaire drawer appeared after Apply.\n"
            f"  Tail of the page: {str(result.get('bodyTail'))[:300]}\n"
            f"  Screenshot: {SHOT_PATH}\n"
        )
    controls = [c for c in result.get("controls", []) if c.get("visible")]
    lines = [
        "",
        f"  Questionnaire captured from: {result['job'].get('title')}",
        f"  Drawer: {result.get('drawerSel')}",
        "",
        "  Visible text:",
    ]
    lines += [f"    {line}" for line in str(result.get("text", ""))[:700].split(". ")[:8]]
    lines += ["", f"  {len(controls)} visible control(s):"]
    for control in controls[:15]:
        lines.append(
            f"    {control['sel']} [{control['tag']}/{control['type']}] {control['text'][:60]}"
        )
    lines += [
        "",
        f"  Full dump:   {OUT_PATH}",
        f"  Screenshot:  {SHOT_PATH}",
        "",
        "  Nothing was answered and nothing was submitted.",
        "",
    ]
    return "\n".join(lines)
