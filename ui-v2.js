/* Job Hunt - the UI v2 switch.
 *
 * One button, added next to the theme control: it sets data-ui="v2" on <html>,
 * which is all ui-v2.css needs to repaint the whole page in the portfolio's
 * look (paper and ink, Archivo Black over JetBrains Mono, square corners, hard
 * shadows). Nothing else about the page changes - same tabs, same data, same
 * behaviour - so switching back is instant and nothing can be lost in it.
 *
 * The choice is remembered per browser. The fonts are only fetched the first
 * time v2 is switched on, so the classic UI never pays for them, and if the
 * network refuses them the skin falls back to Impact / the system mono.
 */
(function () {
  "use strict";
  var KEY = "jh:ui";
  var FONTS = "https://fonts.googleapis.com/css2?family=Archivo+Black&family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;700&display=swap";

  function stored() {
    try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; }
  }
  function remember(value) {
    try { value ? localStorage.setItem(KEY, value) : localStorage.removeItem(KEY); } catch (e) { /* private window */ }
  }
  function fonts() {
    if (document.getElementById("ui-v2-fonts")) return;
    var l = document.createElement("link");
    l.id = "ui-v2-fonts"; l.rel = "stylesheet"; l.href = FONTS;
    document.head.appendChild(l);
  }
  function on() { return document.documentElement.getAttribute("data-ui") === "v2"; }

  function paint(btn) {
    if (!btn) return;
    btn.setAttribute("aria-pressed", on() ? "true" : "false");
    btn.title = on() ? "Switch back to the classic layout" : "Switch to the portfolio look";
    btn.innerHTML = '<span aria-hidden="true">' + (on() ? "■" : "□") + "</span>" +
      '<span class="ui-switch-label">' + (on() ? "v2" : "v1") + "</span>";
  }

  function apply(v2) {
    if (v2) { fonts(); document.documentElement.setAttribute("data-ui", "v2"); }
    else { document.documentElement.removeAttribute("data-ui"); }
    remember(v2 ? "v2" : "");
    paint(document.getElementById("ui-switch"));
  }

  function mount() {
    if (document.getElementById("ui-switch")) return;
    // Next to whatever sits in the brand row (theme button, PC status); falls
    // back to the top of the page if the shell ever changes.
    var host = document.querySelector(".brand") || document.querySelector("aside.side") || document.body;
    var btn = document.createElement("button");
    btn.id = "ui-switch";
    btn.type = "button";
    btn.className = "ui-switch";
    btn.addEventListener("click", function () { apply(!on()); });
    host.appendChild(btn);
    paint(btn);
  }

  if (stored() === "v2") apply(true);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
