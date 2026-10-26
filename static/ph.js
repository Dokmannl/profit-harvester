/* Profit Harvester: gedeelde opbouw van zijbalk, status en pauzeknop.
   Raakt geen bestaande ID's of formulieren van de pagina; voegt alleen dingen toe. */
(function () {
  "use strict";

  var LOGO = '<svg viewBox="0 0 48 48" aria-hidden="true"><rect x="9" y="27" width="7.5" height="12" rx="2" fill="#0B0E13"/>' +
    '<rect x="20.25" y="21" width="7.5" height="18" rx="2" fill="#0B0E13"/><rect x="31.5" y="17" width="7.5" height="22" rx="2" fill="#0B0E13"/>' +
    '<path d="M35.25 15C35.25 10 38.5 7 43 7c0 4.5-3.25 8-7.75 8z" fill="#0B0E13"/></svg>';

  var IC = {
    ververs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><polyline points="20 4 20 11 13 11"/></svg>',
    help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.7"/><circle cx="12" cy="16.9" r=".6" fill="currentColor"/></svg>',
    uit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><polyline points="10 16 14 12 10 8"/><line x1="14" y1="12" x2="4" y2="12"/></svg>',
    maan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>',
    pauze: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6.5" y="5" width="3.6" height="14" rx="1"/><rect x="13.9" y="5" width="3.6" height="14" rx="1"/></svg>',
    start: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.9l10.4-6.5a1 1 0 0 0 0-1.8L9.5 4.6A1 1 0 0 0 8 5.5z"/></svg>'
  };

  var DAGEN = ["zo", "ma", "di", "wo", "do", "vr", "za"];
  var MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];

  function maak(tag, klasse, html) {
    var e = document.createElement(tag);
    if (klasse) { e.className = klasse; }
    if (html !== undefined) { e.innerHTML = html; }
    return e;
  }

  // ---------- zijbalk: logo en "Menu"-kopje ----------
  var nav = document.querySelector(".navbalk");
  if (nav) {
    var merk = maak("div", "ph-zijmerk",
      '<span class="ph-merkje">' + LOGO + '</span><span><b>Profit Harvester</b><small>v6.0 · Bitvavo' +
      (document.body.dataset.demo === "1" ? " · DEMO" : "") + '</small></span>');
    nav.insertBefore(maak("span", "ph-zijlabel", "Menu"), nav.firstChild);
    nav.insertBefore(merk, nav.firstChild);
  }

  // ---------- kop: logo (telefoon) en datum als ondertitel ----------
  var kop = document.querySelector(".kop");
  if (kop && !kop.querySelector(".ph-merkje")) {
    var nu = new Date();
    var datum = DAGEN[nu.getDay()] + " " + nu.getDate() + " " + MAANDEN[nu.getMonth()];
    var sub = kop.querySelector(".ph-sub");
    if (sub && sub.dataset.datum === "1") {
      sub.textContent = datum + (sub.textContent ? " · " + sub.textContent : "");
    }
    var eerste = kop.firstElementChild;
    if (eerste) {
      var blok = maak("div", "ph-kopblok");
      kop.insertBefore(blok, eerste);
      var merkje = maak("a", "ph-merkje ph-kopmerk", LOGO);
      merkje.href = "/";
      merkje.setAttribute("aria-label", "Dashboard");
      blok.appendChild(merkje);
      blok.appendChild(eerste);
    }
  }

  // ---------- onderbalk: icoontjes bij Ververs / Licht / Help / Uitloggen ----------
  var onder = document.querySelector(".onderbalk");
  if (onder) {
    var vv = document.getElementById("knopVernieuw") || onder.querySelector("button.plat");
    if (vv) { vv.insertAdjacentHTML("afterbegin", IC.ververs); }
    var th = document.getElementById("knopThema");
    if (th) {
      // de pagina zet zelf de tekst (Licht/Donker); wij zetten er een icoon voor zonder die tekst te wissen
      var tekst = maak("span", "ph-themalabel", th.textContent);
      th.textContent = "";
      th.insertAdjacentHTML("afterbegin", IC.maan);
      th.appendChild(tekst);
      new MutationObserver(function () {
        if (!th.querySelector(".ph-themalabel")) {
          var t = th.textContent; th.textContent = "";
          th.insertAdjacentHTML("afterbegin", IC.maan);
          th.appendChild(maak("span", "ph-themalabel", t));
        }
      }).observe(th, { childList: true });
    }
    var hl = onder.querySelector('a[href="/help"]');
    if (hl) {
      hl.insertAdjacentHTML("afterbegin", IC.help);
      if (location.pathname === "/help") { hl.classList.add("actief"); }
    }
    var ul = onder.querySelector('#uitlogFormulier button');
    if (ul) { ul.insertAdjacentHTML("afterbegin", IC.uit); }
  }

  // ---------- status: bot actief, uptime, laatste ronde, Pi-temperatuur, pauzeren ----------
  function uptime(sec) {
    var d = Math.floor(sec / 86400), u = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
    if (d) { return d + "d " + u + "u"; }
    if (u) { return u + "u " + m + "m"; }
    return m + "m";
  }

  function pauzeFormulier(actief, klasse) {
    var f = maak("form");
    f.method = "post";
    f.action = "/beheren/pauzeer";
    f.innerHTML = '<input type="hidden" name="terug" value="' + location.pathname + '">' +
      '<button type="submit" class="ph-pauze ' + (actief ? "" : "hervat ") + (klasse || "") + '">' +
      (actief ? IC.pauze + "Bot pauzeren" : IC.start + "Bot hervatten") + '</button>';
    f.addEventListener("submit", function (e) {
      if (f.dataset.bevestigd === "1") { return; }
      e.preventDefault();
      vraagBevestiging(
        actief ? "Bot pauzeren?" : "Bot weer aanzetten?",
        actief
          ? "De bot koopt en verkoopt dan niets meer, ook geen winst afromen, tot je hem weer aanzet. Na een herstart staat hij vanzelf weer aan."
          : "Kopen en verkopen gaan dan weer gewoon door.",
        actief ? "Pauzeren" : "Hervatten",
        function () { f.dataset.bevestigd = "1"; f.submit(); }
      );
    });
    return f;
  }

  // eigen bevestigvenster (zelfde uiterlijk als op Beheren), met Escape en klik ernaast om te annuleren
  function vraagBevestiging(titel, tekst, knop, ok) {
    var laag = maak("div", "ph-overlay");
    laag.innerHTML = '<div class="ph-modaal" role="dialog" aria-modal="true" aria-labelledby="phModTitel">' +
      '<h3 id="phModTitel"></h3><p></p><div class="ph-knoppen">' +
      '<button type="button" class="plat ph-nee">Annuleren</button><button type="button" class="hoofd ph-ja"></button></div></div>';
    laag.querySelector("h3").textContent = titel;
    laag.querySelector("p").textContent = tekst;
    laag.querySelector(".ph-ja").textContent = knop;
    function weg() { laag.remove(); document.removeEventListener("keydown", toets); }
    function toets(e) { if (e.key === "Escape") { weg(); } }
    laag.addEventListener("click", function (e) { if (e.target === laag) { weg(); } });
    laag.querySelector(".ph-nee").addEventListener("click", weg);
    laag.querySelector(".ph-ja").addEventListener("click", function () { weg(); ok(); });
    document.addEventListener("keydown", toets);
    document.body.appendChild(laag);
    laag.querySelector(".ph-ja").focus();
  }

  var zij = null, balk = null, pauzebalk = null;
  if (nav) {
    zij = maak("div", "ph-zijstatus");
    zij.hidden = true;
    document.body.appendChild(zij);
  }
  var plek = document.getElementById("phStatusPlek");
  if (plek) {
    balk = maak("div", "ph-statusbalk");
    balk.hidden = true;
    plek.appendChild(balk);
  }

  var vorigeActief = null;

  function tekenStatus(s) {
    var actief = !!s.bot_actief;
    var stipKlasse = actief ? "" : " uit";
    var naam = actief ? "Bot actief" : "Gepauzeerd";
    var run = s.laatste_run || "–";
    var temp = (s.pi_temp === null || s.pi_temp === undefined) ? "–" : String(s.pi_temp).replace(".", ",") + " °C";

    if (zij) {
      zij.hidden = false;
      zij.innerHTML =
        '<div class="ph-stat-kop"><div><i class="ph-stip' + stipKlasse + '"></i>' + naam + '</div><span>' + uptime(s.uptime_sec || 0) + '</span></div>' +
        '<div class="ph-stat-rij"><div><small>Laatste run</small><b>' + run + '</b></div><div><small>Pi CPU</small><b>' + temp + '</b></div></div>';
      zij.appendChild(pauzeFormulier(actief));
    }
    if (balk) {
      balk.hidden = false;
      balk.innerHTML =
        '<div><div class="ph-stat-kop"><i class="ph-stip' + stipKlasse + '"></i>' + naam + ' · ' + uptime(s.uptime_sec || 0) + '</div>' +
        '<small>run ' + run + ' · Pi ' + temp + '</small></div>';
      balk.appendChild(pauzeFormulier(actief));
    }

    // gepauzeerd: op elke pagina een duidelijke melding bovenaan
    if (!actief && !pauzebalk) {
      var wrap = document.querySelector(".wrap") || document.body;
      pauzebalk = maak("div", "ph-pauzebalk", IC.pauze.replace("<svg", '<svg width="14" height="14"') +
        "De bot is gepauzeerd: er wordt niets gekocht of verkocht.");
      var na = wrap.querySelector(".kop");
      if (na && na.nextSibling) { wrap.insertBefore(pauzebalk, na.nextSibling); } else { wrap.insertBefore(pauzebalk, wrap.firstChild); }
    } else if (actief && pauzebalk) {
      pauzebalk.remove(); pauzebalk = null;
    }
    vorigeActief = actief;
  }

  function haalStatus() {
    fetch("/api/status", { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
      .then(tekenStatus)
      .catch(function () {
        if (zij && !zij.hidden) {
          var k = zij.querySelector(".ph-stip");
          if (k) { k.className = "ph-stip fout"; }
        }
      });
  }

  if (zij || balk) {
    haalStatus();
    setInterval(function () { if (!document.hidden) { haalStatus(); } }, 15000);
  }

  // ---------- munt opzoeken: staat hij op Bitvavo en is hij te verhandelen? ----------
  var ZOEK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="6.5"/><line x1="16" y1="16" x2="20.5" y2="20.5"/></svg>';
  var geldFmt = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
  function koersTekst(k) {
    if (k === null || k === undefined) { return "–"; }
    if (k >= 1) { return geldFmt.format(k); }
    return "€ " + Number(k).toLocaleString("nl-NL", { maximumSignificantDigits: 4 });
  }
  function volumeTekst(v) {
    if (!v) { return "–"; }
    if (v >= 1e6) { return "€ " + (v / 1e6).toLocaleString("nl-NL", { maximumFractionDigits: 1 }) + " mln"; }
    if (v >= 1e3) { return "€ " + Math.round(v / 1e3).toLocaleString("nl-NL") + "k"; }
    return geldFmt.format(v);
  }

  function openZoeken() {
    var laag = maak("div", "ph-overlay");
    laag.innerHTML = '<div class="ph-modaal ph-zoekmodaal" role="dialog" aria-modal="true" aria-labelledby="phZoekTitel">' +
      '<h3 id="phZoekTitel">Munt opzoeken</h3>' +
      '<p>Typ een afkorting of naam, bijvoorbeeld <b>BTC</b> of <b>Bitcoin</b>. Je ziet of hij op Bitvavo in euro’s te verhandelen is.</p>' +
      '<form class="ph-zoekform"><label class="ph-verborgen" for="phZoekVeld">Munt</label>' +
      '<input id="phZoekVeld" type="search" maxlength="30" autocomplete="off" spellcheck="false" placeholder="BTC of Bitcoin">' +
      '<button type="submit" class="hoofd">Zoek</button></form>' +
      '<div class="ph-zoekuitslag" aria-live="polite"></div>' +
      '<div class="ph-knoppen"><button type="button" class="plat ph-nee">Sluiten</button></div></div>';
    var veld = laag.querySelector("#phZoekVeld"), uitslag = laag.querySelector(".ph-zoekuitslag");
    function weg() { laag.remove(); document.removeEventListener("keydown", toets); }
    function toets(e) { if (e.key === "Escape") { weg(); } }
    laag.addEventListener("click", function (e) { if (e.target === laag) { weg(); } });
    laag.querySelector(".ph-nee").addEventListener("click", weg);
    document.addEventListener("keydown", toets);

    function melding(tekst) { uitslag.textContent = ""; uitslag.appendChild(maak("p", "ph-zoekleeg")).textContent = tekst; }
    laag.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var q = veld.value.trim();
      if (!q) { veld.focus(); return; }
      melding("Even kijken bij Bitvavo…");
      fetch("/api/munt-check?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) { melding(res.d.fout || "Dat lukte niet."); return; }
          var lijst = res.d.munten || [];
          if (!lijst.length) { melding("“" + q + "” staat niet op Bitvavo."); return; }
          uitslag.textContent = "";
          lijst.forEach(function (m) {
            var kaart = maak("div", "ph-zoekkaart" + (m.handelbaar ? " ja" : " nee"));
            var kop = maak("div", "ph-zoekkop");
            var naam = maak("div", "ph-zoeknaam");
            naam.appendChild(maak("b")).textContent = m.code;
            naam.appendChild(maak("span")).textContent = m.naam;
            kop.appendChild(naam);
            var label = maak("span", "ph-badge " + (m.handelbaar ? "ph-badge--onder" : "ph-badge--budget"));
            label.textContent = m.handelbaar ? "Te verhandelen" : (m.markt ? "Nu niet te verhandelen" : "Geen euromarkt");
            kop.appendChild(label);
            kaart.appendChild(kop);
            if (m.markt) {
              var cijfers = maak("div", "ph-zoekcijfers");
              var pct = m.verandering_24u;
              [["Koers", koersTekst(m.koers)],
               ["24 uur", pct === null || pct === undefined ? "–" : (pct >= 0 ? "+" : "−") + Math.abs(pct).toLocaleString("nl-NL", { maximumFractionDigits: 1 }) + "%"],
               ["Volume 24 uur", volumeTekst(m.volume_24u_eur)]].forEach(function (c) {
                var vak = maak("div");
                vak.appendChild(maak("small")).textContent = c[0];
                vak.appendChild(maak("b")).textContent = c[1];
                cijfers.appendChild(vak);
              });
              kaart.appendChild(cijfers);
            }
            var extra = [];
            if (m.in && m.in.length) { extra.push("Staat al in je " + m.in.join(" en ") + "."); }
            if (m.markt && !m.handelbaar && m.status) { extra.push("Status bij Bitvavo: " + m.status + "."); }
            if (!m.markt) { extra.push("Deze munt staat wel op Bitvavo, maar je kunt hem niet tegen euro’s kopen of verkopen."); }
            if (extra.length) { kaart.appendChild(maak("p", "ph-zoeknoot")).textContent = extra.join(" "); }
            uitslag.appendChild(kaart);
          });
        })
        .catch(function () { melding("Bitvavo is nu niet bereikbaar. Probeer het zo nog eens."); });
    });
    document.body.appendChild(laag);
    veld.focus();
  }

  // knop in het menu (computer, onder Meldingen) en in de kop (telefoon)
  if (nav) {
    var zk = maak("button", "navknop ph-zoeknav", ZOEK + "Munt opzoeken");
    zk.type = "button";
    zk.addEventListener("click", openZoeken);
    nav.appendChild(zk);
  }
  var kopRechts = document.querySelector(".kop");
  if (kopRechts) {
    var zt = maak("button", "ph-zoekknop", ZOEK);
    zt.type = "button";
    zt.setAttribute("aria-label", "Munt opzoeken op Bitvavo");
    zt.title = "Munt opzoeken op Bitvavo";
    zt.addEventListener("click", openZoeken);
    kopRechts.appendChild(zt);
  }
})();
