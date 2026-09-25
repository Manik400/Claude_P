"""Collapsible filter groups for the generated pages (openings, applications, interview prep).

Each filter group in a page's toolbar is written as

    <details class="fgrp" data-acc="<page>.<group>" open>
      <summary>Posted</summary><span class="fbody"> ...chips / selects... </span>
    </details>

and the page gets SNIPPET (via its "__ACC__" placeholder), which styles the
groups to sit inline in the toolbar and remembers each one's open/closed state
in localStorage. The filter scripts select their controls by attribute, so the
wrapper changes nothing about how filtering works.
"""

SNIPPET = r"""
<style>
  details.fgrp { display: inline-block; vertical-align: middle; border: 1px solid rgba(127,127,127,.28);
    border-radius: 12px; padding: 3px 6px; }
  details.fgrp > summary { display: inline-flex; align-items: center; gap: 4px; cursor: pointer; list-style: none;
    font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; opacity: .7;
    padding: 4px 4px; white-space: nowrap; user-select: none; }
  details.fgrp > summary::-webkit-details-marker { display: none; }
  details.fgrp > summary::before { content: "\25B8"; font-size: 10px; transition: transform .15s; }
  details.fgrp[open] > summary::before { transform: rotate(90deg); }
  details.fgrp > summary:hover { opacity: 1; }
  details.fgrp > .fbody { display: inline-flex; flex-wrap: wrap; gap: 6px; align-items: center; vertical-align: middle; margin-left: 4px; }
  details.fgrp:not([open]) { opacity: .9; }
</style>
<script>
(function () {
  "use strict";
  document.querySelectorAll("details.fgrp[data-acc]").forEach(function (d) {
    var key = "acc:" + d.getAttribute("data-acc");
    try { var v = localStorage.getItem(key); if (v !== null) d.open = v === "1"; } catch (e) { /* private window */ }
    d.addEventListener("toggle", function () {
      try { localStorage.setItem(key, d.open ? "1" : "0"); } catch (e) { /* private window */ }
    });
  });
})();
</script>
"""
