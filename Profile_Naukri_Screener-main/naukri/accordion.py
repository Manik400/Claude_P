"""The shared page kit for every generated page (openings, applications, interview prep, accuracy).

HEAD goes right after the page's viewport meta. It applies the Job Hunt site's
choices before the page paints: the theme (jh:theme = light / dark / auto -
auto leaves the page to follow the device) and the skin (jh:ui = v2 loads the
portfolio look). A page opened inside the site's viewer is same-origin, so it
reads the same keys.

SNIPPET goes at the end of the body:

  - collapsible filter groups: each group in a toolbar is written as
        <details class="fgrp" data-acc="<page>.<group>" open><summary>Posted</summary>
          <span class="fbody"> ...chips / selects... </span></details>
    and remembers its open / closed state;
  - a "Filters" button on every filter toolbar that hides or shows the whole
    toolbar (remembered per page type);
  - the V2 skin as one generic layer over the pages' own colour variables;
  - thin scrollbars that follow the theme, and live updates when the site's
    theme or skin changes while the page is open.

The filter scripts select their controls by attribute, so none of this changes
how filtering works.
"""

FONTS = "https://fonts.googleapis.com/css2?family=Archivo+Black&family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;700&display=swap"

HEAD = r"""<script>(function () {
  try {
    var r = document.documentElement, t = localStorage.getItem('jh:theme') || 'auto';
    if (t === 'light' || t === 'dark') r.setAttribute('data-theme', t);
    if (localStorage.getItem('jh:ui') === 'v2') {
      r.setAttribute('data-ui', 'v2');
      var l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '""" + FONTS + r"""'; document.head.appendChild(l);
    }
  } catch (e) { /* private window: follow the device */ }
})();</script>
"""

SNIPPET = r"""
<style>
  details.fgrp { display: inline-block; vertical-align: middle; border: 1px solid rgba(127,127,127,.28);
    border-radius: 12px; padding: 3px 6px; }
  details.fgrp > summary { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; list-style: none;
    font-size: 0.6875rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; opacity: .7;
    padding: 4px 4px; white-space: nowrap; user-select: none; }
  details.fgrp > summary::-webkit-details-marker { display: none; }
  details.fgrp > summary::before { content: "\25B8"; font-size: 0.625rem; transition: transform .15s; }
  details.fgrp[open] > summary::before { transform: rotate(90deg); }
  details.fgrp > summary:hover { opacity: 1; }
  details.fgrp > .fbody { display: inline-flex; flex-wrap: wrap; gap: 6px; align-items: center; vertical-align: middle; margin-left: 4px; }
  details.fgrp:not([open]) { opacity: .9; }

  /* the whole filter toolbar can be hidden: only its Filters button stays */
  .tb-toggle { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font: inherit; font-size: 0.75rem; font-weight: 700;
    letter-spacing: .05em; text-transform: uppercase; padding: 5px 10px; border-radius: 8px; border: 1px solid rgba(127,127,127,.35);
    background: transparent; color: inherit; opacity: .85; flex: none; }
  .tb-toggle:hover { opacity: 1; }
  .tb-toggle::after { content: "\25B4"; font-size: 0.7rem; }
  .tb-hidden .tb-toggle::after { content: "\25BE"; }
  .tb-hidden > :not(.tb-toggle) { display: none !important; }
  .tb-hidden { padding-top: 4px !important; padding-bottom: 4px !important; }

  /* thin scrollbars that follow the page's light / dark theme */
  :root { color-scheme: light dark; } :root[data-theme="light"] { color-scheme: light; } :root[data-theme="dark"] { color-scheme: dark; }
  * { scrollbar-width: thin; }

  /* V2 skin (the site's portfolio look): one layer over each page's own variables */
  :root[data-ui="v2"] {
    --bg: #E9EAE4; --surface: #FFFFFF; --surface-2: #F5F6F2; --card: #FFFFFF; --card2: #F5F6F2;
    --ink: #11151A; --fg: #11151A; --muted: #4E575F; --line: #11151A; --line2: #C9CCC3;
    --accent: #EE3D28; --accent-on: #FFFFFF; --accent-soft: rgba(238,61,40,.12); --accent-bg: rgba(238,61,40,.12);
    --v2-mono: 'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace; --v2-display: 'Archivo Black', Impact, system-ui, sans-serif;
  }
  @media (prefers-color-scheme: dark) { :root[data-ui="v2"]:not([data-theme="light"]) {
    --bg: #0D1114; --surface: #151A1F; --surface-2: #1B2228; --card: #151A1F; --card2: #1B2228;
    --ink: #ECEEE9; --fg: #ECEEE9; --muted: #98A4AC; --line: #2B333A; --line2: #232A30;
    --accent: #FF5F49; --accent-on: #11151A; --accent-soft: rgba(255,95,73,.16); --accent-bg: rgba(255,95,73,.16); } }
  :root[data-ui="v2"][data-theme="dark"] {
    --bg: #0D1114; --surface: #151A1F; --surface-2: #1B2228; --card: #151A1F; --card2: #1B2228;
    --ink: #ECEEE9; --fg: #ECEEE9; --muted: #98A4AC; --line: #2B333A; --line2: #232A30;
    --accent: #FF5F49; --accent-on: #11151A; --accent-soft: rgba(255,95,73,.16); --accent-bg: rgba(255,95,73,.16); }
  :root[data-ui="v2"] body, :root[data-ui="v2"] button, :root[data-ui="v2"] input, :root[data-ui="v2"] select, :root[data-ui="v2"] textarea {
    font-family: 'Archivo', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }
  :root[data-ui="v2"] h1, :root[data-ui="v2"] h2, :root[data-ui="v2"] h3 { font-family: var(--v2-display); font-weight: 400; letter-spacing: -.01em; }
  :root[data-ui="v2"] .chip, :root[data-ui="v2"] .tag, :root[data-ui="v2"] .pill, :root[data-ui="v2"] .ghost, :root[data-ui="v2"] .tb-toggle,
  :root[data-ui="v2"] details.fgrp > summary, :root[data-ui="v2"] .muted, :root[data-ui="v2"] th, :root[data-ui="v2"] code {
    font-family: var(--v2-mono); letter-spacing: .02em; }
  :root[data-ui="v2"] *:not(svg):not(path):not(circle) { border-radius: 0 !important; }
  :root[data-ui="v2"] button, :root[data-ui="v2"] input, :root[data-ui="v2"] select, :root[data-ui="v2"] textarea,
  :root[data-ui="v2"] .chip, :root[data-ui="v2"] .tb-toggle, :root[data-ui="v2"] details.fgrp { border: 2px solid var(--line) !important; }
  :root[data-ui="v2"] button, :root[data-ui="v2"] .chip, :root[data-ui="v2"] .tb-toggle { box-shadow: 2px 2px 0 var(--line); font-weight: 700; }
  :root[data-ui="v2"] .chip[aria-pressed="true"], :root[data-ui="v2"] button[aria-pressed="true"] { background: var(--accent) !important; color: #fff !important; }
  :root[data-ui="v2"] [class*="card"], :root[data-ui="v2"] .app, :root[data-ui="v2"] .stat, :root[data-ui="v2"] section,
  :root[data-ui="v2"] .q, :root[data-ui="v2"] .row, :root[data-ui="v2"] article { border-color: var(--line) !important; box-shadow: 3px 3px 0 var(--line); }
</style>
<script>
(function () {
  "use strict";
  // collapsible filter groups, open / closed remembered
  document.querySelectorAll("details.fgrp[data-acc]").forEach(function (d) {
    var key = "acc:" + d.getAttribute("data-acc");
    try { var v = localStorage.getItem(key); if (v !== null) d.open = v === "1"; } catch (e) { /* private window */ }
    d.addEventListener("toggle", function () {
      try { localStorage.setItem(key, d.open ? "1" : "0"); } catch (e) { /* private window */ }
    });
  });

  // a Filters button on every filter toolbar: hides / shows the whole bar
  var kind = (document.title || "page").split(/\s+/).slice(0, 2).join("-").toLowerCase();
  var bars = Array.prototype.filter.call(document.querySelectorAll(".bar-tools, section.controls, div.bar"), function (el) {
    return el.querySelector(".chip, input[type=search], .search, select");   // a real filter bar, not a progress bar
  });
  bars.forEach(function (bar, i) {
    if (bar.querySelector(":scope > .tb-toggle")) return;
    var key = "tb:" + kind + ":" + i, btn = document.createElement("button");
    btn.type = "button"; btn.className = "tb-toggle";
    function paint(hidden) {
      bar.classList.toggle("tb-hidden", hidden);
      btn.textContent = hidden ? "Show filters" : "Filters";
      btn.setAttribute("aria-expanded", hidden ? "false" : "true");
      btn.title = hidden ? "Show the filters" : "Hide the filters";
    }
    var hidden = false;
    try { hidden = localStorage.getItem(key) === "1"; } catch (e) {}
    bar.insertBefore(btn, bar.firstChild);
    paint(hidden);
    btn.addEventListener("click", function () {
      var h = !bar.classList.contains("tb-hidden"); paint(h);
      try { h ? localStorage.setItem(key, "1") : localStorage.removeItem(key); } catch (e) {}
    });
  });

  // the site's theme / skin changed while this page is open: follow it
  window.addEventListener("storage", function (e) {
    if (e.key !== "jh:theme" && e.key !== "jh:ui") return;
    var r = document.documentElement, t = localStorage.getItem("jh:theme") || "auto";
    if (t === "light" || t === "dark") r.setAttribute("data-theme", t); else r.removeAttribute("data-theme");
    if (localStorage.getItem("jh:ui") === "v2") r.setAttribute("data-ui", "v2"); else r.removeAttribute("data-ui");
  });
})();
</script>
"""
