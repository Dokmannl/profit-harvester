/* Het speelveld "de kas": speelt verzonnen koersen af met de oogstregels van de bot
   voor de hoofdlijst. Gedeeld door de hoofdsite en de pagina proef/. */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var svg = document.getElementById("grafiek");
  var budgetVeld = document.getElementById("budget"), budgetUit = document.getElementById("budgetUit");
  var knop = document.getElementById("speel"), verloop = document.getElementById("verloop");
  var uGeoogst = document.getElementById("uGeoogst"), uReserve = document.getElementById("uReserve"), uWaarde = document.getElementById("uWaarde");
  var rustig = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var geld = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
  var geld2 = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });

  // Vaste, verzonnen koersverlopen: elke keer hetzelfde, zodat je soorten eerlijk kunt vergelijken.
  var SOORTEN = {
    rustig: { zaad: 2, trend: 0.0004, schok: 0.008 },
    wild:   { zaad: 3, trend: 0.00002, schok: 0.02 },
    daalt:  { zaad: 2, trend: -0.0013, schok: 0.009 }
  };
  var DAGEN = 360;          // vier koersen per dag, drie maanden

  function willekeur(zaad) {          // mulberry32
    return function () {
      zaad |= 0; zaad = zaad + 0x6D2B79F5 | 0;
      var t = Math.imul(zaad ^ zaad >>> 15, 1 | zaad);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function koersen(soort) {
    var s = SOORTEN[soort], r = willekeur(s.zaad), p = 1, uit = [1];
    for (var d = 1; d <= DAGEN; d++) {
      var normaal = (r() + r() + r() + r() - 2) * 1.2;   // ongeveer normaal verdeeld
      p *= Math.exp(s.trend + s.schok * normaal);
      uit.push(p);
    }
    return uit;
  }

  // Zelfde regels als de bot voor de hoofdlijst: doel gehaald, top volgen,
  // 1% terugval of winst terug tot 95% van het doel: alleen de winst verkopen.
  function speelAf(soort, budget) {
    var k = koersen(soort);
    var doel = Math.max(5.5, budget * 0.044), vangnet = doel * 0.955;
    var aantal = budget / k[0], volgt = false, top = 0;
    var geoogst = 0, punten = [], oogsten = [], volgDagen = [];
    for (var d = 0; d <= DAGEN; d++) {
      var waarde = aantal * k[d], winst = waarde - budget;
      if (!volgt && winst >= doel) { volgt = true; top = waarde; }
      if (volgt) {
        volgDagen.push(d);
        top = Math.max(top, waarde);
        if (waarde <= top * 0.99 || winst <= vangnet) {
          if (winst > 0) {
            aantal -= winst / k[d];
            geoogst += winst;
            oogsten.push({ dag: d, bedrag: winst, waarde: waarde });
            waarde = budget;
          }
          volgt = false;
        }
      }
      punten.push(waarde);
    }
    return { punten: punten, oogsten: oogsten, geoogst: geoogst, doel: doel, volgDagen: volgDagen };
  }

  // ---------- tekenen ----------
  var B = { l: 58, r: 20, t: 20, o: 34, w: 720, h: 330 };
  function el(naam, attrs, ouder) {
    var e = document.createElementNS(NS, naam);
    for (var k in attrs) { e.setAttribute(k, attrs[k]); }
    (ouder || svg).appendChild(e);
    return e;
  }
  var schaal;
  function assen(budget, uitkomst) {
    // smal scherm: smallere, hogere tekening, zodat lijn en letters leesbaar blijven
    var smal = svg.clientWidth < 600;
    B.w = smal ? 420 : 720; B.h = smal ? 340 : 330; B.l = smal ? 50 : 58;
    svg.setAttribute("viewBox", "0 0 " + B.w + " " + B.h);
    while (svg.lastChild && svg.lastChild.nodeName !== "title") { svg.removeChild(svg.lastChild); }
    var hoogste = Math.max(budget + uitkomst.doel * 2.2, Math.max.apply(null, uitkomst.punten) * 1.04);
    var laagste = Math.min(budget * 0.82, Math.min.apply(null, uitkomst.punten) * 0.96);
    schaal = {
      x: function (d) { return B.l + (d / DAGEN) * (B.w - B.l - B.r); },
      y: function (v) { return B.t + (1 - (v - laagste) / (hoogste - laagste)) * (B.h - B.t - B.o); }
    };
    [0, 120, 240, 360].forEach(function (d) {
      el("line", { x1: schaal.x(d), x2: schaal.x(d), y1: B.t, y2: B.h - B.o, class: "rooster", "stroke-width": 1 });
      el("text", { x: schaal.x(d), y: B.h - 12, class: "label", "text-anchor": d === 0 ? "start" : d === DAGEN ? "end" : "middle" }).textContent =
        d === 0 ? "start" : (d / 120) + (B.w < 600 ? " mnd" : d === 120 ? " maand" : " maanden");
    });
    var yb = schaal.y(budget), yd = schaal.y(budget + uitkomst.doel);
    el("line", { x1: B.l, x2: B.w - B.r, y1: yb, y2: yb, class: "budgetlijn", "stroke-width": 2 });
    el("text", { x: B.l - 8, y: yb + 4, class: "label-glas", "text-anchor": "end" }).textContent = geld.format(budget);
    el("line", { x1: B.l, x2: B.w - B.r, y1: yd, y2: yd, class: "doellijn", "stroke-width": 1.5, "stroke-dasharray": "6 6" });
    el("text", { x: B.w - B.r, y: yd - 8, class: "label-zaad", "text-anchor": "end" }).textContent = "oogstdoel +" + geld.format(uitkomst.doel);
  }

  var bezig = null;
  function start() {
    if (bezig) { cancelAnimationFrame(bezig); bezig = null; }
    var soort = document.querySelector('input[name="soort"]:checked').value;
    var budget = Number(budgetVeld.value);
    var u = speelAf(soort, budget);
    assen(budget, u);
    var lijn = el("polyline", { class: "waarde", fill: "none", "stroke-width": 3, "stroke-linejoin": "round", "stroke-linecap": "round", points: "" });
    var oogstLaag = el("g", { class: "oogst" });
    var pts = [], getoond = 0, geoogst = 0;
    knop.textContent = "Opnieuw afspelen";
    verloop.innerHTML = "De munt groeit…";

    function stap(tot) {
      while (getoond <= tot) {
        var d = getoond, v = u.punten[d];
        pts.push(schaal.x(d).toFixed(1) + "," + schaal.y(v).toFixed(1));
        u.oogsten.forEach(function (o) {
          if (o.dag === d) {
            // de top vóór de verkoop, dan de val terug naar het budget
            pts.splice(pts.length - 1, 1, schaal.x(d).toFixed(1) + "," + schaal.y(o.waarde).toFixed(1), schaal.x(d).toFixed(1) + "," + schaal.y(v).toFixed(1));
            el("circle", { cx: schaal.x(d), cy: schaal.y(o.waarde), r: 6 }, oogstLaag);
            // twee oogsten vlak na elkaar: eerste bedrag links, tweede rechts van de stip
            var i = u.oogsten.indexOf(o), x = schaal.x(d), y = schaal.y(o.waarde);
            var buurVoor = i > 0 && x - schaal.x(u.oogsten[i - 1].dag) < 48;
            var buurNa = i < u.oogsten.length - 1 && schaal.x(u.oogsten[i + 1].dag) - x < 48;
            el("text", buurVoor ? { x: x + 11, y: y + 4, "text-anchor": "start" }
              : buurNa ? { x: x - 11, y: y + 4, "text-anchor": "end" }
              : { x: x, y: y - 12, "text-anchor": "middle" }, oogstLaag).textContent = "+" + geld.format(o.bedrag);
            geoogst += o.bedrag;
          }
        });
        getoond++;
      }
      lijn.setAttribute("points", pts.join(" "));
      var nu = u.punten[Math.min(tot, DAGEN)];
      uGeoogst.textContent = geld.format(geoogst);
      uReserve.textContent = geld.format(geoogst / 2);
      uWaarde.textContent = geld.format(nu);
      uWaarde.classList.toggle("onder", nu < budget);
    }

    function klaar() {
      var eind = u.punten[DAGEN];
      if (u.oogsten.length) {
        verloop.innerHTML = "In drie maanden oogstte de bot <strong>" + u.oogsten.length + " keer</strong>, samen <strong>" +
          geld2.format(u.geoogst) + "</strong>. De helft ging naar je reserve. " +
          (eind >= budget ? "Je budget van " + geld.format(budget) + " staat er nog in." :
            "Aan het eind zakte de munt onder je budget; de bot wacht nu tot hij herstelt.");
      } else {
        verloop.innerHTML = "De munt kwam nooit boven het oogstdoel, dus de bot verkocht <strong>niets</strong>. " +
          "Je munt is nu " + geld.format(eind) + " waard. Zonder stop-loss wacht hij gewoon tot de munt herstelt.";
      }
    }

    if (rustig) { stap(DAGEN); klaar(); return; }
    var begin = null, duur = 4200;
    function frame(t) {
      if (begin === null) { begin = t; }
      var dag = Math.min(DAGEN, Math.floor(((t - begin) / duur) * DAGEN));
      stap(dag);
      if (dag < DAGEN) { bezig = requestAnimationFrame(frame); } else { bezig = null; klaar(); }
    }
    bezig = requestAnimationFrame(frame);
  }

  budgetVeld.addEventListener("input", function () { budgetUit.textContent = geld.format(Number(budgetVeld.value)); });
  knop.addEventListener("click", start);
  document.querySelectorAll('input[name="soort"]').forEach(function (r) { r.addEventListener("change", start); });

  // beginbeeld: lege kas met budget en doel, of meteen afspelen met #rustig, #wild of #daalt
  var gevraagd = location.hash.slice(1);
  if (SOORTEN[gevraagd]) { document.getElementById("s-" + gevraagd).checked = true; start(); }
  else { assen(250, speelAf("rustig", 250)); }
  window.addEventListener("hashchange", function () {
    var h = location.hash.slice(1);
    if (SOORTEN[h]) { document.getElementById("s-" + h).checked = true; start(); }
  });
})();
