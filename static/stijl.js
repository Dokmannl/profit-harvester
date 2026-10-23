/* Profit Harvester: wisselen tussen de stijlen "moestuin" en "retro" (Windows 95).
   Wordt in de <head> geladen, zodat de gekozen stijl er meteen staat (geen flits).
   De keuze wordt per browser bewaard; licht/donker blijft los daarvan werken. */
(function () {
  "use strict";
  var KEY = "ph-stijl";
  var html = document.documentElement;

  function lees() { try { return localStorage.getItem(KEY) === "retro" ? "retro" : "moestuin"; } catch (e) { return "moestuin"; } }
  function bewaar(s) { try { localStorage.setItem(KEY, s); } catch (e) { /* geen opslag: alleen deze pagina */ } }

  // ?stijl=retro of ?stijl=moestuin in de adresbalk kiest meteen een stijl
  var gevraagd = /[?&]stijl=(retro|moestuin)\b/.exec(location.search);
  if (gevraagd) { bewaar(gevraagd[1]); }
  html.setAttribute("data-stijl", gevraagd ? gevraagd[1] : lees());

  var ICOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="1"/><line x1="8" y1="20" x2="16" y2="20"/><line x1="12" y1="16" x2="12" y2="20"/></svg>';

  function label() { return lees() === "retro" ? "Moestuin" : "Retro"; }

  document.addEventListener("DOMContentLoaded", function () {
    var onder = document.querySelector(".onderbalk");
    if (!onder) { return; }
    var knop = document.createElement("button");
    knop.type = "button";
    knop.className = "plat";
    knop.id = "knopStijl";
    knop.title = "Wissel tussen moestuin- en retro-stijl";
    knop.innerHTML = ICOON + "<span>" + label() + "</span>";
    knop.addEventListener("click", function () {
      var nieuw = lees() === "retro" ? "moestuin" : "retro";
      bewaar(nieuw);
      html.setAttribute("data-stijl", nieuw);
      knop.querySelector("span").textContent = label();
    });
    var uitlog = onder.querySelector("form");
    onder.insertBefore(knop, uitlog || null);
  });
})();
