# Demo van het dashboard met nepdata. Geen verbinding met Bitvavo, geen orders.
# Starten vanuit de projectmap: python demo/demo_app.py  ->  http://127.0.0.1:5134
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
    {"coin": "DOT", "icoon": "", "ingelegd": 0.0, "plafond": 150.0, "op_slot": False,
     "geoogst": 0.0, "dagrange": 6.2, "take_profit_pct": 11.0, "actief": True,
     "koers": 3.95, "waarde": 0.0, "budget": 100.0, "winst": -100.0, "netto_winst": -100.0,
     "rendement": -100.0, "doel_eur": 11.03, "netto_doel": 11.0, "voortgang": 0, "status": "MONITORING"},
]

# Totaal = alle euro's (250 vrij + 50 pot + 110 dalpot) + hoofdlijst 606,60
# + reserve 55,00 + pot belegd 195,18 + dalpot belegd 198,40.
portfolio = {
    "totaal": 1465.18,
    "cash": 250.00,
    "belegd": 606.60,
    "reserve": 55.00,
    "reserves": [
        {"munt": "BTC", "waarde": 40.00, "actief": False},
        {"munt": "ETH", "waarde": 15.00, "actief": True},
    ],
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
        reserve_keuzes=["BTC", "ETH"],
        reserve_actief="ETH",
        reserve_melding=None,
        verwerkt=request.args.get("verwerkt"),
    )


@app.route("/beheren/<path:pad>", methods=["POST"])
def beheren_actie(pad):
    print("ACTIE:", pad, dict(request.form))
    return redirect(url_for("beheren", verwerkt="1"))


HELP_INSTELLINGEN = {
    "demo": True, "fee_pct": 0.25, "min_winst": 5.5, "min_order": 5.0, "hoofd_doel": 11.0,
    "max_inleg": 1.5, "lagen": [4.0, 10.0, 18.0], "trailing_buy": 1.0, "wacht_op_bodem": True,
    "reserve_pct": 50.0, "reserve_actief": "ETH", "reserve_keuzes": ["BTC", "ETH"],
    "pot_max": 2, "pot_budget": 25.0, "pot_min_order": 25.0, "pot_doel": 5.5, "pot_trail": 1.0,
    "pot_cooldown": 6.0, "pot_per_dag": 25.0, "pot_noodstop": 25.0, "pot_min_volume": 1_000_000.0,
    "pot_atr_min": 3.0, "pot_atr_max": 25.0, "pot_uitgesloten": [],
    "dalpot_max": 3, "dalpot_budget": 100.0, "dalpot_doel": 10.0, "dalpot_trail": 1.0,
    "dalpot_noodstop": 25.0, "dalpot_herkoop": 24.0,
    "dalpot_uitgesloten": ["BTC", "DAI", "ETH", "EURC", "USDC", "USDT"],
    "login_pogingen": 5, "login_lockout_min": 15,
}


@app.route("/help")
def help_pagina():
    return render_template("help.html", h=HELP_INSTELLINGEN)


@app.route("/api/data")
def api_data():
    return jsonify({"tijd": "12:45:28", "bot_actief": True, "portfolio": portfolio, "posities": posities, "pot": pot, "dalpot": dalpot})


@app.route("/api/historie")
def api_historie():
    return jsonify({"bereik": "dag", "punten": []})


@app.route("/activiteit")
def activiteit_pagina():
    return render_template("activiteit.html")


@app.route("/api/trades")
def api_trades():
    trades = []
    bronnen = ["automatisch", "handmatig", "pot-automatisch", "dalpot-automatisch", "aanvullen", "reserve-btc"]
    munten = ["SOL", "LINK", "ADA", "PEPE", "AVAX", "BTC", "HBAR", "ETH", "BONK"]
    for i in range(35):
        trades.append({
            "tijd": f"2026-09-20T{10 + (i % 10):02d}:{(i * 7) % 60:02d}:00+00:00",
            "munt": munten[i % len(munten)],
            "kant": "verkoop" if i % 3 else "koop",
            "bedrag": round(5 + (i * 3.7) % 80, 2),
            "bron": bronnen[i % len(bronnen)],
        })
    return jsonify({"trades": trades})


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
        "reeks": [{"periode": "2026-09-27", "winst": 22.10, "aantal": 2}],
        "top_munten": [{"munt": "SOL", "winst": 33.00, "aantal": 3, "actief": True}],
        "aantal_munten": 1,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5134, debug=False)
