# Demo van het dashboard met nepdata. Geen verbinding met Bitvavo, geen orders.
# Starten vanuit de projectmap: python demo/demo_app.py  ->  http://127.0.0.1:5134
# (andere poort: python demo/demo_app.py 5144)
import os

from flask import Flask, render_template, jsonify, request, redirect, url_for, send_from_directory

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(PROJECT, "templates"),
    static_folder=os.path.join(PROJECT, "static"),
)


@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js")


@app.route("/login")
def login_voorbeeld():
    # Alleen om de inlogpagina te bekijken; de demo heeft geen wachtwoord.
    return render_template("login.html", fout=request.args.get("fout"), volgende=None)


@app.route("/logout", methods=["POST"])
def logout():
    return redirect(url_for("dashboard"))

# Alle bedragen hieronder zijn verzonnen voorbeeldwaarden.
hoofdlijst_munten = ["ADA", "DOT", "LINK", "SOL"]
pot_munten = ["AVAX", "HBAR"]
dalpot_munten = ["PEPE", "BONK"]

posities = [
    {"coin": "SOL", "icoon": "", "ingelegd": 250.0, "plafond": 375.0, "op_slot": False,
     "geoogst": 33.00, "dagrange": 5.1, "take_profit_pct": 4.4, "actief": True,
     "koers": 131.20, "waarde": 262.40, "budget": 250.0, "winst": 12.40, "netto_winst": 12.37,
     "rendement": 4.96, "doel_eur": 11.03, "netto_doel": 11.0, "voortgang": 100, "status": "PUMPING"},
    {"coin": "LINK", "icoon": "", "ingelegd": 150.0, "plafond": 225.0, "op_slot": False,
     "geoogst": 22.10, "dagrange": 5.6, "take_profit_pct": 7.33, "actief": True,
     "koers": 15.62, "waarde": 156.20, "budget": 150.0, "winst": 6.20, "netto_winst": 6.18,
     "rendement": 4.13, "doel_eur": 11.03, "netto_doel": 11.0, "voortgang": 56, "status": "MONITORING"},
    {"coin": "ADA", "icoon": "", "ingelegd": 200.0, "plafond": 300.0, "op_slot": False,
     "geoogst": 11.20, "dagrange": 4.8, "take_profit_pct": 5.5, "actief": True,
     "koers": 0.47, "waarde": 188.00, "budget": 200.0, "winst": -12.00, "netto_winst": -12.00,
     "rendement": -6.0, "doel_eur": 11.03, "netto_doel": 11.0, "voortgang": 0, "status": "MONITORING"},
    {"coin": "DOT", "icoon": "", "ingelegd": 100.0, "plafond": 150.0, "op_slot": False,
     "geoogst": 0.0, "dagrange": 6.2, "take_profit_pct": 11.0, "actief": True,
     "koers": 3.95, "waarde": 102.00, "budget": 100.0, "winst": 2.00, "netto_winst": 2.00,
     "rendement": 2.0, "doel_eur": 11.03, "netto_doel": 11.0, "voortgang": 18, "status": "MONITORING"},
]

# Totaal = alle euro's (250 vrij + 50 pot + 110 dalpot) + hoofdlijst 708,60
# + reserve 55,00 + pot belegd 195,18 + dalpot belegd 198,40.
portfolio = {
    "totaal": 1567.18,
    "cash": 250.00,
    "belegd": 708.60,
    "reserve": 55.00,
    "reserve_verdeling": {"BTC": 40.00, "ETH": 15.00, "BNB": 0.0, "SOL": 0.0, "XRP": 0.0},
    "reserve_actief": "ETH",
    "gerealiseerd": 66.30,
}

pot = {
    "cash": 50.00,
    "belegd": 195.18,
    "totaal": 245.18,
    "gestort": 250.0,
    "noodstop": False,
    "posities": [
        {"coin": "AVAX", "icoon": "", "koers": 9.26, "waarde": 96.52, "budget": 100.0,
         "ingelegd": 100.0, "geoogst": 7.42, "winst": -3.48, "rendement": -3.48,
         "doel_eur": 5.5, "voortgang": 0, "status": "MONITORING", "op_slot": False,
         "kan_kopen_om": None, "actief": True},
        {"coin": "HBAR", "icoon": "", "koers": 0.062, "waarde": 98.66, "budget": 100.0,
         "ingelegd": 98.66, "geoogst": 0.0, "winst": -1.34, "rendement": -1.34,
         "doel_eur": 5.5, "voortgang": 0, "status": "MONITORING", "op_slot": False,
         "kan_kopen_om": "14:30", "actief": True},
    ],
}

dalpot = {
    "cash": 110.0,
    "belegd": 198.40,
    "totaal": 308.40,
    "gestort": 310.0,
    "noodstop": False,
    "posities": [
        {"coin": "PEPE", "icoon": "", "koers": 0.0000034, "waarde": 102.30, "budget": 100.0,
         "ingelegd": 102.30, "geoogst": 0.0, "winst": 2.30, "rendement": 2.30,
         "doel_eur": 10.0, "voortgang": 23, "status": "MONITORING", "op_slot": False,
         "kan_kopen_om": None, "actief": True},
        {"coin": "BONK", "icoon": "", "koers": 0.0000091, "waarde": 96.10, "budget": 100.0,
         "ingelegd": 96.10, "geoogst": 0.0, "winst": -3.90, "rendement": -3.90,
         "doel_eur": 10.0, "voortgang": 0, "status": "MONITORING", "op_slot": False,
         "kan_kopen_om": None, "actief": True},
    ],
}


@app.route("/")
def dashboard():
    return render_template("index.html", portfolio=portfolio, posities=posities, pot=pot, dalpot=dalpot)


pot_instellingen = {"max_munten": 2, "budget_per_munt": 100.0, "winstdoel_eur": 5.50, "trailing_pct": 1.0}
dalpot_instellingen = {"max_munten": 3, "budget_per_munt": 100.0, "winstdoel_eur": 10.0, "trailing_pct": 1.0}


@app.route("/beheren")
def beheren():
    return render_template(
        "beheren.html",
        hoofdlijst_munten=hoofdlijst_munten,
        pot_munten=pot_munten,
        pot_instellingen=pot_instellingen,
        dalpot_munten=dalpot_munten,
        dalpot_instellingen=dalpot_instellingen,
        reserve_munt="ETH",
        reserve_munten=("BTC", "ETH", "BNB", "SOL", "XRP"),
        verwerkt=request.args.get("verwerkt"),
        fout=None,
    )


_demo_status = {"actief": True, "gestart": __import__("time").time() - 3 * 86400 - 14 * 3600}


_publiek = {"client": None}


@app.route("/api/munt-check")
def api_munt_check():
    """Demo: zoekt echt bij Bitvavo, maar alleen in openbare gegevens (geen sleutels, geen orders)."""
    q = (request.args.get("q") or "").strip()
    if not q or len(q) > 30:
        return jsonify({"fout": "Vul een muntcode of naam in, bijvoorbeeld BTC of Bitcoin."}), 400
    try:
        import ccxt
        if _publiek["client"] is None:
            c = ccxt.bitvavo({"enableRateLimit": True}); c.load_markets(); _publiek["client"] = c
        c = _publiek["client"]
        qo, ql = q.upper(), q.lower()
        def score(code, info):
            naam = str(info.get("name") or "").lower()
            if code == qo: return 0
            if naam == ql: return 1
            if code.startswith(qo) or naam.startswith(ql): return 2
            if ql in naam: return 3
            return None
        treffers = sorted((s2, code) for code, info in (c.currencies or {}).items() for s2 in [score(code, info)] if s2 is not None)[:6]
        tick = c.fetch_tickers([f"{code}/EUR" for _, code in treffers if f"{code}/EUR" in c.markets]) if treffers else {}
        demo_lijsten = {"hoofdlijst": [p["coin"] for p in posities], "reserve": list(portfolio["reserve_verdeling"])}
        uit = []
        for _, code in treffers:
            m = c.markets.get(f"{code}/EUR") or {}
            status = (m.get("info") or {}).get("status")
            t = tick.get(f"{code}/EUR") or {}
            uit.append({"code": code, "naam": c.currencies[code].get("name") or code,
                        "handelbaar": bool(m) and bool(m.get("active")) and status in (None, "trading"),
                        "markt": bool(m), "status": status, "koers": t.get("last"),
                        "verandering_24u": t.get("percentage"), "volume_24u_eur": t.get("quoteVolume"),
                        "min_order_eur": ((m.get("limits") or {}).get("cost") or {}).get("min"),
                        "in": [n for n, l in demo_lijsten.items() if code in l]})
        return jsonify({"vraag": q, "munten": uit})
    except Exception:
        return jsonify({"fout": "Bitvavo is nu niet bereikbaar. Probeer het zo nog eens."}), 502


@app.route("/api/status")
def api_status():
    import time
    nu = time.time()
    return jsonify({"bot_actief": _demo_status["actief"], "uptime_sec": int(nu - _demo_status["gestart"]),
                    "laatste_run": time.strftime("%H:%M:%S"), "laatste_run_sec_geleden": 1,
                    "pi_temp": 41.0, "demo": True})


@app.route("/beheren/pauzeer", methods=["POST"])
def beheren_pauzeer():
    _demo_status["actief"] = not _demo_status["actief"]
    terug = request.form.get("terug", "/")
    return redirect(terug if terug.startswith("/") and not terug.startswith("//") else "/")


# Afgeroomd-pagina: voorbeeld met een scheve verdeling, zodat er iets te herbalanceren is
_demo_afgeroomd = {
    "waarden": {"BTC": 250.0, "ETH": 300.0, "BNB": 20.0, "SOL": 0.0, "XRP": 0.0},
    "koersen": {"BTC": 62500.0, "ETH": 2300.0, "BNB": 540.0, "SOL": 150.0, "XRP": 0.52},
    "doelen": {"BTC": 50.0, "ETH": 30.0, "BNB": 10.0, "SOL": 5.0, "XRP": 5.0},
    "minimum": 25.0,
    "melding": None,
}


def _demo_plan(d):
    """Zelfde rekenregels als herbalanceer_plan in bot.py, op de nepdata."""
    munten = [m for m, p in d["doelen"].items() if p > 0]
    totaal = sum(d["waarden"][m] for m in munten)
    som = sum(d["doelen"][m] for m in munten)
    doel = {m: d["doelen"][m] / som * totaal for m in munten}
    laag = [m for m in munten if doel[m] < d["minimum"]]
    tekort = sum(d["minimum"] - doel[m] for m in laag)
    ruimte = sum(doel[m] - d["minimum"] for m in munten if m not in laag)
    for m in munten:
        if m in laag:
            doel[m] = d["minimum"]
        elif ruimte > 0:
            doel[m] -= tekort * (doel[m] - d["minimum"]) / ruimte
    drempel = max(6.0, totaal * 0.02)
    rijen, verkopen, kopen = [], [], []
    for m in munten:
        v = doel[m] - d["waarden"][m]
        actie = "verkopen" if -v >= drempel else ("kopen" if v >= drempel else "")
        rijen.append({"munt": m, "huidig": d["waarden"][m], "doel_eur": doel[m], "actie": actie, "bedrag": abs(v) if actie else 0.0})
        (verkopen if actie == "verkopen" else kopen if actie == "kopen" else []).append(abs(v))
    opbrengst = sum(verkopen) * 0.9975
    factor = min(1.0, opbrengst / sum(kopen)) if kopen else 0.0
    for r in rijen:
        if r["actie"] == "kopen":
            r["bedrag"] *= factor
    return {"totaal": totaal, "rijen": rijen, "drempel": drempel, "uitvoerbaar": bool(verkopen and kopen),
            "reden": "" if verkopen and kopen else "De reserve is in balans."}


@app.route("/afgeroomd")
def afgeroomd_pagina():
    d = _demo_afgeroomd
    totaal = sum(d["waarden"].values())
    som = sum(d["doelen"].values())
    gekocht = {"BTC": 236.0, "ETH": 281.5, "BNB": 20.6, "SOL": 0.0, "XRP": 0.0}
    munten = [{"munt": m, "waarde": w, "aantal": w / d["koersen"][m], "koers": d["koersen"][m],
               "pct": w / totaal * 100 if totaal else 0, "doel_pct": d["doelen"].get(m, 0.0), "icoon": "",
               "gekocht": gekocht[m], "verkocht": 0.0, "resultaat": w - gekocht[m],
               "resultaat_pct": (w - gekocht[m]) / gekocht[m] * 100 if gekocht[m] else 0.0}
              for m, w in d["waarden"].items()]
    volgende = max(d["doelen"], key=lambda m: d["doelen"][m] / som * totaal - d["waarden"][m])
    nu = int(__import__("time").time())
    dag = 86400
    grafiek = {
        "ingelegd": [[nu - 35 * dag + i * 3 * dag, round(45.0 * (i + 1), 2)] for i in range(12)],
        "waarde": [[nu - 35 * dag + i * dag, round(40 + i * 15.5 + (i % 5) * 6, 2)] for i in range(36)],
    }
    a = {"totaal": totaal, "munten": munten, "volgende": volgende, "minimum": d["minimum"],
         "melding_pp": 10.0, "max_munten": 10,
         "resultaat": totaal - sum(gekocht.values()), "netto_ingelegd": sum(gekocht.values()), "grafiek": grafiek,
         "doelen_ingesteld": True, "reserve_pct": 50.0, "plan": _demo_plan(d),
         "recent": [{"tijd": "2026-10-23T13:58:00+00:00", "munt": "ETH", "kant": "koop", "bedrag": 5.51, "bron": "reserve-eth"},
                    {"tijd": "2026-10-22T23:58:00+00:00", "munt": "BTC", "kant": "koop", "bedrag": 5.52, "bron": "reserve-btc"}]}
    melding, d["melding"] = d["melding"], None
    return render_template("afgeroomd.html", a=a, melding=melding)


@app.route("/afgeroomd/<pad>", methods=["POST"])
def afgeroomd_actie(pad):
    print("ACTIE afgeroomd:", pad, dict(request.form))
    _demo_afgeroomd["melding"] = {"ok": True, "tekst": "Demo: er is niets echt opgeslagen of verhandeld."}
    return redirect(url_for("afgeroomd_pagina"))


@app.route("/beheren/<path:pad>", methods=["POST"])
def beheren_actie(pad):
    print("ACTIE:", pad, dict(request.form))
    return redirect(url_for("beheren", verwerkt="1"))


HELP_INSTELLINGEN = {
    "demo": True, "fee_pct": 0.25, "min_winst": 5.5, "min_order": 5.0, "min_oogst": 10.5, "hoofd_doel": 11.0,
    "max_inleg": 1.5, "lagen": [4.0, 10.0, 18.0], "trailing_buy": 1.0, "wacht_op_bodem": True,
    "reserve_pct": 50.0, "reserve_actief": "ETH", "reserve_keuzes": ["BTC", "ETH", "BNB", "SOL", "XRP"],
    "pot_max": 2, "pot_budget": 25.0, "pot_min_order": 25.0, "pot_doel": 5.5, "pot_trail": 1.0,
    "pot_cooldown": 6.0, "pot_per_dag": 25.0, "pot_noodstop": 25.0, "pot_min_volume": 1_000_000.0,
    "pot_atr_min": 3.0, "pot_atr_max": 25.0, "pot_uitgesloten": [],
    "dalpot_max": 3, "dalpot_budget": 100.0, "dalpot_doel": 10.0, "dalpot_trail": 1.0,
    "dalpot_noodstop": 25.0, "dalpot_herkoop": 24.0,
    "dalpot_uitgesloten": ["BTC", "DAI", "ETH", "EURC", "USDC", "USDT"],
    "login_pogingen": 5, "login_lockout_min": 15,
    "donatie": {
        "BTC": "bc1q0sjsskrmmmtm9zj2vaeady8h37w280xxffve6n",
        "ETH": "0x798483b4749654Fa0C1bffb95F27d7C401955c24",
        "SOL": "6Qe6o5FMQUUMifxAdzE75SsekYsFX6Bgft3JGPdmGJRT",
    },
}


@app.route("/help")
def help_pagina():
    return render_template("help.html", h=HELP_INSTELLINGEN)


@app.route("/api/data")
def api_data():
    return jsonify({"tijd": "12:45:28", "bot_actief": True, "portfolio": portfolio, "posities": posities, "pot": pot, "dalpot": dalpot})


@app.route("/api/historie")
def api_historie():
    # Verzonnen, rustig stijgend verloop dat eindigt op de huidige totale waarde.
    import math
    import time
    bereik = request.args.get("bereik", "dag")
    dagen = {"dag": 1, "maand": 30, "kwartaal": 90, "alles": 120}.get(bereik, 1)
    aantal = 96
    nu = time.time()
    eind = portfolio["totaal"]
    punten = []
    for i in range(aantal + 1):
        f = i / aantal
        golf = math.sin(f * 9.0) * 6.0 + math.sin(f * 23.0) * 2.5
        waarde = eind - (1 - f) * 18.0 * dagen ** 0.5 + golf * (1 - f * 0.6)
        punten.append({"t": nu - (1 - f) * dagen * 86400, "totaal": round(waarde, 2),
                       "cash": portfolio["cash"], "belegd": portfolio["belegd"]})
    punten[-1]["totaal"] = eind
    return jsonify({"bereik": bereik, "punten": punten})


@app.route("/activiteit")
def activiteit_pagina():
    return render_template("activiteit.html")


@app.route("/api/trades")
def api_trades():
    # Verzonnen orders van de afgelopen dagen, nieuwste eerst. Ook gebruikt voor
    # de koop/verkoop-stippen in de grafiek.
    from datetime import datetime, timedelta, timezone
    nu = datetime.now(timezone.utc)
    voorbeelden = [
        (2.0, "SOL", "verkoop", 11.03, "automatisch"),
        (2.0, "ETH", "koop", 5.51, "reserve-eth"),
        (7.5, "HBAR", "koop", 25.00, "pot-automatisch"),
        (11.0, "PEPE", "koop", 100.00, "dalpot-automatisch"),
        (11.0, "BONK", "koop", 100.00, "dalpot-automatisch"),
        (16.0, "LINK", "verkoop", 11.05, "automatisch"),
        (16.0, "BTC", "koop", 5.52, "reserve-btc"),
        (21.0, "DOT", "koop", 100.25, "aanvullen"),
        (30.0, "AVAX", "verkoop", 105.42, "pot-automatisch"),
        (40.0, "SOL", "verkoop", 11.10, "handmatig"),
        (40.0, "BTC", "koop", 5.55, "reserve-btc"),
        (55.0, "ADA", "koop", 50.13, "aanvullen"),
    ]
    trades = [{
        "tijd": (nu - timedelta(hours=uur)).isoformat(timespec="seconds"),
        "munt": munt, "kant": kant, "bedrag": bedrag,
        "fee": round(bedrag * 0.0025, 4), "bron": bron,
    } for uur, munt, kant, bedrag, bron in voorbeelden]
    return jsonify({"trades": trades})


# Verzonnen meldingen voor het belletje in het menu.
import time as _tijd
_meld = {"gelezen_tot": 0}
_nu = int(_tijd.time())
_meld_items = [
    {"t": _nu - 3600 * 16, "tekst": "💰 WINST AFGEROOMD: LINK\n• Netto na fee: € 11,02\n• Naar BTC omgezet: € 5,51", "niveau": "info"},
    {"t": _nu - 3600 * 11, "tekst": "📉 Dalpot kocht PEPE en BONK voor € 100,00 per munt", "niveau": "info"},
    {"t": _nu - 3600 * 5, "tekst": "⚠️ De aankoop van HBAR/EUR is maar gedeeltelijk gelukt (€ 24,10 van € 25,00).", "niveau": "belangrijk"},
    {"t": _nu - 3600 * 2, "tekst": "💰 WINST AFGEROOMD: SOL\n• Netto na fee: € 11,00\n• Naar ETH omgezet: € 5,50", "niveau": "info"},
]


@app.route("/api/meldingen")
def api_meldingen():
    ongelezen = sum(1 for m in _meld_items if m["niveau"] == "belangrijk" and m["t"] > _meld["gelezen_tot"])
    return jsonify({"meldingen": list(reversed(_meld_items)), "ongelezen_belangrijk": ongelezen,
                    "gelezen_tot": _meld["gelezen_tot"]})


@app.route("/api/meldingen/gelezen", methods=["POST"])
def api_meldingen_gelezen():
    _meld["gelezen_tot"] = int(_tijd.time())
    return jsonify({"ok": True})


@app.route("/rendement")
def rendement_pagina():
    return render_template("rendement.html")


@app.route("/potten")
def potten_pagina():
    return render_template("potten.html")


@app.route("/api/rendement")
def api_rendement():
    return jsonify({
        "bereik": request.args.get("bereik", "week"),
        "totaal_winst": 66.30, "aantal_oogsten": 6, "gemiddelde": 11.05,
        "totaal_fees": 0.17, "naar_btc": 33.15,
        "reeks": [
            {"periode": "2026-09-21", "winst": 11.02, "aantal": 1},
            {"periode": "2026-09-22", "winst": 0.0, "aantal": 0},
            {"periode": "2026-09-23", "winst": 11.10, "aantal": 1},
            {"periode": "2026-09-24", "winst": 11.05, "aantal": 1},
            {"periode": "2026-09-25", "winst": 0.0, "aantal": 0},
            {"periode": "2026-09-26", "winst": 11.03, "aantal": 1},
            {"periode": "2026-09-27", "winst": 22.10, "aantal": 2},
        ],
        "top_munten": [
            {"munt": "SOL", "winst": 33.00, "aantal": 3, "actief": True},
            {"munt": "LINK", "winst": 22.10, "aantal": 2, "actief": True},
            {"munt": "ADA", "winst": 11.20, "aantal": 1, "actief": True},
        ],
        "aantal_munten": 3,
    })


if __name__ == "__main__":
    # Poort: als argument, via PORT, of standaard 5134.
    import sys
    poort = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "5134"))
    app.run(host="127.0.0.1", port=poort, debug=False)
