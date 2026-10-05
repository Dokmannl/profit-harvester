# -*- coding: utf-8 -*-
"""
Profit Harvester V5.7
Gepatchte versie van V5.5 Pro.

Belangrijkste wijzigingen ten opzichte van V5.5:
  1. Eén globale lock rond alle orders, config-schrijfacties en database-schrijfacties.
  2. Verkooporders worden afgerond op de precisie van de markt en gecontroleerd
     tegen de minimum order-eisen van Bitvavo.
  3. Handelskosten worden meegerekend bij afromen en bij aanvullen.
  4. Menuknoppen worden altijd eerst herkend, ook wanneer de bot in een invoermodus staat.
  5. Balans en tickers worden gecached, zodat de rate limit niet wordt overschreden.
  6. Telegram draait in een eigen thread met long polling.
  7. Het webdashboard luistert standaard alleen lokaal en de API-routes vragen om een token.
  8. Fouten worden gelogd in plaats van stil weggeslikt.
"""

import os
import time
import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps

import ccxt
import requests
import json
import smtplib
from email.message import EmailMessage
from tinydb import TinyDB, Query
from tinydb.storages import Storage
from dotenv import load_dotenv
import secrets
import hashlib
import uuid
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

load_dotenv()

# ---------------------------------------------------------------------------
# Configuratie uit omgeving
# ---------------------------------------------------------------------------

BITVAVO_KEY = os.getenv("BITVAVO_API_KEY")
BITVAVO_SECRET = os.getenv("BITVAVO_API_SECRET")
BITVAVO_OPERATOR_ID = os.getenv("BITVAVO_OPERATOR_ID", "1234567890")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
EMAIL_SMTP_POORT = int(os.getenv("EMAIL_SMTP_POORT", "587"))

# Token waarmee de POST-routes van het dashboard worden beschermd.
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
# Standaard alleen lokaal bereikbaar. Zet bewust op 0.0.0.0 als je van buiten wil.
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5000"))
# Alleen aanzetten als het dashboard achter een proxy draait (Tailscale Funnel,
# nginx, Caddy). Dan komt het echte IP van de bezoeker uit X-Forwarded-For.
VERTROUW_PROXY = os.getenv("VERTROUW_PROXY", "0") == "1"
# Sessiecookie alleen via https versturen. Zet op 0 als je het dashboard via
# gewone http op je thuisnetwerk gebruikt, anders werkt inloggen niet.
DASHBOARD_ALLEEN_HTTPS = os.getenv("DASHBOARD_ALLEEN_HTTPS", "1") == "1"

# Demo-modus: echte koersen van Bitvavo, maar een nep-saldo en gesimuleerde
# orders. Geen API-key nodig. Zie DemoExchange.
DEMO_MODUS = os.getenv("DEMO_MODUS", "0") == "1"
DEMO_STARTKAPITAAL = float(os.getenv("DEMO_STARTKAPITAAL", "1000"))
# In demo-modus eigen databestanden, zodat demo en echt nooit mengen.
DATA_PREFIX = "demo_" if DEMO_MODUS else ""

CONFIG_FILE = DATA_PREFIX + "bot_live_config.json"
DB_FILE = DATA_PREFIX + "bot_trades_db.json"

MIN_WINST_EUR = 5.50          # minimale netto winst per afroming
MIN_ORDER_EUR = 5.00          # Bitvavo weigert orders onder ongeveer dit bedrag
STANDAARD_FEE_PCT = 0.25      # taker fee in procenten, overschrijfbaar via config

# De Docker-container draait op UTC, ongeacht de klok van de Pi zelf. Alles
# wat een mens te zien krijgt (activiteitenlog, "kan weer kopen om", het
# dagelijkse mailmoment) moet in Nederlandse tijd zijn, niet in UTC — anders
# staat er bijvoorbeeld 17:24 op het dashboard terwijl het 19:24 is. Een
# echte tijdzone (i.p.v. een vaste +2) verwerkt de overgang zomer-/wintertijd
# vanzelf correct.
NL_TZ = ZoneInfo("Europe/Amsterdam")


def nu_nl():
    """Huidig moment, correct in Nederlandse tijd — voor alles dat een mens leest."""
    return datetime.now(timezone.utc).astimezone(NL_TZ)


def parse_tijd_utc(iso_str):
    """
    Parseert een opgeslagen tijdstip als UTC-aware datetime. Tijdstippen van
    vóór deze fix zijn opgeslagen zonder tijdzone-marker, maar stonden al in
    UTC (de container-klok) — die interpreteren we alsnog als UTC in plaats
    van als naïef, anders knalt de vergelijking met een aware datetime.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def tijd_met_utc_marker(iso_str):
    """
    Zorgt dat een opgeslagen tijdstip altijd een tijdzone-marker heeft, ook
    de oudere naïeve tijdstippen van vóór deze fix. Nodig voordat zo'n
    tijdstip als kale string naar de browser gaat (activiteitenlog): zonder
    marker interpreteert JavaScript zo'n string als lokale tijd, terwijl het
    in werkelijkheid UTC was.
    """
    if not iso_str:
        return iso_str
    try:
        return parse_tijd_utc(iso_str).isoformat(timespec="seconds")
    except ValueError:
        return iso_str

logging.basicConfig(
    filename="bot_errors.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def log_error(context, error):
    logging.error("%s: %s", context, error, exc_info=True)


def log_info(bericht):
    logging.info(bericht)


# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------

def euro(bedrag, include_codeblock=True):
    geformatteerd = f"{bedrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if include_codeblock:
        return f"`€ {geformatteerd}`"
    return f"€ {geformatteerd}"


def laad_config():
    """Leest de config en garandeert dat de verwachte sleutels bestaan."""
    config = {"coins": {}, "global_settings": {}}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                geladen = json.load(f)
            if isinstance(geladen, dict):
                config.update(geladen)
        except Exception as e:
            log_error("laad_config", e)
    # setdefault voorkomt dat een ontbrekende sleutel later stilletjes verdwijnt
    config.setdefault("coins", {})
    config.setdefault("global_settings", {})
    # Losse muntenlijst voor de pot. Mag geen overlap hebben met "coins",
    # want Bitvavo geeft maar één saldo per munt terug.
    config.setdefault("pot_coins", {})
    # Dalpot: net als de pot, maar dan omgekeerd — kiest zelf de munt die
    # het hardst gedaald is, i.p.v. de meest volatiele. Volledig gescheiden
    # van coins en pot_coins, mag ook geen overlap hebben.
    config.setdefault("dalpot_coins", {})
    return config


def bewaar_config(config_data):
    """Schrijft de config atomisch weg, zodat een crash het bestand niet sloopt."""
    tijdelijk = CONFIG_FILE + ".tmp"
    with open(tijdelijk, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)
    os.replace(tijdelijk, CONFIG_FILE)


# ---------------------------------------------------------------------------
# Muntlogo's
#
# De oude template haalde logo's bij assets.coincap.io. Die dienst bestaat niet
# meer, vandaar de drie geneste onerror-vangnetten in de HTML. Hier halen we de
# logo-URL's een keer per dag bij CoinGecko en bewaren we ze in een bestand.
# Faalt dat, dan valt de pagina terug op een letterblokje.
# ---------------------------------------------------------------------------

ICOON_FILE = "coin_iconen.json"
ICOON_MAX_LEEFTIJD = 24 * 3600
COINGECKO = "https://api.coingecko.com/api/v3"


def laad_iconen():
    if os.path.exists(ICOON_FILE):
        try:
            with open(ICOON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            log_error("laad_iconen", e)
    return {"opgehaald": 0, "iconen": {}}


def bewaar_iconen(data):
    try:
        tijdelijk = ICOON_FILE + ".tmp"
        with open(tijdelijk, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tijdelijk, ICOON_FILE)
    except Exception as e:
        log_error("bewaar_iconen", e)


def _haal_iconen_op(symbolen):
    """Vraagt CoinGecko om de logo-URL per symbool. Geeft een dict terug."""
    gevonden = {}
    if not symbolen:
        return gevonden

    # CoinGecko accepteert maximaal een handvol symbolen per keer
    blokken = [symbolen[i:i + 25] for i in range(0, len(symbolen), 25)]
    for blok in blokken:
        try:
            r = requests.get(
                f"{COINGECKO}/coins/markets",
                params={"vs_currency": "eur", "symbols": ",".join(s.lower() for s in blok), "per_page": 250},
                timeout=15,
            )
            if r.status_code != 200:
                log_info(f"CoinGecko gaf status {r.status_code} voor iconen.")
                continue
            for item in r.json():
                symbool = (item.get("symbol") or "").upper()
                afbeelding = item.get("image")
                # De eerste treffer heeft de hoogste marktwaarde, die houden we aan
                if symbool and afbeelding and symbool not in gevonden:
                    gevonden[symbool] = afbeelding
        except Exception as e:
            log_error("_haal_iconen_op", e)
        time.sleep(1.5)
    return gevonden


def ververs_iconen(geforceerd=False):
    """Vult ontbrekende logo's aan. Draait in een eigen thread, blokkeert niets."""
    data = laad_iconen()
    iconen = data.get("iconen", {})
    config = laad_config()
    coins = list(dict.fromkeys(
        list(config.get("coins", {}).keys())
        + list(config.get("pot_coins", {}).keys())
        + list(config.get("dalpot_coins", {}).keys())
    ))

    vers_genoeg = (time.time() - data.get("opgehaald", 0)) < ICOON_MAX_LEEFTIJD
    ontbreekt = [c for c in coins if c not in iconen]

    if vers_genoeg and not ontbreekt and not geforceerd:
        return

    doel = coins if (geforceerd or not vers_genoeg) else ontbreekt
    nieuw = _haal_iconen_op(doel)
    if nieuw:
        iconen.update(nieuw)
        bewaar_iconen({"opgehaald": time.time(), "iconen": iconen})
        log_info(f"Logo's bijgewerkt voor {len(nieuw)} munten.")


def icoon_loop():
    while True:
        try:
            ververs_iconen()
        except Exception as e:
            log_error("icoon_loop", e)
        time.sleep(3600)


def icoon_voor(coin):
    return laad_iconen().get("iconen", {}).get(coin, "")


# ---------------------------------------------------------------------------
# Boekhouding
#
# Zonder dit weet je niet of de bot geld verdient. Hier houden we drie dingen
# bij: elke order in een logboek, hoeveel euro er per munt is ingelegd, en een
# reservepot die het aanvullen niet mag aanraken.
# ---------------------------------------------------------------------------

STATE_FILE = DATA_PREFIX + "bot_state.json"
STANDAARD_RESERVE_PCT = 50.0     # deel van elke afroming dat naar de reserve (BTC/ETH) gaat
# Reservemunten: hier gaat het afgeroomde deel van de winst naartoe. Op het
# dashboard kies je welke munt de nieuwe winst krijgt (reserve_actief); het
# hele saldo van ALLE reservemunten telt als reserve, ook na een wissel.
RESERVE_KEUZES = ["BTC", "ETH"]
STANDAARD_RESERVE_ACTIEF = "BTC"
RESERVE_ICOON = {"BTC": "₿", "ETH": "Ξ"}

# Donatie-adressen van de maker, getoond onderaan de uitlegpagina. Leeg = het
# donatieblok wordt niet getoond.
DONATIE_ADRESSEN = {
    "BTC": "bc1q0sjsskrmmmtm9zj2vaeady8h37w280xxffve6n",
    "ETH": "0x798483b4749654Fa0C1bffb95F27d7C401955c24",
    "SOL": "6Qe6o5FMQUUMifxAdzE75SsekYsFX6Bgft3JGPdmGJRT",
}


def actieve_reserve(config=None):
    """De munt waar nieuwe afgeroomde winst naartoe gaat."""
    config = config or laad_config()
    munt = str(config.get("global_settings", {}).get("reserve_actief", STANDAARD_RESERVE_ACTIEF)).upper()
    return munt if munt in RESERVE_KEUZES else STANDAARD_RESERVE_ACTIEF


def is_reserve_munt(coin):
    """
    Reservemunten horen bij geen enkele lijst. btc_reserve_waarde rekent het
    hele saldo van deze munten tot de reserve; staan ze ook in de hoofdlijst,
    pot of dalpot, dan telt de bot ze dubbel en kan hij reserve als winst
    verkopen.
    """
    return (coin or "").upper().replace("/EUR", "") in RESERVE_KEUZES


RESERVE_GEWEIGERD_TEKST = (
    "❌ *{munt}* is een reservemunt: " + " en ".join(RESERVE_KEUZES) + " zijn gereserveerd "
    "voor de afgeroomde winst. Bitvavo geeft maar één saldo per munt terug, dus de bot zou "
    "reserve als winst kunnen verkopen. Daarom kan {munt} niet in de hoofdlijst, pot of dalpot."
)
STANDAARD_MAX_INLEG = 1.5        # bodem: hoogstens 1,5 keer het budget inleggen
STANDAARD_HOOFDLIJST_WINSTDOEL_EUR = 11.0   # vast winstdoel per hoofdlijst-munt in euro's, niet in %

trades_tabel = None              # wordt in main() gezet


def laad_state():
    basis = {
        "reserve_eur": 0.0, "ingelegd": {}, "geoogst": {}, "gestart": None,
        # Pot: los potje waar de bot zelf in mag kopen en verkopen.
        "pot_cash_eur": 0.0, "pot_gestort": 0.0, "pot_noodstop_actief": False,
        "pot_laatste_koop": {}, "pot_besteed_vandaag": 0.0, "pot_besteed_datum": "",
        # Dalpot: zelfde soort boekhouding als de pot, maar volledig gescheiden.
        "dalpot_cash_eur": 0.0, "dalpot_gestort": 0.0, "dalpot_noodstop_actief": False,
        "dalpot_laatst_verkocht": {},
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                geladen = json.load(f)
            if isinstance(geladen, dict):
                basis.update(geladen)
        except Exception as e:
            log_error("laad_state", e)
    basis.setdefault("ingelegd", {})
    basis.setdefault("geoogst", {})
    basis.setdefault("pot_laatste_koop", {})
    return basis


def bewaar_state(state):
    try:
        tijdelijk = STATE_FILE + ".tmp"
        with open(tijdelijk, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tijdelijk, STATE_FILE)
    except Exception as e:
        log_error("bewaar_state", e)


def log_trade(munt, kant, aantal, koers, bedrag, fee_eur, bron):
    """Schrijft een order weg. Dit is de enige bron voor gerealiseerde winst."""
    try:
        if trades_tabel is None:
            return
        trades_tabel.insert({
            "tijd": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "munt": munt,
            "kant": kant,
            "aantal": aantal,
            "koers": koers,
            "bedrag": round(bedrag, 2),
            "fee": round(fee_eur, 4),
            "bron": bron,
        })
    except Exception as e:
        log_error("log_trade", e)


def _order_uitkomst(order, market, soort):
    """
    Haalt de echte status van een net geplaatste order op: "gevuld",
    "niet_gevuld" (door Bitvavo geannuleerd, er is niets gebeurd) of
    "onbekend" (status kon niet vastgesteld worden).
    """
    laatste_fout = None
    for _ in range(3):
        try:
            echt = exchange.fetch_order(order["id"], market)
            if echt.get("status") == "open":
                time.sleep(1)
                continue
            if echt.get("status") == "closed" and (echt.get("filled") or 0) > 0:
                return "gevuld"
            return "niet_gevuld"
        except Exception as e:
            laatste_fout = e
            time.sleep(1)
    if laatste_fout is not None:
        log_error(f"order_uitkomst.{market}", laatste_fout)
    send_telegram_message(
        f"⚠️ Kon niet controleren of de {soort} van *{market}* gelukt is. "
        f"Check even in Bitvavo en of de bot-boeken kloppen.",
        include_keyboard=True,
    )
    return "onbekend"


def plaats_marktorder(zijde, market, hoeveelheid, soort="aankoop"):
    """
    Plaatst een marktorder en controleert of hij echt gevuld is. Bitvavo kan
    een marktorder zonder foutmelding annuleren (bijvoorbeeld bij een te dun
    orderboek). Is dat gebeurd, dan wordt het nog één keer geprobeerd; nooit
    opnieuw bij een onduidelijke uitkomst, want dan zou er dubbel gekocht of
    verkocht kunnen worden. zijde "buy": hoeveelheid is het bedrag in euro,
    zijde "sell": het aantal munten. Een fout bij het plaatsen zelf gaat omhoog.
    Geeft True terug als er echt iets gevuld is.
    """
    for poging in range(2):
        if zijde == "buy":
            order = exchange.create_market_buy_order(market, None, {"amountQuote": hoeveelheid})
        else:
            order = exchange.create_market_sell_order(market, hoeveelheid)
        uitkomst = _order_uitkomst(order, market, soort)
        if uitkomst == "gevuld":
            return True
        if uitkomst == "onbekend":
            return False
        if poging == 0:
            log_info(f"{market}: {soort} niet gevuld door Bitvavo, nog één keer proberen.")
            time.sleep(2)
    return False


def recente_trades(limiet=20):
    """Laatste orders uit het logboek, nieuwste eerst. Voedt het activiteitenoverzicht op het dashboard."""
    if trades_tabel is None:
        return []
    try:
        alles = trades_tabel.all()
        alles.sort(key=lambda t: t.get("tijd", ""), reverse=True)
        resultaat = []
        for t in alles[:limiet]:
            resultaat.append({
                "tijd": tijd_met_utc_marker(t.get("tijd")),
                "munt": (t.get("munt") or "").replace("/EUR", ""),
                "kant": t.get("kant"),
                "bedrag": t.get("bedrag"),
                "fee": t.get("fee"),
                "bron": t.get("bron"),
            })
        return resultaat
    except Exception as e:
        log_error("recente_trades", e)
        return []


def registreer_koop(coin, bedrag):
    state = laad_state()
    state["ingelegd"][coin] = round(state["ingelegd"].get(coin, 0.0) + bedrag, 2)
    bewaar_state(state)


def koop_btc_reserve(bedrag_eur, fee):
    """
    Zet een bedrag om naar de actieve reservemunt (BTC of ETH, te kiezen op
    het dashboard). Dit is de vervanger van de oude EUR-reserve: in plaats van
    euro's opzij te zetten die niets doen, koopt de bot er meteen crypto voor.
    Er is geen apart 'reserve_eur'-bedrag meer dat aangroeit — de waarde staat
    gewoon in het echte saldo, zichtbaar via de normale balans.
    De bron blijft "reserve-btc", ook voor ETH, zodat oude en nieuwe
    logboekregels hetzelfde geteld worden.
    """
    if bedrag_eur < MIN_ORDER_EUR:
        return 0.0
    markt = f"{actieve_reserve()}/EUR"
    try:
        gevuld = plaats_marktorder("buy", markt, round(bedrag_eur, 2), "aankoop")
        cache.invalideer()
        if not gevuld:
            return 0.0
        log_trade(markt, "koop", None, None, bedrag_eur, bedrag_eur * fee, "reserve-btc")
        return bedrag_eur
    except Exception as e:
        log_error("koop_btc_reserve", e)
        return 0.0


def registreer_verkoop(coin, netto_opbrengst, config=None):
    """
    Boekt de netto opbrengst. Een deel (reserve_pct, standaard 50%) wordt
    direct omgezet naar de actieve reservemunt (BTC of ETH). De rest
    blijft gewoon vrije cash.
    """
    config = config or laad_config()
    reserve_pct = float(config.get("global_settings", {}).get("reserve_pct", STANDAARD_RESERVE_PCT))
    naar_btc = netto_opbrengst * max(0.0, min(100.0, reserve_pct)) / 100.0
    fee = fee_fractie(config)

    state = laad_state()
    state["geoogst"][coin] = round(state["geoogst"].get(coin, 0.0) + netto_opbrengst, 2)
    bewaar_state(state)

    return koop_btc_reserve(naar_btc, fee)


def registreer_pot_koop(coin, bedrag):
    """Zelfde boekhouding als registreer_koop, maar het geld komt uit de pot."""
    state = laad_state()
    state["ingelegd"][coin] = round(state["ingelegd"].get(coin, 0.0) + bedrag, 2)
    state["pot_cash_eur"] = round(state.get("pot_cash_eur", 0.0) - bedrag, 2)
    state["pot_laatste_koop"][coin] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bewaar_state(state)


def registreer_pot_verkoop(coin, netto_winst, volledige_opbrengst):
    """
    Pot-munten worden in hun geheel verkocht (niet alleen de winst afgeroomd
    zoals bij de hoofdlijst), zodat de plek weer vrijkomt voor een nieuwe
    munt. `netto_winst` is puur de winst (voor de boekhouding/statistieken),
    `volledige_opbrengst` is winst + oorspronkelijke inleg samen en gaat
    helemaal terug de pot-cash in.
    """
    state = laad_state()
    state["geoogst"][coin] = round(state["geoogst"].get(coin, 0.0) + netto_winst, 2)
    state["pot_cash_eur"] = round(state.get("pot_cash_eur", 0.0) + volledige_opbrengst, 2)
    state["ingelegd"].pop(coin, None)
    bewaar_state(state)


def registreer_dalpot_koop(coin, bedrag):
    """Zelfde boekhouding als registreer_pot_koop, maar dan voor de dalpot."""
    state = laad_state()
    state["ingelegd"][coin] = round(state["ingelegd"].get(coin, 0.0) + bedrag, 2)
    state["dalpot_cash_eur"] = round(state.get("dalpot_cash_eur", 0.0) - bedrag, 2)
    bewaar_state(state)


def registreer_dalpot_verkoop(coin, netto_winst, volledige_opbrengst):
    """Zelfde boekhouding als registreer_pot_verkoop, maar dan voor de dalpot."""
    state = laad_state()
    state["geoogst"][coin] = round(state["geoogst"].get(coin, 0.0) + netto_winst, 2)
    state["dalpot_cash_eur"] = round(state.get("dalpot_cash_eur", 0.0) + volledige_opbrengst, 2)
    state["ingelegd"].pop(coin, None)

    # Onthouden wanneer deze munt verkocht is, zodat de dalpot hem niet meteen
    # opnieuw kiest (zie _in_afkoelperiode). Oude vermeldingen ruimen we op.
    nu = datetime.now(timezone.utc)
    laatst = state.setdefault("dalpot_laatst_verkocht", {})
    laatst[coin] = nu.isoformat(timespec="seconds")
    for oud in [c for c, t in laatst.items() if not _in_afkoelperiode(t, 7 * 24.0)]:
        del laatst[oud]
    bewaar_state(state)


def _in_afkoelperiode(verkocht_op, uren):
    """True als het tijdstip (ISO, UTC) nog binnen het opgegeven aantal uren valt."""
    try:
        return (datetime.now(timezone.utc) - parse_tijd_utc(verkocht_op)) < timedelta(hours=uren)
    except (ValueError, TypeError):
        return False


def handelscash(vrij_cash, state=None):
    """Vrije cash minus de reserve, de pot en de dalpot. Hier mag het aanvullen aan komen."""
    state = state or laad_state()
    afgezonderd = (
        state.get("reserve_eur", 0.0)
        + state.get("pot_cash_eur", 0.0)
        + state.get("dalpot_cash_eur", 0.0)
    )
    return max(0.0, vrij_cash - afgezonderd)


def inleg_bodem(coin, budget, config=None, state=None):
    """Geeft (ingelegd, plafond, op_slot) terug voor deze munt.

    state kan worden meegegeven zodat bot_state.json niet per munt opnieuw
    van schijf gelezen wordt (dat gebeurde eerder 24+ keer per dashboardverzoek).
    """
    config = config or laad_config()
    factor = float(config.get("global_settings", {}).get("max_inleg_factor", STANDAARD_MAX_INLEG))
    state = state if state is not None else laad_state()
    ingelegd = state.get("ingelegd", {}).get(coin, 0.0)
    plafond = budget * factor
    return ingelegd, plafond, ingelegd >= plafond


def gerealiseerd_totaal(state=None):
    state = state if state is not None else laad_state()
    return round(sum(state.get("geoogst", {}).values()), 2)


def bereken_doel(budget, tp_pct, fee):
    """
    Geeft (netto_doel, bruto_doel) terug.

    netto_doel is wat er na fee overblijft, bruto_doel is de winst die de positie
    moet laten zien voordat de bot in trailing gaat. Het dashboard gebruikt
    hetzelfde bruto_doel, anders staat de voortgangsbalk op 100 procent terwijl
    de bot nog niet verkoopt.
    """
    netto_doel = max(budget * (tp_pct / 100.0), MIN_WINST_EUR)
    bruto_doel = netto_doel / (1.0 - fee) if fee < 1 else netto_doel
    return netto_doel, bruto_doel


def fee_fractie(config=None):
    """Handelskosten als fractie, bijvoorbeeld 0.0025 voor 0.25 procent."""
    config = config or laad_config()
    pct = config.get("global_settings", {}).get("fee_pct", STANDAARD_FEE_PCT)
    try:
        return max(0.0, float(pct)) / 100.0
    except (TypeError, ValueError):
        return STANDAARD_FEE_PCT / 100.0


# ---------------------------------------------------------------------------
# Exchange, database en locking
# ---------------------------------------------------------------------------

class AtomischeJSONStorage(Storage):
    """
    TinyDB's eigen JSONStorage truncate't het bestand en schrijft er dan
    overheen — niet atomisch. Wordt het proces precies op dat moment gekilled
    (bijvoorbeeld door 'docker compose restart'), dan blijft er een leeg of
    half bestand over en crasht elke volgende lezing met een JSONDecodeError.
    Dat is hier meermaals per dag live waargenomen sinds 10 september.

    Schrijft in plaats daarvan naar een tijdelijk bestand en verwisselt dat
    met os.replace(), atomisch op besturingssysteemniveau — zelfde patroon
    als bewaar_config()/bewaar_state() al gebruiken.
    """

    def __init__(self, path):
        self._path = path

    def read(self):
        if not os.path.exists(self._path) or os.path.getsize(self._path) == 0:
            return None
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, data):
        tijdelijk = self._path + ".tmp"
        with open(tijdelijk, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tijdelijk, self._path)

    def close(self):
        pass


db = TinyDB(DB_FILE, storage=AtomischeJSONStorage)
Trade = Query()

class DemoExchange:
    """
    Nep-exchange voor de demo-modus. Koersen, markten, precisie en candles
    komen gewoon van Bitvavo (openbare data, geen key nodig). Alleen saldo en
    orders zijn nagebootst: een order wordt direct gevuld tegen de actuele
    vraag- of biedprijs, met de standaard fee. Het saldo staat in
    demo_saldo.json en blijft dus bewaard na een herstart.

    De rest van de bot merkt geen verschil: hij gebruikt dezelfde functies
    (fetch_balance, create_market_*_order, fetch_order) als bij de echte
    exchange, dus de handelslogica wordt precies zo getest als hij live draait.
    """

    SALDO_FILE = "demo_saldo.json"
    MIN_ORDER_EUR = 5.0

    def __init__(self, startkapitaal):
        self._echt = ccxt.bitvavo({"enableRateLimit": True})
        self._lock = threading.Lock()
        self._orders = {}
        self._fee = STANDAARD_FEE_PCT / 100.0
        self._saldo = self._laad_saldo(startkapitaal)

    def __getattr__(self, naam):
        # Alles wat hier niet nagebootst wordt (markets, load_markets,
        # fetch_tickers, fetch_ohlcv, amount_to_precision, market, ...) gaat
        # gewoon naar de openbare Bitvavo-API.
        return getattr(self._echt, naam)

    def _laad_saldo(self, startkapitaal):
        if os.path.exists(self.SALDO_FILE):
            try:
                with open(self.SALDO_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {k: float(v) for k, v in data.items()}
            except Exception as e:
                log_error("demo_laad_saldo", e)
        saldo = {"EUR": float(startkapitaal)}
        self._bewaar_saldo(saldo)
        return saldo

    def _bewaar_saldo(self, saldo):
        tijdelijk = self.SALDO_FILE + ".tmp"
        with open(tijdelijk, "w", encoding="utf-8") as f:
            json.dump(saldo, f, indent=2)
        os.replace(tijdelijk, self.SALDO_FILE)

    def _prijs(self, market, kant):
        ticker = self._echt.fetch_ticker(market)
        prijs = ticker.get(kant) or ticker.get("last")
        if not prijs:
            raise ccxt.ExchangeError(f"Demo: geen koers voor {market}")
        return float(prijs)

    def fetch_balance(self, params=None):
        with self._lock:
            saldo = {k: v for k, v in self._saldo.items() if v > 0}
        resultaat = {"free": dict(saldo), "used": {k: 0.0 for k in saldo}, "total": dict(saldo)}
        for munt, aantal in saldo.items():
            resultaat[munt] = {"free": aantal, "used": 0.0, "total": aantal}
        return resultaat

    def _vul_order(self, market, kant, aantal, prijs, kosten, fee_eur):
        order_id = f"demo-{uuid.uuid4()}"
        order = {
            "id": order_id, "symbol": market, "type": "market", "side": kant,
            "status": "closed", "amount": aantal, "filled": aantal, "remaining": 0.0,
            "price": prijs, "average": prijs, "cost": kosten,
            "fee": {"currency": "EUR", "cost": fee_eur},
            "timestamp": int(time.time() * 1000),
        }
        self._orders[order_id] = order
        return order

    def create_market_buy_order(self, market, amount, params=None):
        bedrag = float((params or {}).get("amountQuote") or 0.0)
        if bedrag < self.MIN_ORDER_EUR:
            raise ccxt.InvalidOrder(f"Demo: order van € {bedrag:.2f} is onder het minimum")
        munt = market.split("/")[0]
        prijs = self._prijs(market, "ask")
        fee_eur = bedrag * self._fee
        aantal = float(self._echt.amount_to_precision(market, (bedrag - fee_eur) / prijs))
        with self._lock:
            if self._saldo.get("EUR", 0.0) + 1e-9 < bedrag:
                raise ccxt.InsufficientFunds(f"Demo: niet genoeg EUR voor € {bedrag:.2f}")
            self._saldo["EUR"] = self._saldo.get("EUR", 0.0) - bedrag
            self._saldo[munt] = self._saldo.get(munt, 0.0) + aantal
            self._bewaar_saldo(self._saldo)
            return self._vul_order(market, "buy", aantal, prijs, bedrag, fee_eur)

    def create_market_sell_order(self, market, amount, params=None):
        munt = market.split("/")[0]
        aantal = float(amount)
        prijs = self._prijs(market, "bid")
        bruto = aantal * prijs
        if bruto < self.MIN_ORDER_EUR:
            raise ccxt.InvalidOrder(f"Demo: order van € {bruto:.2f} is onder het minimum")
        fee_eur = bruto * self._fee
        with self._lock:
            if self._saldo.get(munt, 0.0) + 1e-12 < aantal:
                raise ccxt.InsufficientFunds(f"Demo: niet genoeg {munt} om {aantal} te verkopen")
            self._saldo[munt] = max(0.0, self._saldo.get(munt, 0.0) - aantal)
            self._saldo["EUR"] = self._saldo.get("EUR", 0.0) + bruto - fee_eur
            self._bewaar_saldo(self._saldo)
            return self._vul_order(market, "sell", aantal, prijs, bruto, fee_eur)

    def fetch_order(self, order_id, market=None, params=None):
        order = self._orders.get(order_id)
        if order is None:
            raise ccxt.OrderNotFound(f"Demo: order {order_id} onbekend")
        return order


if DEMO_MODUS:
    exchange = DemoExchange(DEMO_STARTKAPITAAL)
else:
    exchange = ccxt.bitvavo({
        "apiKey": BITVAVO_KEY,
        "secret": BITVAVO_SECRET,
        "enableRateLimit": True,
        "options": {"operatorId": BITVAVO_OPERATOR_ID},
    })

# RLock zodat een functie die de lock heeft een andere functie mag aanroepen
# die de lock ook neemt, zonder zichzelf te blokkeren.
handel_lock = threading.RLock()

INSTELLINGEN_MODUS = None
BOT_ACTIVE = True


def met_lock(func):
    """Decorator voor alles wat orders plaatst of naar config of database schrijft."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        with handel_lock:
            return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Cache voor balans en koersen
# ---------------------------------------------------------------------------

class MarktCache:
    """
    Houdt balans en tickers kort vast. De oude versie deed elke twee seconden
    twee zware calls naar Bitvavo, wat de rate limit opvreet.
    """

    def __init__(self, balans_ttl=30.0, tickers_ttl=5.0):
        self.balans_ttl = balans_ttl
        self.tickers_ttl = tickers_ttl
        self._balans = None
        self._balans_tijd = 0.0
        self._tickers = None
        self._tickers_tijd = 0.0
        self._lock = threading.Lock()

    def balans(self, force=False):
        with self._lock:
            if force or self._balans is None or (time.time() - self._balans_tijd) > self.balans_ttl:
                self._balans = exchange.fetch_balance()
                self._balans_tijd = time.time()
            return self._balans

    def tickers(self, force=False):
        with self._lock:
            if force or self._tickers is None or (time.time() - self._tickers_tijd) > self.tickers_ttl:
                self._tickers = exchange.fetch_tickers()
                self._tickers_tijd = time.time()
            return self._tickers

    def invalideer(self):
        """Na een order kloppen balans en koers niet meer. Volgende call haalt vers op."""
        with self._lock:
            self._balans_tijd = 0.0
            self._tickers_tijd = 0.0


cache = MarktCache()


def koers_van(tickers, market):
    """Haalt de laatste koers op, of None wanneer de markt onbekend is."""
    ticker = tickers.get(market)
    if not ticker:
        return None
    laatste = ticker.get("last")
    if not laatste:
        return None
    return float(laatste)


def reserve_waarden(balans=None, tickers=None):
    """
    EUR-waarde per reservemunt, voor de reservekaart op het dashboard. Toont
    elke munt met saldo, plus altijd de actieve munt (ook als die nog op nul
    staat). Gewoon de echte balans, dus beweegt mee met de koers.
    """
    balans = balans if balans is not None else cache.balans()
    tickers = tickers if tickers is not None else cache.tickers()
    actief = actieve_reserve()
    regels = []
    for munt in RESERVE_KEUZES:
        aantal = balans["total"].get(munt, 0.0)
        waarde = aantal * (koers_van(tickers, f"{munt}/EUR") or 0.0)
        if waarde > 0 or munt == actief:
            regels.append({"munt": munt, "waarde": waarde, "actief": munt == actief})
    return regels


def btc_reserve_waarde(balans=None, tickers=None):
    """
    Totale EUR-waarde van alle reservemunten samen (BTC + ETH), ongeacht welke
    nu actief is. Alle totalen (dashboard, rapport, historie) gebruiken dit,
    dus een oude BTC-reserve blijft meetellen na een wissel naar ETH.
    """
    return sum(r["waarde"] for r in reserve_waarden(balans, tickers))


def reserve_naam(balans=None, tickers=None):
    """Korte naam voor teksten, bijvoorbeeld 'BTC' of 'BTC + ETH'."""
    try:
        return " + ".join(r["munt"] for r in reserve_waarden(balans, tickers))
    except Exception:
        return actieve_reserve()


# ---------------------------------------------------------------------------
# Orderprecisie en minimumeisen
# ---------------------------------------------------------------------------

def markt_bestaat(market):
    try:
        return market in exchange.markets
    except Exception as e:
        log_error("markt_bestaat", e)
        return False


def bereken_verkoop_aantal(market, bedrag_eur, live_koers):
    """
    Rekent een eurobedrag om naar een aantal munten en rondt dat af op de
    precisie die Bitvavo voor deze markt eist. Geeft None terug wanneer het
    resultaat onder de minimum order-eisen valt.
    """
    if live_koers <= 0 or bedrag_eur <= 0:
        return None
    try:
        ruw = bedrag_eur / live_koers
        aantal = float(exchange.amount_to_precision(market, ruw))
    except Exception as e:
        log_error(f"bereken_verkoop_aantal.{market}", e)
        return None

    if aantal <= 0:
        return None

    limieten = exchange.market(market).get("limits", {}) if markt_bestaat(market) else {}
    min_aantal = (limieten.get("amount") or {}).get("min")
    min_waarde = (limieten.get("cost") or {}).get("min")

    if min_aantal and aantal < float(min_aantal):
        return None
    if min_waarde and (aantal * live_koers) < float(min_waarde):
        return None
    if (aantal * live_koers) < MIN_ORDER_EUR:
        return None
    return aantal


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

HOOFD_KEYBOARD = [
    [{"text": "📊 LIVE DASHBOARD"}, {"text": "💼 OVERZICHT"}],
    [{"text": "🧪 POT"}, {"text": "🛒 HANDELEN"}],
]

TERUG_KEYBOARD = [[{"text": "🔙 Terug naar Menu"}]]

HANDEL_KEYBOARD = [
    [{"text": "🛒 Alles Aanvullen"}, {"text": "💰 Handmatig Afromen"}],
    [{"text": "🪙 Munten Beheren"}, {"text": "➕ Munt Toevoegen"}],
    [{"text": "➖ Munt Verwijderen"}, {"text": "💵 Budget Wijzigen"}],
    [{"text": "🔙 Terug naar Menu"}],
]

POT_KEYBOARD = [
    [{"text": "➕ Pot Munt Toevoegen"}, {"text": "➖ Pot Munt Verwijderen"}],
    [{"text": "💶 Pot Storten"}, {"text": "💶 Pot Opnemen"}],
    [{"text": "🚫 Munt Uitsluiten"}, {"text": "🔄 Pot Nu Laten Kiezen"}],
    [{"text": "🔙 Terug naar Menu"}],
]


# ---------------------------------------------------------------------------
# Volatiliteit
#
# Een doel van 3 procent hangt nu aan de grootte van het budget, wat niets zegt
# over hoe een munt beweegt. Hier meten we de gemiddelde dagrange over 14 dagen
# en schalen we doel en trailing stop daarop.
# ---------------------------------------------------------------------------

def meet_volatiliteit(market):
    """Gemiddelde dagrange in procenten over de laatste 14 dagen, of None."""
    try:
        kaarsen = exchange.fetch_ohlcv(market, timeframe="1d", limit=15)
        if not kaarsen or len(kaarsen) < 5:
            return None
        ranges = []
        for k in kaarsen[:-1]:          # laatste dag is nog niet af
            hoog, laag, slot = k[2], k[3], k[4]
            if slot:
                ranges.append(((hoog - laag) / slot) * 100.0)
        if not ranges:
            return None
        return sum(ranges) / len(ranges)
    except Exception as e:
        log_error(f"meet_volatiliteit.{market}", e)
        return None


def begrens(waarde, laag, hoog):
    return max(laag, min(hoog, waarde))


def ververs_parameters():
    """
    Zet per munt take profit en trailing stop op basis van de beweeglijkheid.
    Een munt met "vast_doel": true in de config blijft met rust gelaten.

    Belangrijk: de metingen zelf (netwerkcalls naar Bitvavo, één per munt, met
    een korte pauze ertussen) gebeuren BUITEN de handelslock. Dat kan bij ~24
    munten een kwart minuut duren, en zolang de lock daarvoor vastzat stonden
    check_portfolio() en elke Telegram- of dashboardactie stil. Alleen het
    wegschrijven van de config aan het eind gaat nog onder de lock, en dat
    duurt milliseconden.
    """
    config = laad_config()
    if not config.get("global_settings", {}).get("volatiliteit_schaal", True):
        return

    # Meten: geen lock. Werk op een kopie van de coinlijsten, niet op het
    # levende config-object, zodat we tijdens het meten niets vasthouden.
    # Zowel de hoofdlijst als de pot krijgen doelen op maat van hun volatiliteit.
    coins_snapshot = {}
    for lijst in ("coins", "pot_coins"):
        for coin, info in config.get(lijst, {}).items():
            coins_snapshot[coin] = (lijst, dict(info))

    nieuwe_waarden = {}
    for coin, (lijst, info) in coins_snapshot.items():
        if info.get("vast_doel"):
            continue
        market = f"{coin}/EUR"
        atr = meet_volatiliteit(market)
        if atr is None:
            continue

        nieuw_tp = round(begrens(1.2 * atr, 2.0, 12.0), 2)
        nieuw_trail = round(begrens(0.35 * atr, 0.6, 3.0), 2)

        if info.get("take_profit_pct") != nieuw_tp or info.get("trailing_sell_pct") != nieuw_trail:
            nieuwe_waarden[coin] = (lijst, nieuw_tp, nieuw_trail, round(atr, 2))
        time.sleep(0.3)

    if not nieuwe_waarden:
        return

    # Schrijven: wel onder de lock, en de config wordt hier opnieuw ingelezen
    # zodat een wijziging die jij ondertussen via Telegram deed niet verloren gaat.
    with handel_lock:
        verse_config = laad_config()
        gewijzigd = []
        for coin, (lijst, nieuw_tp, nieuw_trail, dagrange) in nieuwe_waarden.items():
            if coin not in verse_config.get(lijst, {}):
                continue
            info = verse_config[lijst][coin]
            if info.get("vast_doel"):
                continue
            info["take_profit_pct"] = nieuw_tp
            info["trailing_sell_pct"] = nieuw_trail
            info["dagrange_pct"] = dagrange
            gewijzigd.append(f"{coin}: doel {nieuw_tp}%, stop {nieuw_trail}%")

        if gewijzigd:
            bewaar_config(verse_config)
            log_info("Parameters bijgesteld: " + "; ".join(gewijzigd))


def parameter_loop():
    while True:
        try:
            ververs_parameters()
        except Exception as e:
            log_error("parameter_loop", e)
        time.sleep(24 * 3600)


def pot_kies_loop():
    """
    Los van de dagelijkse parameter_loop: de pot mag nooit lang met werkloze
    cash blijven zitten, dus dit probeert elk uur opnieuw een munt te kiezen
    zolang er ruimte en genoeg cash is. kies_pot_munten() doet zelf niets als
    er geen vrije plek is of geen kandidaat voldoet.
    """
    while True:
        try:
            kies_pot_munten()
        except Exception as e:
            log_error("pot_kies_loop", e)
        time.sleep(3600)


def dalpot_kies_loop():
    """Zelfde soort achtergrondlus als pot_kies_loop(), maar voor de dalpot."""
    while True:
        try:
            kies_dalpot_munten()
        except Exception as e:
            log_error("dalpot_kies_loop", e)
        time.sleep(3600)


def markten_ververs_loop():
    """
    exchange.load_markets() draait normaal maar één keer, bij het opstarten
    (zie main()). Een net op Bitvavo genoteerde munt (zoals XDP eerder) kon
    daardoor pas na een handmatige herstart worden toegevoegd. Deze lus
    ververst de marktenlijst periodiek op de achtergrond, zodat dat niet meer
    nodig is.
    """
    while True:
        time.sleep(4 * 3600)
        try:
            exchange.load_markets(reload=True)
        except Exception as e:
            log_error("markten_ververs_loop", e)


def laagste_recent(market, uren=6):
    """Laagste koers van de afgelopen uren. Voor het wachten op een bodem."""
    try:
        kaarsen = exchange.fetch_ohlcv(market, timeframe="1h", limit=uren)
        if not kaarsen:
            return None
        return min(k[3] for k in kaarsen)
    except Exception as e:
        log_error(f"laagste_recent.{market}", e)
        return None


def send_telegram_message(text, include_keyboard=False, custom_keyboard=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log_info("Telegram niet geconfigureerd, bericht overgeslagen.")
        return
    if DEMO_MODUS:
        text = "🧪 [DEMO] " + text
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}

    if custom_keyboard:
        payload["reply_markup"] = {
            "keyboard": custom_keyboard,
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }
    elif include_keyboard:
        payload["reply_markup"] = {
            "keyboard": HOOFD_KEYBOARD,
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        log_error("send_telegram_message", e)


# ---------------------------------------------------------------------------
# E-mailrapport
# ---------------------------------------------------------------------------

def stuur_email_rapport():
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        send_telegram_message("⚠️ *E-mailinstellingen ontbreken in .env bestand!*", include_keyboard=True)
        return

    try:
        config = laad_config()
        coins = config.get("coins", {})
        balans = cache.balans()
        tickers = cache.tickers()
        vrij_cash = balans["free"].get("EUR", 0.0)

        totaal_belegd = 0.0
        positie_regels = []

        for coin, info in coins.items():
            budget = info.get("budget_eur", 0.0)
            market = f"{coin}/EUR"
            live_koers = koers_van(tickers, market)
            if live_koers is None:
                positie_regels.append(f"• {coin.ljust(6)}: markt niet gevonden")
                continue
            waarde = balans["total"].get(coin, 0.0) * live_koers
            totaal_belegd += waarde
            rendement = ((waarde - budget) / budget) * 100 if budget > 0 else 0
            positie_regels.append(
                f"• {coin.ljust(6)}: € {waarde:8.2f} ({rendement:+6.1f}%) [Budget: €{budget:.0f}]"
            )

        btc_waarde = btc_reserve_waarde(balans, tickers)
        pot = verzamel_pot()
        pot_belegd = pot["belegd"]
        dalpot_belegd = verzamel_dalpot()["belegd"]
        echt_vrij = handelscash(vrij_cash, laad_state())
        totaal_portfolio = vrij_cash + totaal_belegd + btc_waarde + pot_belegd + dalpot_belegd

        msg = EmailMessage()
        msg["Subject"] = f"📈 Profit Harvester Rapport - {nu_nl().strftime('%d-%m-%Y %H:%M')}"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER

        body_tekst = (
            f"PROFIT HARVESTER V5.7 - PORTFOLIO OVERZICHT\n"
            f"Datum: {nu_nl().strftime('%d-%m-%Y %H:%M:%S')}\n\n"
            f"KAPITAAL\n"
            f"Vrije cash:              € {echt_vrij:>10,.2f}\n"
            f"Gereserveerd voor pot:   € {pot['cash']:>10,.2f}\n\n"
            f"VERDELING\n"
            f"Belegd:                  € {totaal_belegd:>10,.2f}\n"
            f"Afgeroomd naar reserve:  € {btc_waarde:>10,.2f}  ({reserve_naam()})\n"
            f"Belegd in pot:           € {pot_belegd:>10,.2f}\n"
            f"----------------------------------------\n"
            f"TOTALE WAARDE:           € {totaal_portfolio:>10,.2f}\n"
            f"----------------------------------------\n\n"
            f"POSITIES OVERZICHT:\n" + "\n".join(positie_regels) + "\n"
            f"----------------------------------------\n\n"
            f"De Profit Harvester monitort momenteel {len(coins)} munten actief op Bitvavo."
        )
        msg.set_content(body_tekst)

        with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_POORT, timeout=30) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)

        send_telegram_message(
            f"📧 *E-mailrapport succesvol verzonden naar {EMAIL_RECEIVER}!*", include_keyboard=True
        )

    except Exception as e:
        log_error("stuur_email_rapport", e)
        send_telegram_message("🚨 *Versturen van het e-mailrapport is mislukt.* Zie bot_errors.log.", include_keyboard=True)


# ---------------------------------------------------------------------------
# Kern: portfolio bewaken en afromen
# ---------------------------------------------------------------------------

def _verkoop_check_munt(coin, info, config, fee, globale_trail, balans, tickers, boek_fn, bron):
    """
    Bewaakt één munt en verkoopt de winst zodra de trailing stop raakt.

    Gedeeld door de hoofdlijst en de pot: alleen boek_fn (waar de opbrengst
    heen gaat, reserve of pot) en bron (voor het Telegram-bericht) verschillen.
    """
    market = f"{coin}/EUR"
    budget = info.get("budget_eur", 250.0)
    tp_pct = info.get("take_profit_pct", 3.0)
    label = " (Pot)" if bron == "pot" else ""

    if time.time() < _verkoop_pauze.get(coin, 0.0):
        return

    live_koers = koers_van(tickers, market)
    if live_koers is None:
        return

    aantal = balans["total"].get(coin, 0.0)
    actuele_waarde = aantal * live_koers

    # Doelwinst is netto, dus na aftrek van de verkoopfee
    _, bruto_doel = bereken_doel(budget, tp_pct, fee)
    target_waarde = budget + bruto_doel

    bestaande_trade = db.get(Trade.munt == market)
    if not bestaande_trade:
        db.insert({"munt": market, "status": "MONITORING", "piek_koers": 0.0, "laagste_koers": 0.0})
        bestaande_trade = db.get(Trade.munt == market)

    huidige_status = bestaande_trade.get("status", "MONITORING")

    if actuele_waarde >= target_waarde and huidige_status == "MONITORING":
        db.update({"status": "PUMPING", "piek_koers": live_koers}, Trade.munt == market)
        send_telegram_message(
            f"🚀 *TRAILING PROFIT GEACTIVEERD*{label} 🚀\n\n"
            f"• Munt: *{coin}*\n"
            f"• Waarde: {euro(actuele_waarde)}",
            include_keyboard=True,
        )
        return

    if huidige_status != "PUMPING":
        return

    # LET OP: hier NIET meer direct terug naar MONITORING zodra de
    # waarde onder target_waarde zakt. Bij een munt die 5-12% per dag
    # beweegt met een doel rond diezelfde orde grootte, schommelt de
    # koers voortdurend rond de doellijn. Als elke kleine terugval de
    # PUMPING-status meteen resette, kwam de trailing-stop-check
    # hieronder bijna nooit meer aan de beurt en werd er zelden
    # verkocht. In plaats daarvan geldt nu: eerst normaal de piek
    # bijhouden en de trailing stop toetsen. Alleen als de koers
    # daadwerkelijk fors terugvalt (verder dan de trailing stop zelf
    # toestaat) geven we de status op en beginnen we opnieuw te meten
    # vanaf het budget.

    oude_piek = bestaande_trade.get("piek_koers") or live_koers
    if live_koers > oude_piek:
        db.update({"piek_koers": live_koers}, Trade.munt == market)
        oude_piek = live_koers

    trailing_pct = float(info.get("trailing_sell_pct", globale_trail))
    daling_pct = ((oude_piek - live_koers) / oude_piek) * 100 if oude_piek else 0.0

    # Alleen helemaal opgeven als de waarde ver onder het budget
    # terugvalt (dubbele trailing-afstand), niet bij elke kleine dip
    # onder target_waarde.
    if actuele_waarde < budget - (2 * trailing_pct / 100.0) * budget:
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)
        return

    if daling_pct < trailing_pct:
        return

    bruto_winst = round(actuele_waarde - budget, 2)
    netto_winst = bruto_winst * (1.0 - fee)
    if netto_winst < MIN_WINST_EUR:
        # De trailing stop is al echt geraakt (verder dan trailing_pct vanaf
        # de piek), maar wat er nog aan winst over is, is te weinig om voor
        # te verkopen. De oude piek is dan niets meer waard — zonder reset
        # zou de status op "Volgt de top" blijven hangen met een allang
        # achterhaalde piek, ook nadat de koers al flink is teruggevallen.
        # Terug naar MONITORING, precies alsof de munt net op budget is
        # gekocht: dat klopt hier wel, want dit gebeurt pas ná een echte
        # trailing-terugval, niet bij elke kleine dip onder het doel.
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)
        return

    aantal_verkopen = bereken_verkoop_aantal(market, bruto_winst, live_koers)
    if aantal_verkopen is None:
        log_info(f"{market}: afromen overgeslagen, order te klein of precisie niet haalbaar.")
        return
    if aantal_verkopen >= aantal:
        log_info(f"{market}: afromen overgeslagen, berekend aantal is groter dan het saldo.")
        return

    gevuld = plaats_marktorder("sell", market, aantal_verkopen, "verkoop")
    cache.invalideer()
    if not gevuld:
        log_info(f"{market}: afromen niet gevuld, over {VERKOOP_MISLUKT_PAUZE // 60} minuten opnieuw.")
        _verkoop_pauze[coin] = time.time() + VERKOOP_MISLUKT_PAUZE
        return
    db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)

    log_trade(market, "verkoop", aantal_verkopen, live_koers,
              bruto_winst, bruto_winst * fee, "automatisch" if bron == "hoofd" else "pot-automatisch")
    apart = boek_fn(coin, netto_winst, config)
    regel_extra = f"• Naar {actieve_reserve(config)} omgezet: {euro(apart)}" if bron == "hoofd" else "• Blijft in de pot"

    send_telegram_message(
        f"💰 *WINST AFGEROOMD*{label}:\n"
        f"• Van: *{coin}*\n"
        f"• Bruto: {euro(bruto_winst)}\n"
        f"• Netto na fee: {euro(netto_winst)}\n"
        f"{regel_extra}",
        include_keyboard=True,
    )


def _pot_verkoop_check_munt(coin, info, config, fee, globale_trail, balans, tickers):
    """
    Zelfde piek/trailing-bewaking als de hoofdlijst, maar de pot verkoopt de
    HELE positie in één keer zodra de trailing stop raakt (niet alleen de
    winst). Het vrijgekomen plekje wordt meteen weer opgevuld met een nieuw
    gekozen munt, zodat de pot nooit met werkloze cash blijft zitten.
    """
    market = f"{coin}/EUR"
    budget = info.get("budget_eur", 250.0)
    tp_pct = info.get("take_profit_pct", 4.0)

    if time.time() < _verkoop_pauze.get(coin, 0.0):
        return

    live_koers = koers_van(tickers, market)
    if live_koers is None:
        return

    aantal = balans["total"].get(coin, 0.0)
    actuele_waarde = aantal * live_koers

    _, bruto_doel = bereken_doel(budget, tp_pct, fee)
    target_waarde = budget + bruto_doel

    bestaande_trade = db.get(Trade.munt == market)
    if not bestaande_trade:
        db.insert({"munt": market, "status": "MONITORING", "piek_koers": 0.0, "laagste_koers": 0.0})
        bestaande_trade = db.get(Trade.munt == market)

    huidige_status = bestaande_trade.get("status", "MONITORING")

    if actuele_waarde >= target_waarde and huidige_status == "MONITORING":
        db.update({"status": "PUMPING", "piek_koers": live_koers}, Trade.munt == market)
        send_telegram_message(
            f"🚀 *TRAILING PROFIT GEACTIVEERD* (Pot) 🚀\n\n"
            f"• Munt: *{coin}*\n"
            f"• Waarde: {euro(actuele_waarde)}",
            include_keyboard=True,
        )
        return

    if huidige_status != "PUMPING":
        return

    oude_piek = bestaande_trade.get("piek_koers") or live_koers
    if live_koers > oude_piek:
        db.update({"piek_koers": live_koers}, Trade.munt == market)
        oude_piek = live_koers

    trailing_pct = float(info.get("trailing_sell_pct", globale_trail))
    daling_pct = ((oude_piek - live_koers) / oude_piek) * 100 if oude_piek else 0.0

    if actuele_waarde < budget - (2 * trailing_pct / 100.0) * budget:
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)
        return

    if daling_pct < trailing_pct:
        return

    netto_opbrengst = round(actuele_waarde * (1.0 - fee), 2)
    netto_winst = round(netto_opbrengst - budget, 2)
    if netto_winst < MIN_WINST_EUR:
        # Zelfde situatie als bij de hoofdlijst: de trailing stop is al
        # geraakt, maar de winst is te klein om voor te verkopen. Zonder
        # reset blijft "Volgt de top" hangen met een allang achterhaalde
        # piek. Terug naar MONITORING vanaf budget, alsof net gekocht.
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)
        return

    try:
        gevuld = plaats_marktorder("sell", market, aantal, "verkoop")
    except Exception as e:
        log_error(f"_pot_verkoop_check_munt.{coin}", e)
        _verkoop_pauze[coin] = time.time() + VERKOOP_MISLUKT_PAUZE
        return

    cache.invalideer()
    if not gevuld:
        log_info(f"Pot: verkoop van {coin} is niet gevuld, over {VERKOOP_MISLUKT_PAUZE // 60} minuten opnieuw.")
        _verkoop_pauze[coin] = time.time() + VERKOOP_MISLUKT_PAUZE
        return

    db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)

    log_trade(market, "verkoop", aantal, live_koers, netto_winst, netto_winst * fee, "pot-automatisch")
    registreer_pot_verkoop(coin, netto_winst, netto_opbrengst)

    verse_config = laad_config()
    verse_config.get("pot_coins", {}).pop(coin, None)
    bewaar_config(verse_config)

    send_telegram_message(
        f"💰 *POT-MUNT VOLLEDIG VERKOCHT*:\n"
        f"• Van: *{coin}*\n"
        f"• Opbrengst: {euro(netto_opbrengst)}\n"
        f"• Winst: {euro(netto_winst)}\n"
        f"_Plekje is vrij, de pot zoekt meteen een vervanger._",
        include_keyboard=True,
    )

    threading.Thread(target=kies_pot_munten, daemon=True).start()


def _dalpot_verkoop_check_munt(coin, info, config, fee, globale_trail, balans, tickers):
    """
    Zelfde piek/trailing-bewaking als de pot, maar dan voor de dalpot
    (koopt de grootste dagverliezer, verkoopt bij herstel). Geen aparte
    "opgeven bij te grote daling"-drempel zoals bij de hoofdlijst/pot: de
    dalpot laat een munt bewust gewoon liggen als hij blijft zakken, dat is
    precies het idee — geen stop-loss.
    """
    market = f"{coin}/EUR"
    budget = info.get("budget_eur", 100.0)
    tp_pct = info.get("take_profit_pct", 10.0)

    if time.time() < _verkoop_pauze.get(coin, 0.0):
        return

    live_koers = koers_van(tickers, market)
    if live_koers is None:
        return

    aantal = balans["total"].get(coin, 0.0)
    actuele_waarde = aantal * live_koers

    _, bruto_doel = bereken_doel(budget, tp_pct, fee)
    target_waarde = budget + bruto_doel

    bestaande_trade = db.get(Trade.munt == market)
    if not bestaande_trade:
        db.insert({"munt": market, "status": "MONITORING", "piek_koers": 0.0, "laagste_koers": 0.0})
        bestaande_trade = db.get(Trade.munt == market)

    huidige_status = bestaande_trade.get("status", "MONITORING")

    if actuele_waarde >= target_waarde and huidige_status == "MONITORING":
        db.update({"status": "PUMPING", "piek_koers": live_koers}, Trade.munt == market)
        send_telegram_message(
            f"🚀 *TRAILING PROFIT GEACTIVEERD* (Dalpot) 🚀\n\n"
            f"• Munt: *{coin}*\n"
            f"• Waarde: {euro(actuele_waarde)}",
            include_keyboard=True,
        )
        return

    if huidige_status != "PUMPING":
        return

    oude_piek = bestaande_trade.get("piek_koers") or live_koers
    if live_koers > oude_piek:
        db.update({"piek_koers": live_koers}, Trade.munt == market)
        oude_piek = live_koers

    trailing_pct = float(info.get("trailing_sell_pct", globale_trail))
    daling_pct = ((oude_piek - live_koers) / oude_piek) * 100 if oude_piek else 0.0

    if actuele_waarde < budget - (2 * trailing_pct / 100.0) * budget:
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)
        return

    if daling_pct < trailing_pct:
        return

    netto_opbrengst = round(actuele_waarde * (1.0 - fee), 2)
    netto_winst = round(netto_opbrengst - budget, 2)
    if netto_winst < MIN_WINST_EUR:
        # Trailing stop is al geraakt, maar de winst is te klein om voor te
        # verkopen. Terug naar MONITORING vanaf budget, alsof net gekocht —
        # anders blijft "Volgt de top" hangen met een allang achterhaalde piek.
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)
        return

    try:
        gevuld = plaats_marktorder("sell", market, aantal, "verkoop")
    except Exception as e:
        log_error(f"_dalpot_verkoop_check_munt.{coin}", e)
        _verkoop_pauze[coin] = time.time() + VERKOOP_MISLUKT_PAUZE
        return

    cache.invalideer()
    if not gevuld:
        log_info(f"Dalpot: verkoop van {coin} is niet gevuld, over {VERKOOP_MISLUKT_PAUZE // 60} minuten opnieuw.")
        _verkoop_pauze[coin] = time.time() + VERKOOP_MISLUKT_PAUZE
        return

    db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)

    log_trade(market, "verkoop", aantal, live_koers, netto_winst, netto_winst * fee, "dalpot-automatisch")
    registreer_dalpot_verkoop(coin, netto_winst, netto_opbrengst)

    verse_config = laad_config()
    verse_config.get("dalpot_coins", {}).pop(coin, None)
    bewaar_config(verse_config)

    send_telegram_message(
        f"💰 *DALPOT-MUNT VOLLEDIG VERKOCHT*:\n"
        f"• Van: *{coin}*\n"
        f"• Opbrengst: {euro(netto_opbrengst)}\n"
        f"• Winst: {euro(netto_winst)}\n"
        f"_Plekje is vrij, de dalpot zoekt meteen de nieuwste grootste daler._",
        include_keyboard=True,
    )

    threading.Thread(target=kies_dalpot_munten, daemon=True).start()


@met_lock
def check_portfolio():
    if not BOT_ACTIVE:
        return
    try:
        config = laad_config()
        fee = fee_fractie(config)
        globale_trail = float(config.get("global_settings", {}).get("trailing_sell_pct", 1.0))

        balans = cache.balans()
        tickers = cache.tickers()

        for coin, info in config.get("coins", {}).items():
            if not info.get("active", True):
                continue
            try:
                _verkoop_check_munt(coin, info, config, fee, globale_trail, balans, tickers,
                                     registreer_verkoop, "hoofd")
            except Exception as inner_e:
                log_error(f"check_portfolio.{coin}", inner_e)

        for coin, info in config.get("pot_coins", {}).items():
            if not info.get("active", True):
                continue
            try:
                _pot_verkoop_check_munt(coin, info, config, fee, globale_trail, balans, tickers)
            except Exception as inner_e:
                log_error(f"check_portfolio.pot.{coin}", inner_e)

        for coin, info in config.get("dalpot_coins", {}).items():
            if not info.get("active", True):
                continue
            try:
                _dalpot_verkoop_check_munt(coin, info, config, fee, globale_trail, balans, tickers)
            except Exception as inner_e:
                log_error(f"check_portfolio.dalpot.{coin}", inner_e)

    except Exception as e:
        log_error("check_portfolio", e)


@met_lock
def voer_handmatige_oogst_uit(coin_code):
    config = laad_config()
    coin = coin_code.replace("/EUR", "").strip().upper()
    coins = config.get("coins", {})

    if coin not in coins:
        send_telegram_message(f"❌ Munt *{coin}* staat niet in je configuratie.", include_keyboard=True)
        return

    budget = coins[coin].get("budget_eur", 250.0)
    market = f"{coin}/EUR"
    fee = fee_fractie(config)

    try:
        balans = cache.balans(force=True)
        tickers = cache.tickers(force=True)
        live_koers = koers_van(tickers, market)
        if live_koers is None:
            send_telegram_message(f"❌ Geen koers gevonden voor *{market}*.", include_keyboard=True)
            return

        aantal = balans["total"].get(coin, 0.0)
        waarde = aantal * live_koers
        bruto_winst = round(waarde - budget, 2)
        netto_winst = bruto_winst * (1.0 - fee)

        if netto_winst < MIN_WINST_EUR:
            send_telegram_message(
                f"⚠️ Netto winst op *{coin}* ({euro(netto_winst)}) is lager dan de drempel van {euro(MIN_WINST_EUR)}.",
                include_keyboard=True,
            )
            return

        aantal_verkopen = bereken_verkoop_aantal(market, bruto_winst, live_koers)
        if aantal_verkopen is None or aantal_verkopen >= aantal:
            send_telegram_message(
                f"⚠️ Order voor *{coin}* kan niet worden geplaatst. Bedrag te klein of saldo te laag.",
                include_keyboard=True,
            )
            return

        gevuld = plaats_marktorder("sell", market, aantal_verkopen, "verkoop")
        cache.invalideer()
        if not gevuld:
            send_telegram_message(
                f"⚠️ De verkooporder voor *{coin}* is niet gevuld. Er is niets verkocht en niets geboekt.",
                include_keyboard=True,
            )
            return
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == market)

        log_trade(market, "verkoop", aantal_verkopen, live_koers,
                  bruto_winst, bruto_winst * fee, "handmatig")
        apart = registreer_verkoop(coin, netto_winst, config)

        send_telegram_message(
            f"🥳 *WINST HANDMATIG GEKAPITALISEERD*!\n"
            f"• Munt: *{coin}*\n"
            f"• Bruto: {euro(bruto_winst)}\n"
            f"• Netto na fee: {euro(netto_winst)}\n"
            f"• Naar {actieve_reserve(config)} omgezet: {euro(apart)}",
            include_keyboard=True,
        )
    except Exception as e:
        log_error(f"handmatig_afromen.{coin}", e)
        send_telegram_message(f"🚨 Afromen van *{coin}* is mislukt. Zie bot_errors.log.", include_keyboard=True)


def _bepaal_aanvul_kandidaten(coins, config, state, balans, tickers):
    """
    Bepaalt welke munten in aanmerking komen om bijgevuld te worden en met
    welk bedrag. Gedeeld door de handmatige aanvulknop (hoofdlijst) en de
    automatische pot-aankoop. Houdt geen rekening met beschikbare cash, dat
    doet de aanroeper tijdens het kopen zelf.
    """
    gs = config.get("global_settings", {})
    lagen = gs.get("aanvul_lagen", [4.0, 10.0, 18.0])
    trailing_buy = float(gs.get("trailing_buy_pct", 1.0))
    wacht_op_bodem = gs.get("wacht_op_bodem", True)

    kandidaten = []
    overgeslagen = []

    for coin, info in coins.items():
        if not info.get("active", True):
            continue

        budget = info.get("budget_eur", 250.0)
        market = f"{coin}/EUR"
        live_koers = koers_van(tickers, market)
        if live_koers is None:
            continue

        waarde = balans["total"].get(coin, 0.0) * live_koers
        tekort = budget - waarde
        if tekort < MIN_ORDER_EUR or budget <= 0:
            continue

        tekort_pct = (tekort / budget) * 100.0

        # Laag 1 is nog niet bereikt: nog te dicht bij budget om bij te vullen
        bereikt = sum(1 for drempel in lagen if tekort_pct >= drempel)
        if bereikt == 0:
            continue

        # Bodem: niet eindeloos bijstorten in een munt die blijft zakken
        ingelegd, plafond, op_slot = inleg_bodem(coin, budget, config, state)
        if op_slot:
            overgeslagen.append(f"• *{coin}*: plafond bereikt ({euro(ingelegd, False)} ingelegd)")
            continue

        # Wachten tot de daling gestopt is
        if wacht_op_bodem:
            bodem = laagste_recent(market)
            if bodem and live_koers < bodem * (1.0 + trailing_buy / 100.0):
                overgeslagen.append(f"• *{coin}*: daalt nog, wacht op een bodem")
                continue

        deel = tekort * (bereikt / float(len(lagen)))
        ruimte = plafond - ingelegd
        kandidaten.append({
            "market": market,
            "munt": coin,
            "tekort": tekort,
            "ruimte": ruimte,
            "laag": bereikt,
            "van_lagen": len(lagen),
            "deel": min(deel, ruimte),
        })

    # Diepst gezakte munt eerst
    kandidaten.sort(key=lambda x: x["laag"], reverse=True)
    return kandidaten, overgeslagen


@met_lock
def voer_alles_aanvullen_uit():
    """
    Vult munten bij naar hun budget. Wordt NOOIT vanzelf gestart: alleen via de
    Telegram-knop of het dashboard. Drie remmen zitten erin:
      1. de reserve en de pot blijven onaangeroerd,
      2. bijvullen gebeurt in lagen, niet in een keer,
      3. per munt geldt een plafond op de totale inleg.
    """
    config = laad_config()
    coins = config.get("coins", {})
    fee = fee_fractie(config)

    try:
        balans = cache.balans(force=True)
        tickers = cache.tickers(force=True)
        state = laad_state()
        vrij_cash = balans["free"].get("EUR", 0.0)
        beschikbaar = handelscash(vrij_cash, state)

        if beschikbaar < MIN_ORDER_EUR:
            send_telegram_message(
                f"⚠️ *Te weinig vrije cash om mee te handelen.*\n"
                f"• Vrij: {euro(vrij_cash)}\n"
                f"• Waarvan pot: {euro(state.get('pot_cash_eur', 0.0))}\n"
                f"• Beschikbaar: {euro(beschikbaar)}",
                include_keyboard=True,
            )
            return

        kandidaten, overgeslagen = _bepaal_aanvul_kandidaten(coins, config, state, balans, tickers)

        if not kandidaten and not overgeslagen:
            send_telegram_message(
                "✅ *Geen munt staat ver genoeg onder budget om bij te vullen.*", include_keyboard=True
            )
            return

        regels = []
        totaal_besteed = 0.0

        for item in kandidaten:
            if beschikbaar < MIN_ORDER_EUR:
                regels.append("• _cash op, rest overgeslagen_")
                break

            # Compenseer de koopfee, anders landt de positie structureel onder budget
            gewenst = item["deel"] / (1.0 - fee) if fee < 1 else item["deel"]
            bedrag = round(min(gewenst, beschikbaar), 2)
            if bedrag < MIN_ORDER_EUR:
                continue

            try:
                if not plaats_marktorder("buy", item["market"], bedrag, "aankoop"):
                    regels.append(f"• *{item['munt']}*: ❌ order niet gevuld door Bitvavo")
                    continue
                log_trade(item["market"], "koop", None, None, bedrag, bedrag * fee, "aanvullen")
                registreer_koop(item["munt"], bedrag)
                regels.append(f"• *{item['munt']}*: +{euro(bedrag)} (laag {item['laag']} van {item['van_lagen']})")
                beschikbaar -= bedrag
                totaal_besteed += bedrag
                time.sleep(0.5)
            except Exception as order_e:
                log_error(f"aanvullen.{item['munt']}", order_e)
                regels.append(f"• *{item['munt']}*: ❌ order mislukt")

        cache.invalideer()

        bericht = "🛒 *AANVULLEN*\n\n"
        bericht += "\n".join(regels) if regels else "_Niets gekocht._"
        if overgeslagen:
            bericht += "\n\n⏭️ *Overgeslagen:*\n" + "\n".join(overgeslagen)
        bericht += (
            f"\n\n▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
            f"💰 Besteed: {euro(totaal_besteed)}\n"
            f"💵 Nog beschikbaar: {euro(beschikbaar)}\n"
            f"💎 Afgeroomd naar {reserve_naam()}: {euro(btc_reserve_waarde())}"
        )
        send_telegram_message(bericht, include_keyboard=True)

    except Exception as e:
        log_error("voer_alles_aanvullen_uit", e)
        send_telegram_message("🚨 *Aanvullen is mislukt.* Zie bot_errors.log.", include_keyboard=True)


# ---------------------------------------------------------------------------
# Pot: los potje waar de bot zelf mag kopen en verkopen
#
# Dit is de enige plek in de bot die uit zichzelf koopt, zonder dat jij op een
# knop drukt. Daarom zitten hier expliciete remmen in: een dagbudget, een
# afkoeltijd per munt, het bestaande inlegplafond (1,5x budget), en een
# noodstop die het kopen stilzet zodra de pot te diep onder de storting zakt.
# Munten in de pot mogen nooit ook in de hoofdlijst staan, anders zou de bot
# niet kunnen zien welk deel van een muntsaldo van wie is.
# ---------------------------------------------------------------------------

STANDAARD_POT_COOLDOWN_UUR = 6.0
STANDAARD_POT_MAX_PER_DAG = 25.0
STANDAARD_POT_NOODSTOP_PCT = 25.0
STANDAARD_POT_MIN_ORDER_EUR = 25.0   # Bitvavo zelf eist maar €5, dit is een eigen, hogere ondergrens
POT_MISLUKTE_KOOP_PAUZE = 600        # seconden wachten voor een munt na een mislukte of niet-gevulde bijkoop
_pot_koop_pauze = {}                 # munt -> tijdstip waarop opnieuw geprobeerd mag worden
VERKOOP_MISLUKT_PAUZE = 600          # seconden wachten voor een munt na een mislukte of niet-gevulde automatische verkoop
_verkoop_pauze = {}                  # munt -> tijdstip waarop een verkoop opnieuw geprobeerd mag worden


@met_lock
def check_pot_kopen():
    """Koopt automatisch bij in de pot. Raakt nooit de hoofdlijst of de reserve."""
    if not BOT_ACTIVE:
        return
    try:
        config = laad_config()
        pot_coins = {c: i for c, i in config.get("pot_coins", {}).items() if i.get("active", True)}
        if not pot_coins:
            return

        gs = config.get("global_settings", {})
        fee = fee_fractie(config)
        cooldown_uur = float(gs.get("pot_cooldown_uur", STANDAARD_POT_COOLDOWN_UUR))
        max_per_dag = float(gs.get("pot_max_per_dag", STANDAARD_POT_MAX_PER_DAG))
        noodstop_pct = float(gs.get("pot_noodstop_pct", STANDAARD_POT_NOODSTOP_PCT))
        # Eigen ondergrens per order, los van Bitvavo's eigen minimum van €5.
        # Hoger dan dat betekent: de pot wacht tot een dip groot genoeg is en
        # koopt dan in één keer minstens dit bedrag, in plaats van in kleine hapjes.
        min_order = float(gs.get("pot_min_order_eur", STANDAARD_POT_MIN_ORDER_EUR))

        state = laad_state()
        pot_cash = state.get("pot_cash_eur", 0.0)
        if pot_cash < min_order:
            return

        balans = cache.balans()
        tickers = cache.tickers()

        # Noodrem: pot te diep onder wat je erin hebt gestort, dan alleen nog verkopen
        pot_waarde_munten = sum(
            balans["total"].get(c, 0.0) * (koers_van(tickers, f"{c}/EUR") or 0.0)
            for c in pot_coins
        )
        pot_totaal = pot_cash + pot_waarde_munten
        pot_gestort = state.get("pot_gestort", 0.0)
        in_noodstop = pot_gestort > 0 and pot_totaal < pot_gestort * (1 - noodstop_pct / 100.0)

        if in_noodstop:
            if not state.get("pot_noodstop_actief"):
                state["pot_noodstop_actief"] = True
                bewaar_state(state)
                send_telegram_message(
                    f"🛑 *Pot-noodstop geactiveerd*\n\n"
                    f"Pot staat op {euro(pot_totaal)}, meer dan {noodstop_pct:.0f}% onder de "
                    f"{euro(pot_gestort)} die je erin hebt gestort.\n"
                    f"_Er wordt niet meer automatisch bijgekocht. Verkopen gaat gewoon door._",
                    include_keyboard=True,
                )
            return
        elif state.get("pot_noodstop_actief"):
            state["pot_noodstop_actief"] = False
            bewaar_state(state)
            send_telegram_message("✅ *Pot-noodstop opgeheven*, de pot koopt weer automatisch bij.", include_keyboard=True)

        # Dagbudget resetten bij een nieuwe dag, op Nederlandse middernacht,
        # niet op UTC-middernacht (dat was 2 uur te laat/vroeg, afhankelijk
        # van zomer- of wintertijd).
        vandaag = nu_nl().strftime("%Y-%m-%d")
        if state.get("pot_besteed_datum") != vandaag:
            state["pot_besteed_vandaag"] = 0.0
            state["pot_besteed_datum"] = vandaag
            bewaar_state(state)

        dagruimte = max(0.0, max_per_dag - state.get("pot_besteed_vandaag", 0.0))
        if dagruimte < min_order:
            return

        kandidaten, _ = _bepaal_aanvul_kandidaten(pot_coins, config, state, balans, tickers)
        if not kandidaten:
            return

        laatste_koop = state.get("pot_laatste_koop", {})
        beschikbaar = min(pot_cash, dagruimte)
        regels = []
        totaal_besteed = 0.0

        # Iets onder min_order nog toestaan (max 1 euro speling, maar nooit
        # onder Bitvavo's eigen minimum): de vorige aankoop in dezelfde ronde
        # kan door de fee een paar cent meer hebben gekost dan zijn eigen
        # doelbedrag, waardoor het restant net onder de drempel valt terwijl
        # het feitelijk gewoon "de laatste beschikbare cash" is. Zonder deze
        # marge blijft zo'n munt voor altijd hangen op "nog niet gekocht".
        ondergrens = max(MIN_ORDER_EUR, min_order - 1.0)

        for item in kandidaten:
            if beschikbaar < ondergrens:
                break

            coin = item["munt"]
            if time.time() < _pot_koop_pauze.get(coin, 0.0):
                continue
            laatst = laatste_koop.get(coin)
            if laatst:
                try:
                    verstreken_uur = (datetime.now(timezone.utc) - parse_tijd_utc(laatst)).total_seconds() / 3600.0
                except ValueError:
                    verstreken_uur = cooldown_uur
                if verstreken_uur < cooldown_uur:
                    continue

            # Wat de gelaagde logica zou kopen
            gewenst = item["deel"] / (1.0 - fee) if fee < 1 else item["deel"]
            # Nooit kleinere hapjes dan min_order, maar ook nooit verder dan het
            # echte tekort of het inlegplafond toestaan
            bovengrens = min(item["tekort"], item["ruimte"])
            bovengrens = bovengrens / (1.0 - fee) if fee < 1 else bovengrens
            gewenst = max(gewenst, min(min_order, bovengrens))
            bedrag = round(min(gewenst, beschikbaar), 2)
            if bedrag < ondergrens:
                continue

            try:
                if not plaats_marktorder("buy", item["market"], bedrag, "aankoop"):
                    log_info(f"Pot: bijkoop van {coin} is niet gevuld, even overgeslagen.")
                    _pot_koop_pauze[coin] = time.time() + POT_MISLUKTE_KOOP_PAUZE
                    continue
                log_trade(item["market"], "koop", None, None, bedrag, bedrag * fee, "pot-automatisch")
                registreer_pot_koop(coin, bedrag)
                regels.append(f"• *{coin}*: +{euro(bedrag)} (laag {item['laag']} van {item['van_lagen']})")
                beschikbaar -= bedrag
                totaal_besteed += bedrag
                time.sleep(0.5)
            except Exception as order_e:
                log_error(f"check_pot_kopen.{coin}", order_e)
                _pot_koop_pauze[coin] = time.time() + POT_MISLUKTE_KOOP_PAUZE

        if totaal_besteed > 0:
            cache.invalideer()
            state = laad_state()
            state["pot_besteed_vandaag"] = round(state.get("pot_besteed_vandaag", 0.0) + totaal_besteed, 2)
            bewaar_state(state)
            send_telegram_message(
                "🧪 *POT AUTOMATISCH BIJGEKOCHT*\n\n" + "\n".join(regels) +
                f"\n\n💰 Besteed: {euro(totaal_besteed)}\n"
                f"💵 Pot cash over: {euro(state.get('pot_cash_eur', 0.0))}",
                include_keyboard=True,
            )

    except Exception as e:
        log_error("check_pot_kopen", e)


@met_lock
def verzamel_pot():
    """
    Bouwt de pot-positielijst op, voor dashboard en Telegram. Zelfde reden als
    verzamel_posities(): TinyDB-reads moeten onder de lock, anders kan een
    lezing een net-in-uitvoering-zijnde schrijfactie als leeg bestand zien.

    Geeft per munt
    ook aan wanneer verkocht wordt (voortgang naar het doel, zelfde als de
    hoofdlijst) en wanneer er weer bijgekocht mag worden (afkoeltijd).
    """
    config = laad_config()
    pot_coins = config.get("pot_coins", {})
    gs = config.get("global_settings", {})
    fee = fee_fractie(config)
    cooldown_uur = float(gs.get("pot_cooldown_uur", STANDAARD_POT_COOLDOWN_UUR))

    state = laad_state()
    balans = cache.balans()
    tickers = cache.tickers()
    iconen = laad_iconen().get("iconen", {})
    geoogst_state = state.get("geoogst", {})
    laatste_koop = state.get("pot_laatste_koop", {})

    posities = []
    pot_waarde = 0.0
    for coin, info in pot_coins.items():
        market = f"{coin}/EUR"
        koers = koers_van(tickers, market) or 0.0
        aantal = balans["total"].get(coin, 0.0)
        waarde = aantal * koers
        pot_waarde += waarde
        budget = info.get("budget_eur", 0.0)
        tp_pct = info.get("take_profit_pct", 4.0)
        winst = waarde - budget

        netto_doel, doel_eur = bereken_doel(budget, tp_pct, fee)
        voortgang = (winst / doel_eur) * 100 if doel_eur > 0 else 0

        bestaande_trade = db.get(Trade.munt == market)
        status = bestaande_trade.get("status", "MONITORING") if bestaande_trade else "MONITORING"

        ingelegd, plafond, op_slot = inleg_bodem(coin, budget, config, state)

        # Wanneer mag deze munt weer bijgekocht worden (afkoeltijd)
        kan_kopen_om = None
        laatst = laatste_koop.get(coin)
        if laatst:
            try:
                vrij_vanaf = parse_tijd_utc(laatst) + timedelta(hours=cooldown_uur)
                if vrij_vanaf > datetime.now(timezone.utc):
                    kan_kopen_om = vrij_vanaf.astimezone(NL_TZ).strftime("%H:%M")
            except ValueError:
                pass

        posities.append({
            "coin": coin,
            "icoon": iconen.get(coin, ""),
            "koers": koers,
            "waarde": waarde,
            "budget": budget,
            "ingelegd": round(ingelegd, 2),
            "geoogst": round(geoogst_state.get(coin, 0.0), 2),
            "winst": winst,
            "rendement": (winst / budget * 100) if budget > 0 else 0,
            "doel_eur": doel_eur,
            "voortgang": voortgang,
            "status": status,
            "op_slot": op_slot,
            "kan_kopen_om": kan_kopen_om,
            "actief": info.get("active", True),
        })

    posities.sort(key=lambda x: -x["waarde"])
    pot_cash = state.get("pot_cash_eur", 0.0)
    return {
        "cash": pot_cash,
        "belegd": pot_waarde,
        "totaal": pot_cash + pot_waarde,
        "gestort": state.get("pot_gestort", 0.0),
        "noodstop": bool(state.get("pot_noodstop_actief", False)),
        "posities": posities,
    }


@met_lock
def verzamel_dalpot():
    """
    Zelfde als verzamel_pot(), maar voor de dalpot. Geen laagsgewijs
    bijkopen of afkoeltijd hier (de dalpot koopt altijd in één keer het
    volle budget), dus "ingelegd" is simpelweg gelijk aan "budget" en
    "kan_kopen_om" bestaat niet.
    """
    config = laad_config()
    dalpot_coins = config.get("dalpot_coins", {})
    fee = fee_fractie(config)

    state = laad_state()
    balans = cache.balans()
    tickers = cache.tickers()
    iconen = laad_iconen().get("iconen", {})
    geoogst_state = state.get("geoogst", {})

    posities = []
    dalpot_waarde = 0.0
    for coin, info in dalpot_coins.items():
        market = f"{coin}/EUR"
        koers = koers_van(tickers, market) or 0.0
        aantal = balans["total"].get(coin, 0.0)
        waarde = aantal * koers
        dalpot_waarde += waarde
        budget = info.get("budget_eur", 0.0)
        tp_pct = info.get("take_profit_pct", 10.0)
        winst = waarde - budget

        netto_doel, doel_eur = bereken_doel(budget, tp_pct, fee)
        voortgang = (winst / doel_eur) * 100 if doel_eur > 0 else 0

        bestaande_trade = db.get(Trade.munt == market)
        status = bestaande_trade.get("status", "MONITORING") if bestaande_trade else "MONITORING"

        posities.append({
            "coin": coin,
            "icoon": iconen.get(coin, ""),
            "koers": koers,
            "waarde": waarde,
            "budget": budget,
            "ingelegd": round(budget, 2),
            "geoogst": round(geoogst_state.get(coin, 0.0), 2),
            "winst": winst,
            "rendement": (winst / budget * 100) if budget > 0 else 0,
            "doel_eur": doel_eur,
            "voortgang": voortgang,
            "status": status,
            "op_slot": False,
            "kan_kopen_om": None,
            "actief": info.get("active", True),
        })

    posities.sort(key=lambda x: -x["waarde"])
    dalpot_cash = state.get("dalpot_cash_eur", 0.0)
    return {
        "cash": dalpot_cash,
        "belegd": dalpot_waarde,
        "totaal": dalpot_cash + dalpot_waarde,
        "gestort": state.get("dalpot_gestort", 0.0),
        "noodstop": bool(state.get("dalpot_noodstop_actief", False)),
        "posities": posities,
    }


STANDAARD_POT_MAX_MUNTEN = 2
STANDAARD_POT_MIN_VOLUME_EUR = 1_000_000.0   # 24u omzet, tegen dunne/illiquide munten
STANDAARD_POT_ATR_MIN = 3.0                  # dagrange, tegen munten die amper bewegen
STANDAARD_POT_ATR_MAX = 25.0                 # dagrange, tegen extreem wilde munten
STANDAARD_POT_WINSTDOEL_EUR = 5.50           # winstdoel per pot-munt in euro's, niet in %
STANDAARD_POT_TRAILING_PCT = 1.0             # trailing stop voor pot-munten, vast (niet volatiliteit-geschaald)

# Dalpot: omgekeerde pot. Kiest de munt met de grootste 24u-daling, koopt
# in één keer het volle budget, laat 'm liggen als hij verder zakt (geen
# stop-loss), verkoopt de hele positie zodra het winstdoel + trailing
# geraakt wordt. Bewust geen liquiditeitseis — op verzoek van de gebruiker,
# die het risico van dun-verhandelde munten hierbij accepteert.
STANDAARD_DALPOT_MAX_MUNTEN = 3
STANDAARD_DALPOT_WINSTDOEL_EUR = 10.0
STANDAARD_DALPOT_TRAILING_PCT = 1.0
STANDAARD_DALPOT_BUDGET_PER_MUNT = 100.0
STANDAARD_DALPOT_UITGESLOTEN = ["BTC", "ETH", "USDT", "USDC", "DAI", "EURC"]
STANDAARD_DALPOT_NOODSTOP_PCT = 25.0
DALPOT_MAX_MISLUKTE_KOPEN = 8    # per keuzerun, tegen eindeloos proberen op dunne munten
STANDAARD_DALPOT_HERKOOP_UUR = 24.0   # een verkochte of verwijderde munt wordt zo lang niet opnieuw gekozen


def kies_pot_munten(handmatig=False):
    """
    Kiest zelf nieuwe munten voor de pot, als daar ruimte voor is.

    Filtert in twee stappen, van goedkoop naar duur:
      1. genoeg 24u-omzet (tegen dunne, makkelijk te manipuleren munten),
      2. dagrange over de laatste 14 dagen binnen een bandbreedte (niet dood,
         niet compleet wild) — dezelfde meting als de volatiliteitsschaal.
    Wat overblijft wordt op omzet gerangschikt (hoger = gevestigder) en de
    beste kandidaten vullen de vrije plekken tot het ingestelde maximum.

    Dit is heuristische filtering, geen beleggingsadvies: het zegt niets over
    of een munt goed gaat presteren, alleen dat hij liquide genoeg is en
    genoeg beweegt om iets te kunnen oogsten.

    handmatig=True (vanuit de Telegram-knop) zorgt dat er altijd een bericht
    terugkomt, ook als er niets te kiezen viel — anders lijkt de knop niets
    te doen.

    Net als ververs_parameters(): het trage deel (tickers doorzoeken, per
    kandidaat een netwerkaanvraag voor de dagrange, met pauze ertussen) gaat
    BUITEN de handelslock. Dat kon eerder 10-20 seconden duren, en zolang de
    lock daarvoor vastzat stonden het dashboard en elke Telegram-actie stil.
    Alleen het wegschrijven en de daadwerkelijke aankoop aan het eind gaan
    nog onder de lock.
    """
    if not BOT_ACTIVE:
        return
    try:
        config = laad_config()
        gs = config.get("global_settings", {})
        if not gs.get("pot_auto_kiezen", True):
            if handmatig:
                send_telegram_message(
                    "ℹ️ `pot_auto_kiezen` staat uit in de instellingen. Zet die aan, of voeg zelf een munt toe.",
                    custom_keyboard=POT_KEYBOARD,
                )
            return

        pot_coins = config.get("pot_coins", {})
        max_munten = int(gs.get("pot_max_munten", STANDAARD_POT_MAX_MUNTEN))
        vrije_plekken = max_munten - len(pot_coins)
        if vrije_plekken <= 0:
            if handmatig:
                send_telegram_message(
                    f"ℹ️ De pot heeft al {len(pot_coins)} van de {max_munten} munten. "
                    f"Verwijder er eerst een, of verhoog `pot_max_munten`.",
                    custom_keyboard=POT_KEYBOARD,
                )
            return

        state = laad_state()
        pot_cash = state.get("pot_cash_eur", 0.0)
        min_order = float(gs.get("pot_min_order_eur", STANDAARD_POT_MIN_ORDER_EUR))
        if pot_cash < min_order:
            if handmatig:
                send_telegram_message(
                    f"ℹ️ Te weinig pot-cash: {euro(pot_cash)}, minimaal {euro(min_order)} nodig per munt.",
                    custom_keyboard=POT_KEYBOARD,
                )
            return

        # Vast budget per munt (standaard hetzelfde als de minimum orderomvang),
        # niet verdeeld over de pot-cash. Met max_munten=2 en €25 per munt is
        # dat dus 2x €25, ongeacht hoeveel cash er verder in de pot zit.
        budget_per_munt = float(gs.get("pot_budget_per_munt", min_order))
        winstdoel_eur = float(gs.get("pot_winstdoel_eur", STANDAARD_POT_WINSTDOEL_EUR))
        trailing_pct = float(gs.get("pot_trailing_pct", STANDAARD_POT_TRAILING_PCT))
        min_volume = float(gs.get("pot_min_volume_eur", STANDAARD_POT_MIN_VOLUME_EUR))
        atr_min = float(gs.get("pot_atr_min", STANDAARD_POT_ATR_MIN))
        atr_max = float(gs.get("pot_atr_max", STANDAARD_POT_ATR_MAX))

        hoofdlijst = set(config.get("coins", {}).keys())
        potlijst = set(pot_coins.keys())
        uitgesloten = set(gs.get("pot_uitgesloten", []))

        balans = cache.balans()
        tickers = cache.tickers()
        ruw = []
        for market, ticker in tickers.items():
            if not market.endswith("/EUR"):
                continue
            coin = market[:-4]
            if coin in hoofdlijst or coin in potlijst or coin in uitgesloten or coin == "EUR" or is_reserve_munt(coin):
                continue

            # Munten die je al bezit buiten de bot om (handmatige trades,
            # oude posities) niet kiezen. Anders telt de pot je hele
            # bestaande saldo mee als "zijn" positie en kloppen de cijfers
            # niet meer — precies het euro['SOL raar']-probleem van eerder,
            # maar dan andersom.
            bestaand_saldo = balans["total"].get(coin, 0.0)
            if bestaand_saldo > 0:
                live_koers = ticker.get("last") or 0.0
                if bestaand_saldo * live_koers > 1.0:
                    continue

            volume = ticker.get("quoteVolume") or 0.0
            if volume < min_volume:
                continue
            ruw.append((coin, market, volume))

        # Meeste omzet eerst checken, scheelt onnodige ohlcv-aanvragen verderop
        ruw.sort(key=lambda x: x[2], reverse=True)

        gekozen = []
        for coin, market, volume in ruw:
            if len(gekozen) >= vrije_plekken:
                break
            atr = meet_volatiliteit(market)
            time.sleep(0.3)
            if atr is None or not (atr_min <= atr <= atr_max):
                continue
            gekozen.append((coin, market, volume, atr))

        if not gekozen:
            if handmatig:
                send_telegram_message(
                    f"ℹ️ Geen munt gevonden die aan de eisen voldoet "
                    f"(min. {euro(min_volume, False)} 24u omzet, dagrange {atr_min:.0f}-{atr_max:.0f}%, "
                    f"niet al in bezit). Probeer het later nog eens.",
                    custom_keyboard=POT_KEYBOARD,
                )
            return

        # Alleen dit deel — wegschrijven en de daadwerkelijke aankoop — onder
        # de lock. Vers inlezen en de vrije plekken opnieuw tellen, want
        # tijdens het trage (ongelockte) zoeken hierboven kan er ondertussen
        # via Telegram of de website ook al een munt bij gekomen zijn.
        regels = []
        with handel_lock:
            verse_config = laad_config()
            fee = fee_fractie(verse_config)
            cash_over = laad_state().get("pot_cash_eur", 0.0)
            vrije_plekken_nu = max_munten - len(verse_config["pot_coins"])

            for coin, market, volume, atr in gekozen:
                if vrije_plekken_nu <= 0:
                    break
                if coin in verse_config["coins"] or coin in verse_config["pot_coins"]:
                    continue
                verse_config["pot_coins"][coin] = {
                    "active": True, "budget_eur": round(budget_per_munt, 2),
                    "take_profit_pct": round(winstdoel_eur / budget_per_munt * 100, 2) if budget_per_munt else 7.33,
                    "trailing_sell_pct": trailing_pct,
                    "vast_doel": True,
                }
                bewaar_config(verse_config)
                vrije_plekken_nu -= 1

                # Meteen voor het volle budget kopen in plaats van te wachten op
                # een dip: bij deze opzet wordt een munt toch in één keer
                # helemaal verkocht zodra hij zijn winstdoel haalt, dus laagsgewijs
                # instappen (zoals de hoofdlijst doet) voegt hier niets toe en
                # kost alleen tijd waarin de pot met werkloze cash zit.
                bedrag = round(min(budget_per_munt, cash_over), 2)
                kocht_tekst = ""
                if bedrag >= MIN_ORDER_EUR:
                    try:
                        gevuld = plaats_marktorder("buy", market, bedrag, "aankoop")
                        cache.invalideer()
                        if gevuld:
                            log_trade(market, "koop", None, None, bedrag, bedrag * fee, "pot-automatisch")
                            registreer_pot_koop(coin, bedrag)
                            cash_over = round(cash_over - bedrag, 2)
                            kocht_tekst = f", meteen gekocht voor {euro(bedrag)}"
                        else:
                            kocht_tekst = ", order niet gevuld (de pot koopt later zelf bij)"
                    except Exception as koop_e:
                        log_error(f"kies_pot_munten.koop.{coin}", koop_e)

                regels.append(
                    f"• *{coin}*: budget {euro(budget_per_munt)}{kocht_tekst}, "
                    f"24u omzet {euro(volume, False)}, dagrange {atr:.1f}%"
                )

        if regels:
            threading.Thread(target=ververs_iconen, daemon=True).start()
            send_telegram_message(
                "🧪 *POT KOOS ZELF NIEUWE MUNTEN*\n\n" + "\n".join(regels) +
                f"\n\n_Gekozen op 24u-omzet (min. {euro(min_volume, False)}) en dagbeweging "
                f"({atr_min:.0f}-{atr_max:.0f}%). Geen garantie voor de toekomst.\n"
                f"Zet `pot_auto_kiezen` op false in de config om dit uit te schakelen._",
                include_keyboard=True,
            )

    except Exception as e:
        log_error("kies_pot_munten", e)


def kies_dalpot_munten(handmatig=False):
    """
    Kiest zelf nieuwe munten voor de dalpot: de munt(en) met de grootste
    24u-koersdaling. Geen liquiditeits- of volatiliteitsfilter (bewust, op
    verzoek) — alleen uitsluiting van munten die al in de hoofdlijst, de
    pot, de dalpot zelf staan, op de uitsluitlijst staan, of al buiten de
    bot om in bezit zijn.

    Simpeler en sneller dan kies_pot_munten(): geen aparte netwerkaanvraag
    per kandidaat nodig, de 24u-procentuele verandering staat al in de
    normale tickerdata.
    """
    if not BOT_ACTIVE:
        return
    try:
        config = laad_config()
        gs = config.get("global_settings", {})
        if not gs.get("dalpot_auto_kiezen", True):
            return

        dalpot_coins = config.get("dalpot_coins", {})
        max_munten = int(gs.get("dalpot_max_munten", STANDAARD_DALPOT_MAX_MUNTEN))
        vrije_plekken = max_munten - len(dalpot_coins)
        if vrije_plekken <= 0:
            if handmatig:
                send_telegram_message(
                    f"ℹ️ De dalpot heeft al {len(dalpot_coins)} van de {max_munten} munten. "
                    f"Verwijder er eerst een, of verhoog `dalpot_max_munten`.",
                    include_keyboard=True,
                )
            return

        state = laad_state()
        dalpot_cash = state.get("dalpot_cash_eur", 0.0)
        budget_per_munt = float(gs.get("dalpot_budget_per_munt", STANDAARD_DALPOT_BUDGET_PER_MUNT))
        # Alleen kopen met het volle budget: een deelaankoop zou toch als
        # "budget" geboekt worden en dan direct een nep-verlies tonen.
        if dalpot_cash < budget_per_munt:
            if handmatig:
                send_telegram_message(
                    f"ℹ️ Te weinig dalpot-cash: {euro(dalpot_cash)} (nodig: {euro(budget_per_munt)}).",
                    include_keyboard=True,
                )
            return

        winstdoel_eur = float(gs.get("dalpot_winstdoel_eur", STANDAARD_DALPOT_WINSTDOEL_EUR))
        trailing_pct = float(gs.get("dalpot_trailing_pct", STANDAARD_DALPOT_TRAILING_PCT))

        hoofdlijst = set(config.get("coins", {}).keys())
        potlijst = set(config.get("pot_coins", {}).keys())
        dalpotlijst = set(dalpot_coins.keys())
        uitgesloten = set(gs.get("dalpot_uitgesloten", STANDAARD_DALPOT_UITGESLOTEN))

        balans = cache.balans()
        tickers = cache.tickers()

        # Noodrem: dalpot te diep onder wat je erin hebt gestort, dan alleen
        # nog verkopen (dat loopt via check_portfolio, hier niet aangeraakt),
        # geen nieuwe munten meer kopen. Zelfde patroon als check_pot_kopen().
        noodstop_pct = float(gs.get("dalpot_noodstop_pct", STANDAARD_DALPOT_NOODSTOP_PCT))
        dalpot_waarde_munten = sum(
            balans["total"].get(c, 0.0) * (koers_van(tickers, f"{c}/EUR") or 0.0)
            for c in dalpotlijst
        )
        dalpot_totaal = dalpot_cash + dalpot_waarde_munten
        dalpot_gestort = state.get("dalpot_gestort", 0.0)
        in_noodstop = dalpot_gestort > 0 and dalpot_totaal < dalpot_gestort * (1 - noodstop_pct / 100.0)

        if in_noodstop:
            if not state.get("dalpot_noodstop_actief"):
                state["dalpot_noodstop_actief"] = True
                bewaar_state(state)
                send_telegram_message(
                    f"🛑 *Dalpot-noodstop geactiveerd*\n\n"
                    f"Dalpot staat op {euro(dalpot_totaal)}, meer dan {noodstop_pct:.0f}% onder de "
                    f"{euro(dalpot_gestort)} die je erin hebt gestort.\n"
                    f"_Er worden geen nieuwe munten meer gekocht. Bestaande posities lopen gewoon door._",
                    include_keyboard=True,
                )
            elif handmatig:
                send_telegram_message(
                    f"🛑 Dalpot-noodstop is actief (staat {noodstop_pct:.0f}%+ onder storting), "
                    f"er wordt niet gekocht.", include_keyboard=True,
                )
            return
        elif state.get("dalpot_noodstop_actief"):
            state["dalpot_noodstop_actief"] = False
            bewaar_state(state)
            send_telegram_message("✅ *Dalpot-noodstop opgeheven*, de dalpot kiest weer automatisch nieuwe munten.", include_keyboard=True)

        herkoop_uur = float(gs.get("dalpot_herkoop_uur", STANDAARD_DALPOT_HERKOOP_UUR))
        laatst_verkocht = state.get("dalpot_laatst_verkocht", {})

        kandidaten = []
        for market, ticker in tickers.items():
            if not market.endswith("/EUR"):
                continue
            coin = market[:-4]
            if (coin in hoofdlijst or coin in potlijst or coin in dalpotlijst or coin in uitgesloten
                    or coin == "EUR" or is_reserve_munt(coin)):
                continue

            # Afkoelperiode: een net verkochte munt is vaak nog steeds de
            # grootste daler en zou meteen weer gekozen worden (dubbele fee).
            if coin in laatst_verkocht and _in_afkoelperiode(laatst_verkocht[coin], herkoop_uur):
                continue

            bestaand_saldo = balans["total"].get(coin, 0.0)
            if bestaand_saldo > 0:
                live_koers = ticker.get("last") or 0.0
                if bestaand_saldo * live_koers > 1.0:
                    continue

            verandering_pct = ticker.get("percentage")
            if verandering_pct is None:
                continue
            kandidaten.append((coin, market, verandering_pct))

        # Grootste daling eerst (meest negatieve percentage)
        kandidaten.sort(key=lambda x: x[2])

        if not kandidaten:
            if handmatig:
                send_telegram_message("ℹ️ Geen geschikte munt gevonden. Probeer het later nog eens.", include_keyboard=True)
            return

        regels = []
        mislukt = []
        with handel_lock:
            verse_config = laad_config()
            fee = fee_fractie(verse_config)
            cash_over = laad_state().get("dalpot_cash_eur", 0.0)
            vrije_plekken_nu = max_munten - len(verse_config["dalpot_coins"])

            for coin, market, verandering_pct in kandidaten:
                if vrije_plekken_nu <= 0 or cash_over < budget_per_munt:
                    break
                if len(mislukt) >= DALPOT_MAX_MISLUKTE_KOPEN:
                    break
                if coin in verse_config["coins"] or coin in verse_config["pot_coins"] or coin in verse_config["dalpot_coins"]:
                    continue

                # Eerst kopen, pas daarna boeken: een dunne munt kan door Bitvavo
                # geannuleerd worden, dan gaat de bot gewoon naar de volgende.
                bedrag = round(budget_per_munt, 2)
                try:
                    gevuld = plaats_marktorder("buy", market, bedrag, "aankoop")
                except Exception as koop_e:
                    log_error(f"kies_dalpot_munten.koop.{coin}", koop_e)
                    mislukt.append(coin)
                    continue
                cache.invalideer()
                if not gevuld:
                    log_info(f"Dalpot: order voor {coin} is niet gevuld, volgende kandidaat.")
                    mislukt.append(coin)
                    continue

                log_trade(market, "koop", None, None, bedrag, bedrag * fee, "dalpot-automatisch")
                registreer_dalpot_koop(coin, bedrag)
                verse_config["dalpot_coins"][coin] = {
                    "active": True, "budget_eur": round(budget_per_munt, 2),
                    "take_profit_pct": round(winstdoel_eur / budget_per_munt * 100, 2) if budget_per_munt else 10.0,
                    "trailing_sell_pct": trailing_pct,
                    "vast_doel": True,
                }
                bewaar_config(verse_config)
                cash_over = round(cash_over - bedrag, 2)
                vrije_plekken_nu -= 1
                regels.append(f"• *{coin}*: gekocht voor {euro(bedrag)}, 24u: {verandering_pct:.1f}%")

        overgeslagen = f"\n_Overgeslagen (order niet gevuld): {', '.join(mislukt)}_" if mislukt else ""
        if regels:
            threading.Thread(target=ververs_iconen, daemon=True).start()
            send_telegram_message(
                "📉 *DALPOT KOOS ZELF NIEUWE MUNTEN*\n\n" + "\n".join(regels) + overgeslagen +
                f"\n\n_Gekozen op grootste 24u-daling, geen liquiditeitseis. Geen garantie voor de toekomst._",
                include_keyboard=True,
            )
        elif handmatig and mislukt:
            send_telegram_message(
                f"ℹ️ Geen munt gekocht: de orders voor {', '.join(mislukt)} zijn niet gevuld "
                f"(waarschijnlijk een te dun orderboek).", include_keyboard=True,
            )

    except Exception as e:
        log_error("kies_dalpot_munten", e)


# ---------------------------------------------------------------------------
# Muntbeheer
# ---------------------------------------------------------------------------

@met_lock
def verwerk_munt_toevoegen(invoer_tekst):
    try:
        delen = invoer_tekst.strip().split()
        if len(delen) != 2:
            send_telegram_message("⚠️ Ongeldige invoer. Typ bijvoorbeeld `SOL 250`.", include_keyboard=True)
            return

        coin = delen[0].upper().replace("/EUR", "")
        nieuw_budget = float(delen[1].replace(",", ".").replace("€", ""))
        market = f"{coin}/EUR"

        # Controle tegen de echte marktlijst, zodat een typefout geen spookmunt oplevert
        if not markt_bestaat(market):
            send_telegram_message(
                f"❌ Markt *{market}* bestaat niet op Bitvavo. Controleer de afkorting.", include_keyboard=True
            )
            return

        if nieuw_budget < MIN_ORDER_EUR:
            send_telegram_message(
                f"⚠️ Budget moet minimaal {euro(MIN_ORDER_EUR)} zijn.", include_keyboard=True
            )
            return

        if is_reserve_munt(coin):
            send_telegram_message(RESERVE_GEWEIGERD_TEKST.format(munt=coin), include_keyboard=True)
            return

        config = laad_config()
        coins = config["coins"]

        if coin in config["pot_coins"]:
            send_telegram_message(
                f"❌ *{coin}* staat al in de pot. Een munt kan niet in beide lijsten staan, "
                f"want Bitvavo geeft maar één saldo per munt terug.",
                include_keyboard=True,
            )
            return

        gs = config.get("global_settings", {})
        winstdoel_eur = float(gs.get("hoofdlijst_winstdoel_eur", STANDAARD_HOOFDLIJST_WINSTDOEL_EUR))
        tp_pct = round(winstdoel_eur / nieuw_budget * 100, 2) if nieuw_budget else 7.33
        coins[coin] = {
            "active": True,
            "budget_eur": nieuw_budget,
            "take_profit_pct": tp_pct,
            "trailing_sell_pct": 1.0,
            "vast_doel": True,
        }
        bewaar_config(config)
        # Logo van de nieuwe munt op de achtergrond ophalen
        threading.Thread(target=ververs_iconen, daemon=True).start()
        send_telegram_message(
            f"🎉 *Munt {coin} succesvol toegevoegd!*\n"
            f"• Budget: {euro(nieuw_budget)}\n"
            f"• Winstdoel: {euro(winstdoel_eur)} (vast, 1% trailing)",
            include_keyboard=True,
        )
    except ValueError:
        send_telegram_message("⚠️ Het budget is geen geldig getal. Typ bijvoorbeeld `SOL 250`.", include_keyboard=True)
    except Exception as e:
        log_error("verwerk_munt_toevoegen", e)
        send_telegram_message("🚨 Fout bij toevoegen. Controleer de invoer.", include_keyboard=True)


@met_lock
def verwerk_munt_verwijderen(coin_code):
    try:
        coin = coin_code.replace("/EUR", "").strip().upper()
        config = laad_config()
        coins = config["coins"]

        if coin in coins:
            del coins[coin]
            bewaar_config(config)
            db.remove(Trade.munt == f"{coin}/EUR")
            send_telegram_message(
                f"🗑️ *Munt {coin} is verwijderd uit de monitoring!*\n\n"
                f"_Let op: eventuele munten blijven gewoon in je wallet staan._",
                include_keyboard=True,
            )
        else:
            send_telegram_message(f"❌ Munt *{coin}* staat niet in de lijst.", include_keyboard=True)
    except Exception as e:
        log_error("verwerk_munt_verwijderen", e)
        send_telegram_message("🚨 Fout bij verwijderen.", include_keyboard=True)


@met_lock
def verwerk_budget_wijziging(invoer_tekst):
    try:
        delen = invoer_tekst.strip().split()
        if len(delen) != 2:
            send_telegram_message("⚠️ Ongeldige invoer. Typ bijvoorbeeld `INJ 250`.", include_keyboard=True)
            return

        coin = delen[0].upper().replace("/EUR", "")
        nieuw_budget = float(delen[1].replace(",", ".").replace("€", ""))

        config = laad_config()
        coins = config["coins"]

        if coin not in coins:
            send_telegram_message(
                f"❌ Munt {coin} bestaat nog niet. Gebruik eerst 'Munt Toevoegen'.", include_keyboard=True
            )
            return

        coins[coin]["budget_eur"] = nieuw_budget
        bewaar_config(config)
        # Status resetten, anders loopt een oude PUMPING-status door op het nieuwe budget
        db.update({"status": "MONITORING", "piek_koers": 0.0}, Trade.munt == f"{coin}/EUR")
        send_telegram_message(
            f"✅ *Budget voor {coin} aangepast naar {euro(nieuw_budget)}!*", include_keyboard=True
        )
    except ValueError:
        send_telegram_message("⚠️ Het budget is geen geldig getal.", include_keyboard=True)
    except Exception as e:
        log_error("verwerk_budget_wijziging", e)
        send_telegram_message("🚨 Fout bij wijzigen van het budget.", include_keyboard=True)


@met_lock
def verwerk_pot_munt_toevoegen(invoer_tekst):
    try:
        delen = invoer_tekst.strip().split()
        if len(delen) != 2:
            send_telegram_message("⚠️ Ongeldige invoer. Typ bijvoorbeeld `XRP 25`.", custom_keyboard=TERUG_KEYBOARD)
            return

        coin = delen[0].upper().replace("/EUR", "")
        nieuw_budget = float(delen[1].replace(",", ".").replace("€", ""))
        market = f"{coin}/EUR"

        if not markt_bestaat(market):
            send_telegram_message(f"❌ Markt *{market}* bestaat niet op Bitvavo.", custom_keyboard=POT_KEYBOARD)
            return
        if is_reserve_munt(coin):
            send_telegram_message(RESERVE_GEWEIGERD_TEKST.format(munt=coin), custom_keyboard=POT_KEYBOARD)
            return
        if nieuw_budget < MIN_ORDER_EUR:
            send_telegram_message(f"⚠️ Budget moet minimaal {euro(MIN_ORDER_EUR)} zijn.", custom_keyboard=POT_KEYBOARD)
            return

        config = laad_config()
        if coin in config["coins"]:
            send_telegram_message(
                f"❌ *{coin}* staat al in je hoofdlijst. Een munt kan niet in beide lijsten staan, "
                f"want Bitvavo geeft maar één saldo per munt terug.",
                custom_keyboard=POT_KEYBOARD,
            )
            return
        if coin in config["pot_coins"]:
            send_telegram_message(f"ℹ️ *{coin}* staat al in de pot.", custom_keyboard=POT_KEYBOARD)
            return

        gs = config.get("global_settings", {})
        winstdoel_eur = float(gs.get("pot_winstdoel_eur", STANDAARD_POT_WINSTDOEL_EUR))
        trailing_pct = float(gs.get("pot_trailing_pct", STANDAARD_POT_TRAILING_PCT))
        config["pot_coins"][coin] = {
            "active": True, "budget_eur": nieuw_budget,
            "take_profit_pct": round(winstdoel_eur / nieuw_budget * 100, 2) if nieuw_budget else 7.33,
            "trailing_sell_pct": trailing_pct,
            "vast_doel": True,
        }
        bewaar_config(config)
        threading.Thread(target=ververs_iconen, daemon=True).start()

        # Meteen kopen, net als wanneer de bot zelf een munt kiest — anders
        # blijft deze munt hangen op het trage laagsgewijze systeem met
        # afkoeltijd, en duurt het (te) lang voor het volle budget erin zit.
        state = laad_state()
        pot_cash = state.get("pot_cash_eur", 0.0)
        bedrag = round(min(nieuw_budget, pot_cash), 2)
        kocht_tekst = ""
        if bedrag >= MIN_ORDER_EUR:
            fee = fee_fractie(config)
            try:
                gevuld = plaats_marktorder("buy", market, bedrag, "aankoop")
                cache.invalideer()
                if gevuld:
                    log_trade(market, "koop", None, None, bedrag, bedrag * fee, "pot-automatisch")
                    registreer_pot_koop(coin, bedrag)
                    kocht_tekst = f"• Meteen gekocht: {euro(bedrag)}\n"
                else:
                    kocht_tekst = "• De order is niet gevuld (te dun orderboek?), de pot koopt later zelf bij.\n"
            except Exception as koop_e:
                log_error(f"verwerk_pot_munt_toevoegen.koop.{coin}", koop_e)
                kocht_tekst = "• Meteen kopen is mislukt, probeer het later handmatig.\n"
        else:
            kocht_tekst = "• Te weinig pot-cash om meteen te kopen, wacht op een volgende storting.\n"

        send_telegram_message(
            f"🧪 *{coin} toegevoegd aan de pot!*\n"
            f"• Budget: {euro(nieuw_budget)}\n"
            f"{kocht_tekst}\n"
            f"_De bot mag deze munt zelf kopen en verkopen, uitsluitend met pot-cash._",
            custom_keyboard=POT_KEYBOARD,
        )
    except ValueError:
        send_telegram_message("⚠️ Het budget is geen geldig getal.", custom_keyboard=POT_KEYBOARD)
    except Exception as e:
        log_error("verwerk_pot_munt_toevoegen", e)
        send_telegram_message("🚨 Fout bij toevoegen aan de pot.", custom_keyboard=POT_KEYBOARD)


@met_lock
def verwerk_pot_munt_verwijderen(coin_code):
    """
    Verwijdert een munt uit de pot — en verkoopt 'm daarbij ook echt, zodat
    het geld altijd in de pot blijft (terug de pot-cash in) in plaats van dat
    je zelf op Bitvavo moet verkopen en de waarde onzichtbaar wordt voor
    "Totale waarde". Alleen als er geen noemenswaardige waarde meer is
    (al 0, of al eerder buiten de bot om verkocht) slaat de verkoopstap over.
    """
    try:
        coin = coin_code.replace("/EUR", "").strip().upper()
        config = laad_config()
        if coin not in config["pot_coins"]:
            send_telegram_message(f"❌ *{coin}* staat niet in de pot.", custom_keyboard=POT_KEYBOARD)
            return

        market = f"{coin}/EUR"
        balans = cache.balans(force=True)
        tickers = cache.tickers()
        koers = koers_van(tickers, market) or 0.0
        aantal = balans["total"].get(coin, 0.0)
        waarde = aantal * koers

        verkoop_tekst = ""
        if waarde >= 1.0:
            fee = fee_fractie(config)
            try:
                gevuld = plaats_marktorder("sell", market, aantal, "verkoop")
            except Exception as order_e:
                log_error(f"verwerk_pot_munt_verwijderen.verkoop.{coin}", order_e)
                send_telegram_message(
                    f"🚨 Verkoop van {coin} is mislukt — munt blijft nog in de pot staan. Probeer het nog eens.",
                    custom_keyboard=POT_KEYBOARD,
                )
                return

            cache.invalideer()
            if not gevuld:
                send_telegram_message(
                    f"⚠️ De verkooporder voor {coin} is niet gevuld — munt blijft nog in de pot staan. Probeer het later nog eens.",
                    custom_keyboard=POT_KEYBOARD,
                )
                return
            netto_opbrengst = round(waarde * (1.0 - fee), 2)
            budget = config["pot_coins"][coin].get("budget_eur", 0.0)
            netto_winst = round(netto_opbrengst - budget, 2)
            log_trade(market, "verkoop", aantal, koers, netto_winst, netto_winst * fee, "handmatig")
            registreer_pot_verkoop(coin, netto_winst, netto_opbrengst)
            verkoop_tekst = f"\n• Verkocht voor {euro(netto_opbrengst)}, terug in pot-cash."

        verse_config = laad_config()
        verse_config["pot_coins"].pop(coin, None)
        bewaar_config(verse_config)
        db.remove(Trade.munt == market)

        send_telegram_message(f"🗑️ *{coin} verwijderd uit de pot.*{verkoop_tekst}", custom_keyboard=POT_KEYBOARD)
    except Exception as e:
        log_error("verwerk_pot_munt_verwijderen", e)
        send_telegram_message("🚨 Fout bij verwijderen uit de pot.", custom_keyboard=POT_KEYBOARD)


@met_lock
def verwerk_pot_munt_budget_verhogen(invoer_tekst):
    """
    Verhoogt het budget van een bestaande pot-munt en koopt meteen het
    verschil bij, zodat de positie echt groeit (niet alleen het doel
    verder weg komt te staan). Alleen verhogen, niet verlagen — dat zou
    een verkoop vereisen.
    """
    try:
        delen = invoer_tekst.strip().split()
        if len(delen) != 2:
            send_telegram_message("⚠️ Ongeldige invoer. Typ bijvoorbeeld `AVAX 100`.", custom_keyboard=POT_KEYBOARD)
            return

        coin = delen[0].upper().replace("/EUR", "")
        nieuw_budget = float(delen[1].replace(",", ".").replace("€", ""))

        config = laad_config()
        if coin not in config["pot_coins"]:
            send_telegram_message(f"❌ *{coin}* staat niet in de pot.", custom_keyboard=POT_KEYBOARD)
            return

        # Tegen het WERKELIJK geïnvesteerde bedrag afzetten, niet tegen het
        # ingestelde budget: een munt die handmatig is toegevoegd (of nog
        # laagsgewijs aan het bijkopen is) kan een budget hebben dat al op
        # het doel staat terwijl er in werkelijkheid nog veel minder in zit.
        balans = cache.balans(force=True)
        tickers = cache.tickers()
        koers = koers_van(tickers, f"{coin}/EUR") or 0.0
        huidige_waarde = balans["total"].get(coin, 0.0) * koers

        if nieuw_budget <= huidige_waarde:
            send_telegram_message(
                f"⚠️ *{coin}* staat al op {euro(huidige_waarde)}, dat is al gelijk aan of meer dan "
                f"het nieuwe budget ({euro(nieuw_budget)}). Verlagen kan hier niet, want dat vereist een verkoop.",
                custom_keyboard=POT_KEYBOARD,
            )
            return

        verschil = round(nieuw_budget - huidige_waarde, 2)
        state = laad_state()
        pot_cash = state.get("pot_cash_eur", 0.0)
        if verschil < MIN_ORDER_EUR:
            send_telegram_message(f"⚠️ Verschil moet minimaal {euro(MIN_ORDER_EUR)} zijn.", custom_keyboard=POT_KEYBOARD)
            return
        if verschil > pot_cash:
            send_telegram_message(
                f"⚠️ Je hebt maar {euro(pot_cash)} pot-cash, {euro(verschil)} nodig voor deze verhoging.",
                custom_keyboard=POT_KEYBOARD,
            )
            return

        market = f"{coin}/EUR"
        fee = fee_fractie(config)
        try:
            gevuld = plaats_marktorder("buy", market, verschil, "aankoop")
        except Exception as order_e:
            log_error(f"verwerk_pot_munt_budget_verhogen.{coin}", order_e)
            send_telegram_message(f"🚨 Order voor {coin} is mislukt.", custom_keyboard=POT_KEYBOARD)
            return

        cache.invalideer()
        if not gevuld:
            send_telegram_message(
                f"⚠️ De order voor {coin} is niet gevuld (te dun orderboek?). Er is niets gekocht, het budget is niet aangepast.",
                custom_keyboard=POT_KEYBOARD,
            )
            return
        log_trade(market, "koop", None, None, verschil, verschil * fee, "pot-automatisch")
        registreer_pot_koop(coin, verschil)

        verse_config = laad_config()
        gs = verse_config.get("global_settings", {})
        winstdoel_eur = float(gs.get("pot_winstdoel_eur", STANDAARD_POT_WINSTDOEL_EUR))
        verse_config["pot_coins"][coin]["budget_eur"] = nieuw_budget
        verse_config["pot_coins"][coin]["take_profit_pct"] = round(winstdoel_eur / nieuw_budget * 100, 2)
        verse_config["pot_coins"][coin]["vast_doel"] = True
        bewaar_config(verse_config)

        send_telegram_message(
            f"🧪 *{coin} opgehoogd naar {euro(nieuw_budget)}*\n"
            f"• Bijgekocht: {euro(verschil)}",
            custom_keyboard=POT_KEYBOARD,
        )
    except ValueError:
        send_telegram_message("⚠️ Ongeldig bedrag.", custom_keyboard=POT_KEYBOARD)
    except Exception as e:
        log_error("verwerk_pot_munt_budget_verhogen", e)
        send_telegram_message("🚨 Fout bij ophogen van het budget.", custom_keyboard=POT_KEYBOARD)


@met_lock
def verwerk_pot_storten(invoer):
    try:
        bedrag = float(invoer.strip().replace(",", ".").replace("€", ""))
    except ValueError:
        send_telegram_message("⚠️ Geen geldig bedrag. Typ bijvoorbeeld `50`.", custom_keyboard=POT_KEYBOARD)
        return

    if bedrag <= 0:
        send_telegram_message("⚠️ Bedrag moet groter dan 0 zijn.", custom_keyboard=POT_KEYBOARD)
        return

    state = laad_state()
    balans = cache.balans(force=True)
    vrij_cash = balans["free"].get("EUR", 0.0)
    # Wat nu nog vrij is, dus niet al gereserveerd en niet al in de pot zit
    vrij_voor_pot = handelscash(vrij_cash, state)

    if bedrag > vrij_voor_pot:
        send_telegram_message(
            f"⚠️ Je hebt maar {euro(vrij_voor_pot)} vrije cash die niet al gereserveerd is "
            f"of al in de pot zit.",
            custom_keyboard=POT_KEYBOARD,
        )
        return

    state["pot_cash_eur"] = round(state.get("pot_cash_eur", 0.0) + bedrag, 2)
    state["pot_gestort"] = round(state.get("pot_gestort", 0.0) + bedrag, 2)
    bewaar_state(state)
    send_telegram_message(
        f"🧪 *{euro(bedrag, False)} gestort in de pot.*\n"
        f"Pot cash staat nu op {euro(state['pot_cash_eur'])}.\n\n"
        f"_Dit is een boeking, er verandert niets op Bitvavo._",
        custom_keyboard=POT_KEYBOARD,
    )
    # Meteen laten kiezen als er nu ruimte is, niet wachten op de dagelijkse cyclus
    threading.Thread(target=kies_pot_munten, daemon=True).start()


@met_lock
def verwerk_pot_opnemen(invoer):
    try:
        bedrag = float(invoer.strip().replace(",", ".").replace("€", ""))
    except ValueError:
        send_telegram_message("⚠️ Geen geldig bedrag. Typ bijvoorbeeld `20`.", custom_keyboard=POT_KEYBOARD)
        return

    state = laad_state()
    pot_cash = state.get("pot_cash_eur", 0.0)
    if bedrag <= 0 or bedrag > pot_cash:
        send_telegram_message(
            f"⚠️ Bedrag moet tussen 0 en {euro(pot_cash)} liggen. "
            f"Alleen de vrije pot-cash kan opgenomen worden, geen belegd deel.",
            custom_keyboard=POT_KEYBOARD,
        )
        return

    state["pot_cash_eur"] = round(pot_cash - bedrag, 2)
    state["pot_gestort"] = round(max(0.0, state.get("pot_gestort", 0.0) - bedrag), 2)
    bewaar_state(state)
    send_telegram_message(
        f"🧪 *{euro(bedrag, False)} uit de pot gehaald.*\n"
        f"Pot cash staat nu op {euro(state['pot_cash_eur'])}.",
        custom_keyboard=POT_KEYBOARD,
    )


@met_lock
def verwerk_pot_munt_uitsluiten(invoer_tekst):
    """
    Zet een munt op de uitsluitingslijst zodat kies_pot_munten() hem nooit
    kiest. Staat de munt al op de lijst, dan heft dit de uitsluiting weer op
    (toggle) — typ dus gewoon nogmaals dezelfde afkorting om terug te draaien.
    """
    coin = invoer_tekst.strip().upper().replace("/EUR", "")
    if not coin or " " in coin:
        send_telegram_message("⚠️ Typ één muntafkorting, bijvoorbeeld `SOL`.", custom_keyboard=POT_KEYBOARD)
        return

    config = laad_config()
    gs = config.setdefault("global_settings", {})
    uitgesloten = set(gs.get("pot_uitgesloten", []))

    if coin in uitgesloten:
        uitgesloten.discard(coin)
        gs["pot_uitgesloten"] = sorted(uitgesloten)
        bewaar_config(config)
        send_telegram_message(
            f"✅ *{coin}* mag weer gekozen worden door de pot.", custom_keyboard=POT_KEYBOARD
        )
        return

    uitgesloten.add(coin)
    gs["pot_uitgesloten"] = sorted(uitgesloten)

    verwijderd = coin in config["pot_coins"]
    if verwijderd:
        del config["pot_coins"][coin]

    bewaar_config(config)

    if verwijderd:
        db.remove(Trade.munt == f"{coin}/EUR")
        send_telegram_message(
            f"🚫 *{coin} uitgesloten* en meteen uit de pot verwijderd.\n"
            f"_Typ nogmaals `{coin}` bij deze knop om dit weer op te heffen._",
            custom_keyboard=POT_KEYBOARD,
        )
    else:
        send_telegram_message(
            f"🚫 *{coin} uitgesloten.* De pot zal hem nooit zelf kiezen.\n"
            f"_Typ nogmaals `{coin}` bij deze knop om dit weer op te heffen._",
            custom_keyboard=POT_KEYBOARD,
        )


@met_lock
def wijzig_pot_instellingen(max_munten, budget_per_munt, winstdoel_eur, trailing_pct):
    """
    Past de algemene pot-instellingen aan (max. aantal munten, budget per
    nieuwe munt, winstdoel in euro's, trailing-percentage). Raakt alleen
    toekomstige munt-keuzes — bestaande pot-munten blijven op hun eigen,
    al vastgezette waarden staan (die pas je apart aan via budget ophogen).
    Geeft (True, bericht) of (False, foutmelding) terug.
    """
    if max_munten < 1 or max_munten > 10:
        return False, "Max. aantal munten moet tussen 1 en 10 liggen."
    if budget_per_munt < MIN_ORDER_EUR:
        return False, f"Budget per munt moet minimaal {euro(MIN_ORDER_EUR)} zijn."
    if winstdoel_eur < MIN_WINST_EUR:
        return False, f"Winstdoel moet minimaal {euro(MIN_WINST_EUR)} zijn."
    if trailing_pct < 0.1 or trailing_pct > 10:
        return False, "Trailing moet tussen 0,1% en 10% liggen."

    config = laad_config()
    gs = config.setdefault("global_settings", {})
    gs["pot_max_munten"] = int(max_munten)
    gs["pot_budget_per_munt"] = round(budget_per_munt, 2)
    gs["pot_winstdoel_eur"] = round(winstdoel_eur, 2)
    gs["pot_trailing_pct"] = round(trailing_pct, 2)
    bewaar_config(config)

    send_telegram_message(
        f"🧪 *Pot-instellingen aangepast*\n"
        f"• Max. munten: `{int(max_munten)}`\n"
        f"• Budget per nieuwe munt: {euro(budget_per_munt)}\n"
        f"• Winstdoel: {euro(winstdoel_eur)}\n"
        f"• Trailing: `{trailing_pct}%`\n\n"
        f"_Geldt voor nieuw gekozen munten. Bestaande pot-munten pas je apart aan._",
        custom_keyboard=POT_KEYBOARD,
    )
    return True, "Pot-instellingen opgeslagen."


@met_lock
def verwerk_dalpot_storten(invoer):
    try:
        bedrag = float(invoer.strip().replace(",", ".").replace("€", ""))
    except ValueError:
        send_telegram_message("⚠️ Geen geldig bedrag.", include_keyboard=True)
        return
    if bedrag <= 0:
        send_telegram_message("⚠️ Bedrag moet groter dan 0 zijn.", include_keyboard=True)
        return

    state = laad_state()
    balans = cache.balans(force=True)
    vrij_cash = balans["free"].get("EUR", 0.0)
    vrij_voor_dalpot = handelscash(vrij_cash, state)
    if bedrag > vrij_voor_dalpot:
        send_telegram_message(
            f"⚠️ Je hebt maar {euro(vrij_voor_dalpot)} vrije cash die niet al gereserveerd is.",
            include_keyboard=True,
        )
        return

    state["dalpot_cash_eur"] = round(state.get("dalpot_cash_eur", 0.0) + bedrag, 2)
    state["dalpot_gestort"] = round(state.get("dalpot_gestort", 0.0) + bedrag, 2)
    bewaar_state(state)
    send_telegram_message(
        f"📉 *{euro(bedrag, False)} gestort in de dalpot.*\n"
        f"Dalpot cash staat nu op {euro(state['dalpot_cash_eur'])}.\n\n"
        f"_Dit is een boeking, er verandert niets op Bitvavo._",
        include_keyboard=True,
    )
    threading.Thread(target=kies_dalpot_munten, daemon=True).start()


@met_lock
def verwerk_dalpot_opnemen(invoer):
    try:
        bedrag = float(invoer.strip().replace(",", ".").replace("€", ""))
    except ValueError:
        send_telegram_message("⚠️ Geen geldig bedrag.", include_keyboard=True)
        return

    state = laad_state()
    dalpot_cash = state.get("dalpot_cash_eur", 0.0)
    if bedrag <= 0 or bedrag > dalpot_cash:
        send_telegram_message(
            f"⚠️ Bedrag moet tussen 0 en {euro(dalpot_cash)} liggen.", include_keyboard=True
        )
        return

    state["dalpot_cash_eur"] = round(dalpot_cash - bedrag, 2)
    state["dalpot_gestort"] = round(max(0.0, state.get("dalpot_gestort", 0.0) - bedrag), 2)
    bewaar_state(state)
    send_telegram_message(
        f"📉 *{euro(bedrag, False)} uit de dalpot gehaald.*\n"
        f"Dalpot cash staat nu op {euro(state['dalpot_cash_eur'])}.",
        include_keyboard=True,
    )


@met_lock
def verwerk_dalpot_munt_toevoegen(invoer_tekst):
    try:
        delen = invoer_tekst.strip().split()
        if len(delen) != 2:
            send_telegram_message("⚠️ Ongeldige invoer. Typ bijvoorbeeld `XRP 100`.", include_keyboard=True)
            return

        coin = delen[0].upper().replace("/EUR", "")
        nieuw_budget = float(delen[1].replace(",", ".").replace("€", ""))
        market = f"{coin}/EUR"

        if not markt_bestaat(market):
            send_telegram_message(f"❌ Markt *{market}* bestaat niet op Bitvavo.", include_keyboard=True)
            return
        if is_reserve_munt(coin):
            send_telegram_message(RESERVE_GEWEIGERD_TEKST.format(munt=coin), include_keyboard=True)
            return
        if nieuw_budget < MIN_ORDER_EUR:
            send_telegram_message(f"⚠️ Budget moet minimaal {euro(MIN_ORDER_EUR)} zijn.", include_keyboard=True)
            return

        config = laad_config()
        if coin in config["coins"] or coin in config["pot_coins"]:
            send_telegram_message(
                f"❌ *{coin}* staat al in de hoofdlijst of de pot. Een munt kan maar op één plek staan.",
                include_keyboard=True,
            )
            return
        if coin in config["dalpot_coins"]:
            send_telegram_message(f"ℹ️ *{coin}* staat al in de dalpot.", include_keyboard=True)
            return

        gs = config.get("global_settings", {})
        winstdoel_eur = float(gs.get("dalpot_winstdoel_eur", STANDAARD_DALPOT_WINSTDOEL_EUR))
        trailing_pct = float(gs.get("dalpot_trailing_pct", STANDAARD_DALPOT_TRAILING_PCT))

        # De dalpot koopt altijd in één keer het volle budget. Lukt dat niet
        # (te weinig cash of een niet-gevulde order), dan wordt de munt niet
        # toegevoegd, anders staat er een positie in de boeken die niet bestaat.
        bedrag = round(nieuw_budget, 2)
        dalpot_cash = laad_state().get("dalpot_cash_eur", 0.0)
        if dalpot_cash < bedrag:
            send_telegram_message(
                f"⚠️ Te weinig dalpot-cash ({euro(dalpot_cash)}) voor een budget van {euro(bedrag)}. "
                f"Stort eerst bij.", include_keyboard=True,
            )
            return

        try:
            gevuld = plaats_marktorder("buy", market, bedrag, "aankoop")
        except Exception as koop_e:
            log_error(f"verwerk_dalpot_munt_toevoegen.koop.{coin}", koop_e)
            send_telegram_message(f"🚨 Kopen van *{coin}* is mislukt. Er is niets gekocht of toegevoegd.", include_keyboard=True)
            return
        cache.invalideer()
        if not gevuld:
            send_telegram_message(
                f"⚠️ De order voor *{coin}* is niet gevuld (waarschijnlijk een te dun orderboek). "
                f"Er is niets gekocht of toegevoegd.", include_keyboard=True,
            )
            return

        fee = fee_fractie(config)
        log_trade(market, "koop", None, None, bedrag, bedrag * fee, "dalpot-automatisch")
        registreer_dalpot_koop(coin, bedrag)
        config["dalpot_coins"][coin] = {
            "active": True, "budget_eur": bedrag,
            "take_profit_pct": round(winstdoel_eur / bedrag * 100, 2) if bedrag else 10.0,
            "trailing_sell_pct": trailing_pct,
            "vast_doel": True,
        }
        bewaar_config(config)
        threading.Thread(target=ververs_iconen, daemon=True).start()

        send_telegram_message(
            f"📉 *{coin} toegevoegd aan de dalpot!*\n"
            f"• Budget: {euro(bedrag)}\n"
            f"• Meteen gekocht: {euro(bedrag)}\n",
            include_keyboard=True,
        )
    except ValueError:
        send_telegram_message("⚠️ Het budget is geen geldig getal.", include_keyboard=True)
    except Exception as e:
        log_error("verwerk_dalpot_munt_toevoegen", e)
        send_telegram_message("🚨 Fout bij toevoegen aan de dalpot.", include_keyboard=True)


@met_lock
def verwerk_dalpot_munt_verwijderen(coin_code):
    """Zelfde als verwerk_pot_munt_verwijderen, maar voor de dalpot."""
    try:
        coin = coin_code.replace("/EUR", "").strip().upper()
        config = laad_config()
        if coin not in config["dalpot_coins"]:
            send_telegram_message(f"❌ *{coin}* staat niet in de dalpot.", include_keyboard=True)
            return

        market = f"{coin}/EUR"
        balans = cache.balans(force=True)
        tickers = cache.tickers()
        koers = koers_van(tickers, market) or 0.0
        aantal = balans["total"].get(coin, 0.0)
        waarde = aantal * koers

        verkoop_tekst = ""
        if waarde >= 1.0:
            fee = fee_fractie(config)
            try:
                gevuld = plaats_marktorder("sell", market, aantal, "verkoop")
            except Exception as order_e:
                log_error(f"verwerk_dalpot_munt_verwijderen.verkoop.{coin}", order_e)
                send_telegram_message(
                    f"🚨 Verkoop van {coin} is mislukt — munt blijft nog in de dalpot staan.",
                    include_keyboard=True,
                )
                return

            cache.invalideer()
            if not gevuld:
                send_telegram_message(
                    f"⚠️ De verkooporder voor {coin} is niet gevuld — munt blijft nog in de dalpot staan. Probeer het later nog eens.",
                    include_keyboard=True,
                )
                return
            netto_opbrengst = round(waarde * (1.0 - fee), 2)
            budget = config["dalpot_coins"][coin].get("budget_eur", 0.0)
            netto_winst = round(netto_opbrengst - budget, 2)
            log_trade(market, "verkoop", aantal, koers, netto_winst, netto_winst * fee, "handmatig")
            registreer_dalpot_verkoop(coin, netto_winst, netto_opbrengst)
            verkoop_tekst = f"\n• Verkocht voor {euro(netto_opbrengst)}, terug in dalpot-cash."

        verse_config = laad_config()
        verse_config["dalpot_coins"].pop(coin, None)
        bewaar_config(verse_config)
        db.remove(Trade.munt == market)

        send_telegram_message(f"🗑️ *{coin} verwijderd uit de dalpot.*{verkoop_tekst}", include_keyboard=True)
    except Exception as e:
        log_error("verwerk_dalpot_munt_verwijderen", e)
        send_telegram_message("🚨 Fout bij verwijderen uit de dalpot.", include_keyboard=True)


@met_lock
def verwerk_dalpot_munt_uitsluiten(invoer_tekst):
    coin = invoer_tekst.strip().upper().replace("/EUR", "")
    if not coin or " " in coin:
        send_telegram_message("⚠️ Typ één muntafkorting.", include_keyboard=True)
        return

    config = laad_config()
    gs = config.setdefault("global_settings", {})
    uitgesloten = set(gs.get("dalpot_uitgesloten", STANDAARD_DALPOT_UITGESLOTEN))

    if coin in uitgesloten:
        uitgesloten.discard(coin)
        gs["dalpot_uitgesloten"] = sorted(uitgesloten)
        bewaar_config(config)
        send_telegram_message(f"✅ *{coin}* mag weer gekozen worden door de dalpot.", include_keyboard=True)
        return

    uitgesloten.add(coin)
    gs["dalpot_uitgesloten"] = sorted(uitgesloten)
    verwijderd = coin in config["dalpot_coins"]
    if verwijderd:
        del config["dalpot_coins"][coin]
    bewaar_config(config)

    send_telegram_message(
        f"🚫 *{coin} uitgesloten.* De dalpot zal hem nooit zelf kiezen.\n"
        f"_Typ nogmaals `{coin}` om dit weer op te heffen._",
        include_keyboard=True,
    )


@met_lock
def wijzig_dalpot_instellingen(max_munten, budget_per_munt, winstdoel_eur, trailing_pct):
    """Zelfde als wijzig_pot_instellingen, maar voor de dalpot."""
    if max_munten < 1 or max_munten > 10:
        return False, "Max. aantal munten moet tussen 1 en 10 liggen."
    if budget_per_munt < MIN_ORDER_EUR:
        return False, f"Budget per munt moet minimaal {euro(MIN_ORDER_EUR)} zijn."
    if winstdoel_eur < MIN_WINST_EUR:
        return False, f"Winstdoel moet minimaal {euro(MIN_WINST_EUR)} zijn."
    if trailing_pct < 0.1 or trailing_pct > 10:
        return False, "Trailing moet tussen 0,1% en 10% liggen."

    config = laad_config()
    gs = config.setdefault("global_settings", {})
    gs["dalpot_max_munten"] = int(max_munten)
    gs["dalpot_budget_per_munt"] = round(budget_per_munt, 2)
    gs["dalpot_winstdoel_eur"] = round(winstdoel_eur, 2)
    gs["dalpot_trailing_pct"] = round(trailing_pct, 2)
    bewaar_config(config)

    send_telegram_message(
        f"📉 *Dalpot-instellingen aangepast*\n"
        f"• Max. munten: `{int(max_munten)}`\n"
        f"• Budget per nieuwe munt: {euro(budget_per_munt)}\n"
        f"• Winstdoel: {euro(winstdoel_eur)}\n"
        f"• Trailing: `{trailing_pct}%`",
        include_keyboard=True,
    )
    return True, "Dalpot-instellingen opgeslagen."


# ---------------------------------------------------------------------------
# Weergavecommando's
# ---------------------------------------------------------------------------

@met_lock
def verzamel_posities():
    """
    Bouwt de positielijst op. Wordt door dashboard, Telegram en saldo gedeeld.

    Staat onder de lock omdat TinyDB niet atomisch schrijft: zonder lock kon
    een dashboardverzoek of Telegram-commando bot_trades_db.json lezen precies
    terwijl check_portfolio() erin aan het schrijven was, met een
    JSONDecodeError tot gevolg (live waargenomen in cmd_live_dashboard).
    """
    config = laad_config()
    coins = config.get("coins", {})
    fee = fee_fractie(config)
    balans = cache.balans()
    tickers = cache.tickers()
    vrij_cash = balans["free"].get("EUR", 0.0)

    iconen = laad_iconen().get("iconen", {})
    # State wordt hier één keer gelezen en aan inleg_bodem() doorgegeven,
    # in plaats van dat elke munt opnieuw het bestand van schijf leest.
    state = laad_state()
    state_geoogst = state.get("geoogst", {})
    posities = []
    totaal_belegd = 0.0

    for coin, info in coins.items():
        budget = info.get("budget_eur", 0.0)
        tp_pct = info.get("take_profit_pct", 3.0)
        market = f"{coin}/EUR"

        live_koers = koers_van(tickers, market) or 0.0
        aantal = balans["total"].get(coin, 0.0)
        waarde = aantal * live_koers
        totaal_belegd += waarde

        winst = waarde - budget
        rendement = (winst / budget) * 100 if budget > 0 else 0
        netto_doel, doel_eur = bereken_doel(budget, tp_pct, fee)
        voortgang = (winst / doel_eur) * 100 if doel_eur > 0 else 0

        bestaande_trade = db.get(Trade.munt == market)
        status = bestaande_trade.get("status", "MONITORING") if bestaande_trade else "MONITORING"

        ingelegd, plafond, op_slot = inleg_bodem(coin, budget, config, state)

        posities.append({
            "coin": coin,
            "icoon": iconen.get(coin, ""),
            "ingelegd": round(ingelegd, 2),
            "plafond": round(plafond, 2),
            "op_slot": op_slot,
            "geoogst": round(state_geoogst.get(coin, 0.0), 2),
            "dagrange": info.get("dagrange_pct"),
            "take_profit_pct": tp_pct,
            "actief": info.get("active", True),
            "koers": live_koers,
            "waarde": waarde,
            "budget": budget,
            "winst": winst,
            "netto_winst": winst * (1.0 - fee) if winst > 0 else winst,
            "rendement": rendement,
            "doel_eur": doel_eur,
            "netto_doel": netto_doel,
            "voortgang": voortgang,
            "status": status,
        })

    posities.sort(key=lambda x: (0 if x["rendement"] >= 0 else 1, -x["waarde"]))
    return posities, vrij_cash, totaal_belegd


def cmd_live_dashboard():
    try:
        posities, vrij_cash, totaal_belegd = verzamel_posities()
        state = laad_state()
        pot = verzamel_pot()
        dalpot = verzamel_dalpot()
        regels = []
        for p in posities:
            if not p["actief"]:
                continue
            rendement_str = f"+{p['rendement']:.1f}%" if p["rendement"] >= 0 else f"{p['rendement']:.1f}%"
            icon = "🟢 " if p["rendement"] >= 0 else "🔴 "
            regels.append(
                f"{icon}*{p['coin'].ljust(6)}*: `{euro(p['waarde'], False)} ({rendement_str})` [€{p['budget']:.0f}]"
            )

        btc_waarde = btc_reserve_waarde()
        bericht = (
            f"🤖 *PROFIT HARVESTER V5.7*\n\n"
            f"💼 *Totale waarde:* {euro(vrij_cash + totaal_belegd + btc_waarde + pot['belegd'] + dalpot['belegd'])}\n"
            f"💰 *Vrije cash:* {euro(handelscash(vrij_cash, state))}\n"
            f"🪙 *Belegd:* {euro(totaal_belegd)}\n"
            f"💎 *Afgeroomd naar {reserve_naam()}:* {euro(btc_waarde)}\n\n"
            f"📊 *LIVE POSITIES PER MUNT*:\n" + ("\n".join(regels) if regels else "_Geen actieve munten._")
        )
        send_telegram_message(bericht, include_keyboard=True)
    except Exception as e:
        log_error("cmd_live_dashboard", e)
        send_telegram_message("🚨 Dashboard ophalen mislukt. Zie bot_errors.log.", include_keyboard=True)


def cmd_beheren():
    config = laad_config()
    coins = config.get("coins", {})
    if not coins:
        send_telegram_message("🪙 Er staan nog geen munten in de configuratie.", include_keyboard=True)
        return

    fee = fee_fractie(config)
    lines = ["🪙 *MUNTEN BEHEER V5.7*", ""]
    for coin, info in coins.items():
        status = "✅" if info.get("active", True) else "⏸️"
        budget = info.get("budget_eur", 250.0)
        tp_pct = info.get("take_profit_pct", 3.0)
        netto_doel, _ = bereken_doel(budget, tp_pct, fee)
        lines.append(f"{status} *{coin}* | Budget: €{budget:.0f} | Doel: {euro(netto_doel, False)} netto")
    send_telegram_message("\n".join(lines), include_keyboard=True)


def cmd_overzicht():
    """
    Samenvoeging van het oude 'saldo & cash' en 'winst & reserve': cash,
    belegd, totaal, gerealiseerde winst en reserve in één scherm. De
    per-munt uitsplitsing is bewust weggelaten, die staat overzichtelijker
    op het dashboard.
    """
    try:
        _, vrij_cash, totaal_belegd = verzamel_posities()
        state = laad_state()
        btc_waarde = btc_reserve_waarde()
        pot = verzamel_pot()
        dalpot = verzamel_dalpot()
        echt_vrij = handelscash(vrij_cash, state)
        pot_cash = pot["cash"]
        pot_belegd = pot["belegd"]
        dalpot_cash = dalpot["cash"]
        dalpot_belegd = dalpot["belegd"]
        totaal = vrij_cash + totaal_belegd + btc_waarde + pot_belegd + dalpot_belegd

        bericht = (
            f"💼 *OVERZICHT*\n\n"
            f"💰 *Kapitaal*\n"
            f"• Vrije cash: {euro(echt_vrij)}\n"
            f"• Gereserveerd voor pot: {euro(pot_cash)}\n"
            f"• Gereserveerd voor dalpot: {euro(dalpot_cash)}\n\n"
            f"📊 *Verdeling*\n"
            f"• Belegd: {euro(totaal_belegd)}\n"
            f"• Afgeroomd naar {reserve_naam()}: {euro(btc_waarde)}\n"
            f"• Belegd in pot: {euro(pot_belegd)}\n"
            f"• Belegd in dalpot: {euro(dalpot_belegd)}\n\n"
            f"▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
            f"💼 Totale waarde: {euro(totaal)}"
        )
        send_telegram_message(bericht, include_keyboard=True)
    except Exception as e:
        log_error("cmd_overzicht", e)
        send_telegram_message("🚨 Overzicht ophalen mislukt.", include_keyboard=True)


def cmd_pot_status():
    try:
        pot = verzamel_pot()
        if not pot["posities"] and pot["cash"] <= 0:
            config = laad_config()
            auto = config.get("global_settings", {}).get("pot_auto_kiezen", True)
            uitleg = (
                "_Stort geld, dan kiest de bot zelf een munt op basis van omzet en dagbeweging._"
                if auto else
                "_Stort geld en voeg dan zelf een munt toe._"
            )
            send_telegram_message(f"🧪 *Pot is leeg.*\n\n{uitleg}", custom_keyboard=POT_KEYBOARD)
            return

        regels = []
        for p in pot["posities"]:
            status = "✅" if p["actief"] else "⏸️"
            # Nog niets ingelegd betekent "nog niet gekocht", geen verlies —
            # zonder dit onderscheid oogt zo'n munt als −100%.
            if p.get("ingelegd", 0.0) < 1.0:
                regels.append(f"{status} *{p['coin']}*: nog niet gekocht (budget €{p['budget']:.0f})")
            else:
                regels.append(f"{status} *{p['coin']}*: {euro(p['waarde'], False)} (budget €{p['budget']:.0f})")

        uitgesloten = laad_config().get("global_settings", {}).get("pot_uitgesloten", [])
        uitsluit_regel = f"\n🚫 Uitgesloten: {', '.join(uitgesloten)}\n" if uitgesloten else ""

        noodstop = " 🛑 noodstop actief" if pot["noodstop"] else ""
        bericht = (
            f"🧪 *POT*{noodstop}\n\n"
            + ("\n".join(regels) if regels else "_Nog geen munten._") +
            f"\n▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔\n"
            f"💵 Pot cash: {euro(pot['cash'])}\n"
            f"🪙 Pot belegd: {euro(pot['belegd'])}\n"
            f"💼 Pot totaal: {euro(pot['totaal'])}\n"
            f"{uitsluit_regel}\n"
            f"_De bot koopt en verkoopt hier zelf, los van je hoofdlijst._"
        )
        send_telegram_message(bericht, custom_keyboard=POT_KEYBOARD)
    except Exception as e:
        log_error("cmd_pot_status", e)
        send_telegram_message("🚨 Pot-status ophalen mislukt.", include_keyboard=True)


def cmd_handelen_menu():
    """
    Verzamelt alle acties (aanvullen, afromen, munten beheren) en instellingen
    op één plek. Voorheen twee aparte knoppen ('Instellingen' voor beheer,
    losse hoofdmenuknoppen voor aanvullen/afromen) — samengevoegd omdat het
    hoofdmenu anders te vol werd.
    """
    config = laad_config()
    gs = config.get("global_settings", {})
    lagen = gs.get("aanvul_lagen", [4.0, 10.0, 18.0])
    bericht = (
        f"🛒 *Handelen*\n\n"
        f"Kies hieronder een actie, of bekijk de instellingen:\n\n"
        f"• 📉 Trailing Sell: `{gs.get('trailing_sell_pct', 1.0)}%` (per munt op maat)\n"
        f"• 💰 Min. netto afroomwinst: `{euro(MIN_WINST_EUR, False)}`\n"
        f"• 💎 Naar {actieve_reserve(config)} per oogst: `{gs.get('reserve_pct', STANDAARD_RESERVE_PCT)}%`\n"
        f"• 🛑 Inlegplafond per munt: `{gs.get('max_inleg_factor', STANDAARD_MAX_INLEG)}x budget`\n"
        f"• 🪜 Aanvullagen: `{', '.join(str(l) + '%' for l in lagen)}`\n"
        f"• ⏳ Wacht op bodem: `{'ja' if gs.get('wacht_op_bodem', True) else 'nee'}`\n"
        f"• 📊 Doelen op volatiliteit: `{'ja' if gs.get('volatiliteit_schaal', True) else 'nee'}`\n"
        f"• 🧾 Handelsfee: `{gs.get('fee_pct', STANDAARD_FEE_PCT)}%`\n"
        f"• ⏱️ Check Interval: `{gs.get('poll_interval_seconds', 10)}s`\n\n"
        f"🧪 *Pot*\n"
        f"• Zelf munten kiezen: `{'ja' if gs.get('pot_auto_kiezen', True) else 'nee'}`\n"
        f"• Max. aantal pot-munten: `{gs.get('pot_max_munten', STANDAARD_POT_MAX_MUNTEN)}`\n"
        f"• Uitgesloten: `{', '.join(gs.get('pot_uitgesloten', [])) or 'geen'}`\n"
        f"• Budget per munt: `{euro(gs.get('pot_budget_per_munt', gs.get('pot_min_order_eur', STANDAARD_POT_MIN_ORDER_EUR)), False)}`\n"
        f"• Min. 24u omzet: `{euro(gs.get('pot_min_volume_eur', STANDAARD_POT_MIN_VOLUME_EUR), False)}`\n"
        f"• Dagrange-bandbreedte: `{gs.get('pot_atr_min', STANDAARD_POT_ATR_MIN)}-{gs.get('pot_atr_max', STANDAARD_POT_ATR_MAX)}%`\n"
        f"• Min. per order: `{euro(gs.get('pot_min_order_eur', STANDAARD_POT_MIN_ORDER_EUR), False)}`\n"
        f"• Max per dag: `{euro(gs.get('pot_max_per_dag', STANDAARD_POT_MAX_PER_DAG), False)}`\n"
        f"• Afkoeltijd per munt: `{gs.get('pot_cooldown_uur', STANDAARD_POT_COOLDOWN_UUR)}u`\n"
        f"• Noodstop bij: `-{gs.get('pot_noodstop_pct', STANDAARD_POT_NOODSTOP_PCT)}%` t.o.v. storting\n\n"
        f"_Hoofdlijst: de bot koopt nooit uit zichzelf, alleen op jouw knop.\n"
        f"Pot: de bot kiest zijn eigen munten en koopt/verkoopt daar zelf, binnen deze grenzen._"
    )
    send_telegram_message(bericht, custom_keyboard=HANDEL_KEYBOARD)


def cmd_toon_oogstbare_munten():
    try:
        config = laad_config()
        coins = config.get("coins", {})
        fee = fee_fractie(config)
        balans = cache.balans()
        tickers = cache.tickers()
        oogstbaar = []

        for coin, info in coins.items():
            budget = info.get("budget_eur", 0.0)
            market = f"{coin}/EUR"
            live_koers = koers_van(tickers, market)
            if live_koers is None:
                continue
            waarde = balans["total"].get(coin, 0.0) * live_koers
            netto = (waarde - budget) * (1.0 - fee)
            if netto >= MIN_WINST_EUR:
                oogstbaar.append(f"• *{coin}*: {euro(netto)} netto winst (Budget: €{budget:.0f})")

        if oogstbaar:
            msg = (
                "💰 *Kies een munt om af te romen*:\n\n"
                + "\n".join(oogstbaar)
                + "\n\n_Typ de afkorting van de munt:_"
            )
        else:
            msg = f"ℹ️ Geen munten met meer dan {euro(MIN_WINST_EUR)} netto winst boven budget."

        send_telegram_message(msg, custom_keyboard=TERUG_KEYBOARD)
    except Exception as e:
        log_error("cmd_toon_oogstbare_munten", e)
        send_telegram_message("🚨 Ophalen van oogstbare munten mislukt.", include_keyboard=True)


def cmd_toon_actieve_munten_voor_verwijdering():
    config = laad_config()
    coins = config.get("coins", {})
    if not coins:
        send_telegram_message("ℹ️ Er staan geen munten in de configuratie.", include_keyboard=True)
        return
    lijst = [f"• *{coin}*" for coin in coins.keys()]
    msg = (
        "➖ *Kies een munt om te verwijderen*:\n\n"
        + "\n".join(lijst)
        + "\n\n_Typ de afkorting van de munt:_"
    )
    send_telegram_message(msg, custom_keyboard=TERUG_KEYBOARD)


# ---------------------------------------------------------------------------
# Telegram commandoafhandeling
#
# De belangrijkste fix: menuknoppen worden ALTIJD eerst herkend. In V5.5 stond
# de modus-afhandeling tussen de knoppen in, waardoor een druk op bijvoorbeeld
# "INSTELLINGEN" tijdens de afroommodus werd gelezen als de naam van een munt.
# ---------------------------------------------------------------------------

def _actie_handmatig_afromen():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "MANUAL_HARVEST"
    cmd_toon_oogstbare_munten()


def _actie_munt_toevoegen():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "ADD_COIN"
    send_telegram_message(
        "➕ *Voeg munt & budget toe*\n\n_Typ de munt en het budget (bijvoorbeeld_ `SOL 250`_):_",
        custom_keyboard=TERUG_KEYBOARD,
    )


def _actie_munt_verwijderen():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "REMOVE_COIN"
    cmd_toon_actieve_munten_voor_verwijdering()



def _actie_budget_wijzigen():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "CHANGE_COIN_BUDGET"
    send_telegram_message(
        "💵 *Typ de munt en het nieuwe budget in euro's*\n\n_Voorbeeld:_ `INJ 250`",
        custom_keyboard=TERUG_KEYBOARD,
    )


def _actie_terug():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = None
    send_telegram_message("🔙 Hoofdmenu.", include_keyboard=True)


def _actie_pot_munt_toevoegen():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "POT_ADD_COIN"
    send_telegram_message(
        "➕ *Voeg pot-munt & budget toe*\n\n_Typ munt en budget, bijvoorbeeld_ `XRP 25`_:_",
        custom_keyboard=TERUG_KEYBOARD,
    )


def _actie_pot_munt_verwijderen():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "POT_REMOVE_COIN"
    coins = laad_config().get("pot_coins", {})
    if not coins:
        send_telegram_message("ℹ️ De pot heeft nog geen munten.", custom_keyboard=POT_KEYBOARD)
        return
    lijst = [f"• *{c}*" for c in coins.keys()]
    send_telegram_message(
        "➖ *Kies een pot-munt om te verwijderen*:\n\n" + "\n".join(lijst) + "\n\n_Typ de afkorting:_",
        custom_keyboard=TERUG_KEYBOARD,
    )


def _actie_pot_storten():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "POT_DEPOSIT"
    send_telegram_message(
        "💶 *Hoeveel euro naar de pot?*\n\n_Typ een bedrag, bijvoorbeeld_ `50`_:_",
        custom_keyboard=TERUG_KEYBOARD,
    )


def _actie_pot_opnemen():
    global INSTELLINGEN_MODUS
    state = laad_state()
    INSTELLINGEN_MODUS = "POT_WITHDRAW"
    send_telegram_message(
        f"💶 *Hoeveel euro uit de pot?*\n\n"
        f"Er staat {euro(state.get('pot_cash_eur', 0.0))} vrij in de pot.\n"
        f"_Typ een bedrag:_",
        custom_keyboard=TERUG_KEYBOARD,
    )


def _actie_pot_kies_nu():
    """Directe actie, geen invoermodus nodig — zelfde patroon als 'Alles Aanvullen'."""
    send_telegram_message("🔄 Pot scant Bitvavo op nieuwe munten...", custom_keyboard=POT_KEYBOARD)
    threading.Thread(target=kies_pot_munten, kwargs={"handmatig": True}, daemon=True).start()


def _actie_pot_munt_uitsluiten():
    global INSTELLINGEN_MODUS
    INSTELLINGEN_MODUS = "POT_EXCLUDE_COIN"
    gs = laad_config().get("global_settings", {})
    uitgesloten = gs.get("pot_uitgesloten", [])
    huidig = f"\n\nAl uitgesloten: {', '.join(uitgesloten)}" if uitgesloten else ""
    send_telegram_message(
        f"🚫 *Welke munt wil je uitsluiten van de pot?*\n\n"
        f"_Typ de afkorting, bijvoorbeeld_ `SOL`_. Staat de munt in de pot, dan wordt hij ook meteen verwijderd. "
        f"Typ dezelfde afkorting nogmaals om de uitsluiting weer op te heffen.{huidig}_",
        custom_keyboard=TERUG_KEYBOARD,
    )


# Alle menuteksten, inclusief de tekstvarianten zonder emoji en de slash-commando's.
MENU_ACTIES = {
    "🔙 terug naar menu": _actie_terug,
    "terug naar menu": _actie_terug,
    "/menu": _actie_terug,

    "📊 live dashboard": cmd_live_dashboard,
    "live dashboard": cmd_live_dashboard,
    "/status": cmd_live_dashboard,

    "💼 overzicht": cmd_overzicht,
    "overzicht": cmd_overzicht,
    "/overzicht": cmd_overzicht,
    "/saldo": cmd_overzicht,
    "/winst": cmd_overzicht,

    "🪙 munten beheren": cmd_beheren,
    "munten beheren": cmd_beheren,
    "/beheren": cmd_beheren,

    "rapport mailen": stuur_email_rapport,
    "/mail": stuur_email_rapport,

    "🛒 alles aanvullen": voer_alles_aanvullen_uit,
    "alles aanvullen": voer_alles_aanvullen_uit,
    "/aanvullen": voer_alles_aanvullen_uit,

    "💰 handmatig afromen": _actie_handmatig_afromen,
    "handmatig afromen": _actie_handmatig_afromen,
    "/afromen": _actie_handmatig_afromen,

    "🛒 handelen": cmd_handelen_menu,
    "handelen": cmd_handelen_menu,
    "/handelen": cmd_handelen_menu,
    "/settings": cmd_handelen_menu,

    "➕ munt toevoegen": _actie_munt_toevoegen,
    "munt toevoegen": _actie_munt_toevoegen,

    "➖ munt verwijderen": _actie_munt_verwijderen,
    "munt verwijderen": _actie_munt_verwijderen,

    "💵 budget wijzigen": _actie_budget_wijzigen,
    "budget wijzigen": _actie_budget_wijzigen,

    "🧪 pot": cmd_pot_status,
    "pot": cmd_pot_status,
    "/pot": cmd_pot_status,

    "➕ pot munt toevoegen": _actie_pot_munt_toevoegen,
    "pot munt toevoegen": _actie_pot_munt_toevoegen,

    "➖ pot munt verwijderen": _actie_pot_munt_verwijderen,
    "pot munt verwijderen": _actie_pot_munt_verwijderen,

    "💶 pot storten": _actie_pot_storten,
    "pot storten": _actie_pot_storten,

    "💶 pot opnemen": _actie_pot_opnemen,
    "pot opnemen": _actie_pot_opnemen,

    "🚫 munt uitsluiten": _actie_pot_munt_uitsluiten,
    "munt uitsluiten": _actie_pot_munt_uitsluiten,

    "🔄 pot nu laten kiezen": _actie_pot_kies_nu,
    "pot nu laten kiezen": _actie_pot_kies_nu,
    "/potkiezen": _actie_pot_kies_nu,
}

# Acties die zelf een modus zetten, mogen de modus niet direct daarna gewist krijgen.
MODUS_SETTERS = {_actie_handmatig_afromen, _actie_munt_toevoegen, _actie_munt_verwijderen,
                 _actie_budget_wijzigen,
                 _actie_pot_munt_toevoegen, _actie_pot_munt_verwijderen,
                 _actie_pot_storten, _actie_pot_opnemen, _actie_pot_munt_uitsluiten}

MODUS_HANDLERS = {
    "MANUAL_HARVEST": voer_handmatige_oogst_uit,
    "ADD_COIN": verwerk_munt_toevoegen,
    "REMOVE_COIN": verwerk_munt_verwijderen,
    "CHANGE_COIN_BUDGET": verwerk_budget_wijziging,
    "POT_ADD_COIN": verwerk_pot_munt_toevoegen,
    "POT_REMOVE_COIN": verwerk_pot_munt_verwijderen,
    "POT_DEPOSIT": verwerk_pot_storten,
    "POT_WITHDRAW": verwerk_pot_opnemen,
    "POT_EXCLUDE_COIN": verwerk_pot_munt_uitsluiten,
}


def zoek_menu_actie(text):
    return MENU_ACTIES.get(text.strip().lower())


def verwerk_bericht(text):
    global INSTELLINGEN_MODUS

    # Stap 1: is het een menuknop? Dan wint die altijd van de invoermodus.
    actie = zoek_menu_actie(text)
    if actie:
        if actie not in MODUS_SETTERS:
            INSTELLINGEN_MODUS = None
        actie()
        return

    # Stap 2: staat de bot in een invoermodus? Dan is dit de invoer.
    if INSTELLINGEN_MODUS:
        handler = MODUS_HANDLERS.get(INSTELLINGEN_MODUS)
        INSTELLINGEN_MODUS = None
        if handler:
            handler(text)
        return

    # Stap 3: onbekend bericht.
    send_telegram_message("❓ Onbekend commando. Kies een knop uit het menu.", include_keyboard=True)


# maxlen zorgt dat de oudste id automatisch wegvalt. Een set deed dat willekeurig.
verwerkte_updates = deque(maxlen=500)
verwerkte_set = set()
laatste_update_id = 0


def telegram_loop():
    """Eigen thread met long polling, zodat de portfoliocheck niet wacht op Telegram."""
    global laatste_update_id
    if not TELEGRAM_TOKEN:
        log_info("Telegram-token ontbreekt, Telegram-thread gestopt.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    while True:
        try:
            params = {"offset": laatste_update_id + 1, "timeout": 25}
            response = requests.get(url, params=params, timeout=35)
            updates = response.json()

            for update in updates.get("result", []):
                update_id = update["update_id"]
                laatste_update_id = max(laatste_update_id, update_id)

                if update_id in verwerkte_set:
                    continue
                if len(verwerkte_updates) == verwerkte_updates.maxlen:
                    verwerkte_set.discard(verwerkte_updates[0])
                verwerkte_updates.append(update_id)
                verwerkte_set.add(update_id)

                bericht = update.get("message") or {}
                if "text" not in bericht:
                    continue

                afzender_chat_id = str(bericht.get("chat", {}).get("id", ""))
                if afzender_chat_id != str(TELEGRAM_CHAT_ID):
                    log_info(f"Bericht van onbekende chat {afzender_chat_id} genegeerd.")
                    continue

                try:
                    verwerk_bericht(bericht["text"].strip())
                except Exception as e:
                    log_error("verwerk_bericht", e)
                    send_telegram_message("🚨 Er ging iets mis bij het verwerken. Zie bot_errors.log.", include_keyboard=True)

        except requests.exceptions.RequestException as e:
            log_error("telegram_loop.netwerk", e)
            time.sleep(5)
        except Exception as e:
            log_error("telegram_loop", e)
            time.sleep(5)


# ---------------------------------------------------------------------------
# Webdashboard
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Stabiele sleutel om sessiecookies mee te ondertekenen, afgeleid van de
# bestaande DASHBOARD_TOKEN zodat hij niet bij elke herstart verandert (dat
# zou iedereen steeds opnieuw laten inloggen) en er geen los geheim bij
# hoeft in .env.
app.secret_key = hashlib.sha256(
    (DASHBOARD_TOKEN or "onveilig-standaardsleutel-zet-DASHBOARD_TOKEN-in-.env").encode()
).digest()
app.permanent_session_lifetime = 30 * 24 * 3600  # 30 dagen ingelogd blijven
# Sessiecookie extra afschermen: standaard alleen over https (Funnel is altijd
# https), uit te zetten met DASHBOARD_ALLEEN_HTTPS=0 voor gebruik op het
# thuisnetwerk. Niet leesbaar voor JavaScript. SameSite=Lax i.p.v. Strict,
# anders werkt een link vanuit bijvoorbeeld Telegram niet meteen.
app.config["SESSION_COOKIE_SECURE"] = DASHBOARD_ALLEEN_HTTPS
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Endpoints die altijd bereikbaar moeten zijn, ook zonder sessie.
# service_worker en manifest horen hierbij: een browser/telefoon moet het
# icoon en de PWA-manifest kunnen ophalen om "toevoegen aan beginscherm" aan
# te bieden, nog vóór er is ingelogd.
LOGIN_VRIJE_ENDPOINTS = {"login", "service_worker"}


@app.context_processor
def demo_vlag():
    """Maakt demo_modus beschikbaar in alle pagina's, voor het DEMO-label."""
    return {"demo_modus": DEMO_MODUS}


@app.before_request
def vereis_login():
    """
    Login voor de HELE site, niet alleen de actieknoppen. Nodig sinds het
    dashboard via Tailscale Funnel publiek bereikbaar is: zonder dit kon
    iedereen met de URL gewoon meelezen. Gebruikt een eigen inlogpagina met
    alleen een wachtwoordveld (geen HTTP Basic Auth meer — dat vroeg altijd
    om een gebruikersnaam die toch niet gebruikt werd) en een sessiecookie,
    zodat je maar één keer per apparaat hoeft in te loggen.
    """
    if not DASHBOARD_TOKEN:
        return
    if request.endpoint in LOGIN_VRIJE_ENDPOINTS or request.endpoint == "static":
        return
    if session.get("ingelogd"):
        return
    if request.path.startswith("/api/"):
        return jsonify({"fout": "Niet ingelogd."}), 401
    return redirect(url_for("login", volgende=request.path))


# Bescherming tegen wachtwoord-gokken op /login. Het dashboard staat via
# Tailscale Funnel open voor het hele internet, dus zonder dit kan iemand
# onbeperkt pogingen doen. In het geheugen bijgehouden (geen apart bestand
# nodig) — reset bij een herstart van de container, wat in de praktijk
# zelden gebeurt en geen probleem is voor dit doel.
MAX_LOGIN_POGINGEN = 5
LOGIN_VENSTER_SEC = 15 * 60
LOGIN_LOCKOUT_SEC = 15 * 60
_login_pogingen = {}  # ip -> lijst met tijdstippen van mislukte pogingen
_login_lockout_tot = {}  # ip -> tijdstip waarop de blokkade eindigt


def _client_ip():
    """
    Echte IP van de bezoeker. Achter een proxy (VERTROUW_PROXY=1) nemen we de
    LAATSTE waarde uit X-Forwarded-For: die zet de proxy er zelf bij. De
    eerste waarde kan een bezoeker zelf meesturen en is dus niet te
    vertrouwen. Zonder proxy gebruiken we gewoon het verbindingsadres.
    """
    if VERTROUW_PROXY:
        doorgestuurd = request.headers.get("X-Forwarded-For", "")
        if doorgestuurd:
            return doorgestuurd.split(",")[-1].strip()
    return request.remote_addr or "onbekend"


def _login_geblokkeerd(ip):
    tot = _login_lockout_tot.get(ip)
    if tot and time.time() < tot:
        return tot
    if tot:
        _login_lockout_tot.pop(ip, None)
        _login_pogingen.pop(ip, None)
    return None


def _login_mislukking(ip):
    nu = time.time()
    pogingen = [t for t in _login_pogingen.get(ip, []) if nu - t < LOGIN_VENSTER_SEC]
    pogingen.append(nu)
    _login_pogingen[ip] = pogingen
    if len(pogingen) >= MAX_LOGIN_POGINGEN:
        _login_lockout_tot[ip] = nu + LOGIN_LOCKOUT_SEC


@app.route("/login", methods=["GET", "POST"])
def login():
    fout = None
    ip = _client_ip()
    if request.method == "POST":
        tot = _login_geblokkeerd(ip)
        if tot:
            minuten = max(1, int((tot - time.time()) / 60) + 1)
            fout = f"Te veel mislukte pogingen. Probeer over {minuten} minuten opnieuw."
        else:
            wachtwoord = request.form.get("wachtwoord", "")
            if DASHBOARD_TOKEN and secrets.compare_digest(wachtwoord, DASHBOARD_TOKEN):
                _login_pogingen.pop(ip, None)
                _login_lockout_tot.pop(ip, None)
                session.clear()
                session["ingelogd"] = True
                session.permanent = True
                return redirect(request.form.get("volgende") or url_for("dashboard"))
            _login_mislukking(ip)
            fout = "Onjuist wachtwoord."
    volgende = request.args.get("volgende", "")
    return render_template("login.html", fout=fout, volgende=volgende)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/beheren")
def beheren():
    config = laad_config()
    gs = config.get("global_settings", {})
    hoofdlijst_munten = sorted(config.get("coins", {}).keys())
    pot_munten = sorted(config.get("pot_coins", {}).keys())
    dalpot_munten = sorted(config.get("dalpot_coins", {}).keys())
    pot_instellingen = {
        "max_munten": gs.get("pot_max_munten", STANDAARD_POT_MAX_MUNTEN),
        "budget_per_munt": gs.get("pot_budget_per_munt", gs.get("pot_min_order_eur", STANDAARD_POT_MIN_ORDER_EUR)),
        "winstdoel_eur": gs.get("pot_winstdoel_eur", STANDAARD_POT_WINSTDOEL_EUR),
        "trailing_pct": gs.get("pot_trailing_pct", STANDAARD_POT_TRAILING_PCT),
    }
    dalpot_instellingen = {
        "max_munten": gs.get("dalpot_max_munten", STANDAARD_DALPOT_MAX_MUNTEN),
        "budget_per_munt": gs.get("dalpot_budget_per_munt", STANDAARD_DALPOT_BUDGET_PER_MUNT),
        "winstdoel_eur": gs.get("dalpot_winstdoel_eur", STANDAARD_DALPOT_WINSTDOEL_EUR),
        "trailing_pct": gs.get("dalpot_trailing_pct", STANDAARD_DALPOT_TRAILING_PCT),
    }
    return render_template(
        "beheren.html",
        hoofdlijst_munten=hoofdlijst_munten,
        pot_munten=pot_munten,
        pot_instellingen=pot_instellingen,
        dalpot_munten=dalpot_munten,
        dalpot_instellingen=dalpot_instellingen,
        reserve_keuzes=RESERVE_KEUZES,
        reserve_actief=actieve_reserve(config),
        # Uit de sessie, niet uit de URL: anders kan een link met eigen tekst
        # een nep-melding op deze pagina zetten.
        reserve_melding=session.pop("reserve_melding", None),
        verwerkt=request.args.get("verwerkt"),
    )


@met_lock
def verwerk_reserve_wissel(nieuwe_munt):
    """
    Kiest naar welke reservemunt nieuwe afgeroomde winst gaat. Bestaande
    reserve blijft staan en blijft meetellen. Geeft een korte melding terug
    voor de Beheren-pagina.
    """
    munt = (nieuwe_munt or "").strip().upper()
    if munt not in RESERVE_KEUZES:
        return f"{munt or 'Deze munt'} kan geen reservemunt zijn. Kies uit {', '.join(RESERVE_KEUZES)}."
    if not markt_bestaat(f"{munt}/EUR"):
        return f"Markt {munt}/EUR bestaat niet op Bitvavo."
    config = laad_config()
    oud = actieve_reserve(config)
    if munt == oud:
        return f"{munt} was al de actieve reservemunt."
    config["global_settings"]["reserve_actief"] = munt
    bewaar_config(config)
    log_info(f"Reservemunt gewisseld van {oud} naar {munt}.")
    send_telegram_message(
        f"{RESERVE_ICOON.get(munt, '💎')} *Reservemunt gewisseld: {oud} → {munt}*\n\n"
        f"Nieuwe afgeroomde winst gaat voortaan naar {munt}. Je {oud}-reserve blijft "
        f"gewoon staan en telt mee in je totale waarde.",
        include_keyboard=True,
    )
    return f"Nieuwe winst gaat voortaan naar {munt}. Je {oud}-reserve blijft staan."


@app.route("/beheren/reserve-munt", methods=["POST"])
def beheren_reserve_munt():
    try:
        melding = verwerk_reserve_wissel(request.form.get("munt", ""))
    except Exception as e:
        log_error("beheren_reserve_munt", e)
        melding = "Wisselen is mislukt. Zie bot_errors.log."
    session["reserve_melding"] = melding
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/help")
def help_pagina():
    """
    De uitleg toont de instellingen zoals ze nu echt staan (uit de config,
    anders de standaardwaarden), zodat de tekst nooit achterloopt op de bot.
    """
    config = laad_config()
    gs = config.get("global_settings", {})
    pot_min_order = float(gs.get("pot_min_order_eur", STANDAARD_POT_MIN_ORDER_EUR))
    instellingen = {
        "demo": DEMO_MODUS,
        "fee_pct": fee_fractie(config) * 100,
        "min_winst": MIN_WINST_EUR,
        "min_order": MIN_ORDER_EUR,
        "hoofd_doel": float(gs.get("hoofdlijst_winstdoel_eur", STANDAARD_HOOFDLIJST_WINSTDOEL_EUR)),
        "max_inleg": float(gs.get("max_inleg_factor", STANDAARD_MAX_INLEG)),
        "lagen": gs.get("aanvul_lagen", [4.0, 10.0, 18.0]),
        "trailing_buy": float(gs.get("trailing_buy_pct", 1.0)),
        "wacht_op_bodem": gs.get("wacht_op_bodem", True),
        "reserve_pct": float(gs.get("reserve_pct", STANDAARD_RESERVE_PCT)),
        "reserve_actief": actieve_reserve(config),
        "reserve_keuzes": RESERVE_KEUZES,
        "pot_max": int(gs.get("pot_max_munten", STANDAARD_POT_MAX_MUNTEN)),
        "pot_budget": float(gs.get("pot_budget_per_munt", pot_min_order)),
        "pot_min_order": pot_min_order,
        "pot_doel": float(gs.get("pot_winstdoel_eur", STANDAARD_POT_WINSTDOEL_EUR)),
        "pot_trail": float(gs.get("pot_trailing_pct", STANDAARD_POT_TRAILING_PCT)),
        "pot_cooldown": float(gs.get("pot_cooldown_uur", STANDAARD_POT_COOLDOWN_UUR)),
        "pot_per_dag": float(gs.get("pot_max_per_dag", STANDAARD_POT_MAX_PER_DAG)),
        "pot_noodstop": float(gs.get("pot_noodstop_pct", STANDAARD_POT_NOODSTOP_PCT)),
        "pot_min_volume": float(gs.get("pot_min_volume_eur", STANDAARD_POT_MIN_VOLUME_EUR)),
        "pot_atr_min": float(gs.get("pot_atr_min", STANDAARD_POT_ATR_MIN)),
        "pot_atr_max": float(gs.get("pot_atr_max", STANDAARD_POT_ATR_MAX)),
        "pot_uitgesloten": sorted(gs.get("pot_uitgesloten", [])),
        "dalpot_max": int(gs.get("dalpot_max_munten", STANDAARD_DALPOT_MAX_MUNTEN)),
        "dalpot_budget": float(gs.get("dalpot_budget_per_munt", STANDAARD_DALPOT_BUDGET_PER_MUNT)),
        "dalpot_doel": float(gs.get("dalpot_winstdoel_eur", STANDAARD_DALPOT_WINSTDOEL_EUR)),
        "dalpot_trail": float(gs.get("dalpot_trailing_pct", STANDAARD_DALPOT_TRAILING_PCT)),
        "dalpot_noodstop": float(gs.get("dalpot_noodstop_pct", STANDAARD_DALPOT_NOODSTOP_PCT)),
        "dalpot_herkoop": float(gs.get("dalpot_herkoop_uur", STANDAARD_DALPOT_HERKOOP_UUR)),
        "dalpot_uitgesloten": sorted(gs.get("dalpot_uitgesloten", STANDAARD_DALPOT_UITGESLOTEN)),
        "login_pogingen": MAX_LOGIN_POGINGEN,
        "login_lockout_min": LOGIN_LOCKOUT_SEC // 60,
        "donatie": {munt: adres for munt, adres in DONATIE_ADRESSEN.items() if adres},
    }
    return render_template("help.html", h=instellingen)


@app.route("/beheren/aanvullen", methods=["POST"])
def beheren_aanvullen():
    try:
        voer_alles_aanvullen_uit()
    except Exception as e:
        log_error("beheren_aanvullen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/afromen", methods=["POST"])
def beheren_afromen():
    try:
        voer_handmatige_oogst_uit(request.form.get("munt", ""))
    except Exception as e:
        log_error("beheren_afromen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/munt-toevoegen", methods=["POST"])
def beheren_munt_toevoegen():
    try:
        verwerk_munt_toevoegen(f"{request.form.get('munt', '')} {request.form.get('budget', '')}")
    except Exception as e:
        log_error("beheren_munt_toevoegen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/munt-verwijderen", methods=["POST"])
def beheren_munt_verwijderen():
    try:
        verwerk_munt_verwijderen(request.form.get("munt", ""))
    except Exception as e:
        log_error("beheren_munt_verwijderen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/budget-wijzigen", methods=["POST"])
def beheren_budget_wijzigen():
    try:
        verwerk_budget_wijziging(f"{request.form.get('munt', '')} {request.form.get('bedrag', '')}")
    except Exception as e:
        log_error("beheren_budget_wijzigen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/pot-storten", methods=["POST"])
def beheren_pot_storten():
    try:
        verwerk_pot_storten(request.form.get("bedrag", ""))
    except Exception as e:
        log_error("beheren_pot_storten", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/pot-opnemen", methods=["POST"])
def beheren_pot_opnemen():
    try:
        verwerk_pot_opnemen(request.form.get("bedrag", ""))
    except Exception as e:
        log_error("beheren_pot_opnemen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/pot-munt-toevoegen", methods=["POST"])
def beheren_pot_munt_toevoegen():
    try:
        verwerk_pot_munt_toevoegen(f"{request.form.get('munt', '')} {request.form.get('budget', '')}")
    except Exception as e:
        log_error("beheren_pot_munt_toevoegen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/pot-munt-verwijderen", methods=["POST"])
def beheren_pot_munt_verwijderen():
    try:
        verwerk_pot_munt_verwijderen(request.form.get("munt", ""))
    except Exception as e:
        log_error("beheren_pot_munt_verwijderen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/munt-uitsluiten", methods=["POST"])
def beheren_munt_uitsluiten():
    try:
        verwerk_pot_munt_uitsluiten(request.form.get("munt", ""))
    except Exception as e:
        log_error("beheren_munt_uitsluiten", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/pot-kies-nu", methods=["POST"])
def beheren_pot_kies_nu():
    try:
        kies_pot_munten(handmatig=True)
    except Exception as e:
        log_error("beheren_pot_kies_nu", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/pot-munt-budget-verhogen", methods=["POST"])
def beheren_pot_munt_budget_verhogen():
    try:
        verwerk_pot_munt_budget_verhogen(f"{request.form.get('munt', '')} {request.form.get('budget', '')}")
    except Exception as e:
        log_error("beheren_pot_munt_budget_verhogen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/pot-instellingen", methods=["POST"])
def beheren_pot_instellingen():
    try:
        wijzig_pot_instellingen(
            float(request.form.get("max_munten", 0) or 0),
            float(request.form.get("budget_per_munt", 0) or 0),
            float(request.form.get("winstdoel_eur", 0) or 0),
            float(request.form.get("trailing_pct", 0) or 0),
        )
    except Exception as e:
        log_error("beheren_pot_instellingen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/dalpot-storten", methods=["POST"])
def beheren_dalpot_storten():
    try:
        verwerk_dalpot_storten(request.form.get("bedrag", ""))
    except Exception as e:
        log_error("beheren_dalpot_storten", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/dalpot-opnemen", methods=["POST"])
def beheren_dalpot_opnemen():
    try:
        verwerk_dalpot_opnemen(request.form.get("bedrag", ""))
    except Exception as e:
        log_error("beheren_dalpot_opnemen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/dalpot-munt-toevoegen", methods=["POST"])
def beheren_dalpot_munt_toevoegen():
    try:
        verwerk_dalpot_munt_toevoegen(f"{request.form.get('munt', '')} {request.form.get('budget', '')}")
    except Exception as e:
        log_error("beheren_dalpot_munt_toevoegen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/dalpot-munt-verwijderen", methods=["POST"])
def beheren_dalpot_munt_verwijderen():
    try:
        verwerk_dalpot_munt_verwijderen(request.form.get("munt", ""))
    except Exception as e:
        log_error("beheren_dalpot_munt_verwijderen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/dalpot-munt-uitsluiten", methods=["POST"])
def beheren_dalpot_munt_uitsluiten():
    try:
        verwerk_dalpot_munt_uitsluiten(request.form.get("munt", ""))
    except Exception as e:
        log_error("beheren_dalpot_munt_uitsluiten", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/dalpot-kies-nu", methods=["POST"])
def beheren_dalpot_kies_nu():
    try:
        kies_dalpot_munten(handmatig=True)
    except Exception as e:
        log_error("beheren_dalpot_kies_nu", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/beheren/dalpot-instellingen", methods=["POST"])
def beheren_dalpot_instellingen():
    try:
        wijzig_dalpot_instellingen(
            float(request.form.get("max_munten", 0) or 0),
            float(request.form.get("budget_per_munt", 0) or 0),
            float(request.form.get("winstdoel_eur", 0) or 0),
            float(request.form.get("trailing_pct", 0) or 0),
        )
    except Exception as e:
        log_error("beheren_dalpot_instellingen", e)
    return redirect(url_for("beheren", verwerkt="1"))


@app.route("/sw.js")
def service_worker():
    """
    Dient de service worker vanaf de root i.p.v. /static/sw.js, zodat het
    bereik de hele site dekt (een worker onder /static/ zou alleen dat pad
    kunnen bedienen). Nodig om als installeerbare PWA herkend te worden.
    """
    resp = app.send_static_file("sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@app.route("/")
def dashboard():
    try:
        posities, vrij_cash, totaal_belegd = verzamel_posities()
        actieve_posities = [p for p in posities if p["actief"]]
        state = laad_state()
        btc_waarde = btc_reserve_waarde()
        pot = verzamel_pot()
        dalpot = verzamel_dalpot()
        portfolio_data = {
            "totaal": vrij_cash + totaal_belegd + btc_waarde + pot["belegd"] + dalpot["belegd"],
            "cash": handelscash(vrij_cash, state),
            "belegd": totaal_belegd,
            "reserve": btc_waarde,
            "reserves": reserve_waarden(),
            "gerealiseerd": gerealiseerd_totaal(state),
        }
        return render_template(
            "index.html", portfolio=portfolio_data, posities=actieve_posities, pot=pot, dalpot=dalpot
        )
    except Exception as e:
        log_error("dashboard_route", e)
        return "Fout bij laden van dashboard. Zie bot_errors.log.", 500


# ---------------------------------------------------------------------------
# Geschiedenis
#
# De bot bewaarde tot nu toe alleen de stand van nu. Voor een grafiek is een
# reeks nodig. Twee lagen, zodat het bestand klein blijft:
#   fijn : elke 5 minuten, 48 uur bewaard  -> de grafiek van vandaag
#   uur  : elk uur, 95 dagen bewaard       -> de maand en de drie maanden
# ---------------------------------------------------------------------------

HISTORIE_FILE = DATA_PREFIX + "bot_historie.json"
FIJN_INTERVAL = 300           # 5 minuten
FIJN_BEWAREN = 48 * 3600      # 48 uur
UUR_INTERVAL = 3600
# De uurreeks wordt nooit opgeruimd (voor de "Alles"-weergave in de grafiek).
# Blijft ook na jaren nog maar een paar honderd KB, dus geen reden om te snoeien.


def laad_historie():
    if os.path.exists(HISTORIE_FILE):
        try:
            with open(HISTORIE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("fijn", [])
                data.setdefault("uur", [])
                return data
        except Exception as e:
            log_error("laad_historie", e)
    return {"fijn": [], "uur": []}


def bewaar_historie(data):
    try:
        tijdelijk = HISTORIE_FILE + ".tmp"
        with open(tijdelijk, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tijdelijk, HISTORIE_FILE)
    except Exception as e:
        log_error("bewaar_historie", e)


def noteer_historie():
    """Zet de huidige stand weg. Doet niets als het nog te vroeg is."""
    try:
        data = laad_historie()
        nu = time.time()

        fijn = data["fijn"]
        if fijn and (nu - fijn[-1][0]) < FIJN_INTERVAL:
            return

        posities, vrij_cash, belegd = verzamel_posities()
        totaal = (
            vrij_cash + belegd + btc_reserve_waarde()
            + verzamel_pot()["belegd"] + verzamel_dalpot()["belegd"]
        )
        punt = [round(nu), round(totaal, 2), round(vrij_cash, 2), round(belegd, 2)]

        fijn.append(punt)
        data["fijn"] = [p for p in fijn if nu - p[0] <= FIJN_BEWAREN]

        uur = data["uur"]
        if not uur or (nu - uur[-1][0]) >= UUR_INTERVAL:
            uur.append(punt)
            data["uur"] = uur

        bewaar_historie(data)
    except Exception as e:
        log_error("noteer_historie", e)


def historie_punten(bereik):
    """Geeft de punten voor een bereik, teruggedund tot iets wat vlot tekent."""
    data = laad_historie()
    nu = time.time()

    if bereik == "dag":
        ruw = [p for p in data["fijn"] if nu - p[0] <= 24 * 3600]
        # valt de fijne reeks tegen, vul aan met de uurreeks van vandaag
        if len(ruw) < 3:
            ruw = [p for p in data["uur"] if nu - p[0] <= 24 * 3600] or ruw
    elif bereik == "kwartaal":
        ruw = [p for p in data["uur"] if nu - p[0] <= 90 * 24 * 3600]
    elif bereik == "alles":
        ruw = data["uur"]
    else:
        ruw = [p for p in data["uur"] if nu - p[0] <= 30 * 24 * 3600]

    MAX_PUNTEN = 240
    if len(ruw) > MAX_PUNTEN:
        stap = len(ruw) / float(MAX_PUNTEN)
        gedund = [ruw[int(i * stap)] for i in range(MAX_PUNTEN)]
        if gedund[-1] != ruw[-1]:
            gedund.append(ruw[-1])       # laatste stand hoort er altijd bij
        ruw = gedund

    return [{"t": p[0], "totaal": p[1], "cash": p[2], "belegd": p[3]} for p in ruw]


@app.route("/api/historie")
def api_historie():
    """Punten voor de grafiek. bereik = dag, maand, kwartaal of alles."""
    try:
        bereik = request.args.get("bereik", "dag")
        if bereik not in ("dag", "maand", "kwartaal", "alles"):
            bereik = "dag"
        return jsonify({"bereik": bereik, "punten": historie_punten(bereik)})
    except Exception as e:
        log_error("api_historie", e)
        return jsonify({"fout": "Geschiedenis ophalen mislukt."}), 500


@app.route("/api/trades")
def api_trades():
    """Laatste koop/verkoopacties, voor de aparte activiteitenpagina."""
    try:
        limiet = min(max(request.args.get("limiet", 20, type=int) or 20, 1), 200)
        return jsonify({"trades": recente_trades(limiet)})
    except Exception as e:
        log_error("api_trades", e)
        return jsonify({"fout": "Activiteit ophalen mislukt."}), 500


def _oogst_trades():
    """Verkooporders die winst realiseren — dus geen BTC-aankopen, dat is
    een omzetting, geen nieuwe winst."""
    if trades_tabel is None:
        return []
    return [t for t in trades_tabel.all() if t.get("kant") == "verkoop" and t.get("bron") != "reserve-btc"]


def _periode_start(bereik, nu):
    vandaag = nu.replace(hour=0, minute=0, second=0, microsecond=0)
    if bereik == "dag":
        return vandaag
    if bereik == "week":
        return vandaag - timedelta(days=vandaag.weekday())
    if bereik == "maand":
        return vandaag.replace(day=1)
    return None  # alles: geen ondergrens


def bereken_rendement(bereik):
    """
    Zet het orderlogboek om in een winstoverzicht per periode: totaal
    geoogst, aantal oogsten, gemiddelde, betaalde fees, naar de reserve omgezet,
    een reeks per dag (of per maand bij "alles") en de best presterende
    munten. Alles hier is afgeleid van bestaande orders, er wordt niets
    nieuws bijgehouden.
    """
    nu = nu_nl()
    start = _periode_start(bereik, nu)

    def tijd_van(t):
        try:
            return parse_tijd_utc(t["tijd"]).astimezone(NL_TZ)
        except Exception:
            return None

    def in_periode(t):
        if start is None:
            return True
        tijd = tijd_van(t)
        return tijd is not None and tijd >= start

    alle_trades = trades_tabel.all() if trades_tabel is not None else []
    alle_trades_periode = [t for t in alle_trades if in_periode(t)]
    oogsten = [t for t in alle_trades_periode if t.get("kant") == "verkoop" and t.get("bron") != "reserve-btc"]
    btc_aankopen = [t for t in alle_trades_periode if t.get("bron") == "reserve-btc"]

    totaal_winst = round(sum(t.get("bedrag", 0.0) for t in oogsten), 2)
    aantal = len(oogsten)
    gemiddelde = round(totaal_winst / aantal, 2) if aantal else 0.0
    totaal_fees = round(sum(t.get("fee", 0.0) for t in alle_trades_periode), 2)
    naar_btc = round(sum(t.get("bedrag", 0.0) for t in btc_aankopen), 2)

    per_maand = bereik == "alles"
    reeks_dict = {}
    for t in oogsten:
        tijd = tijd_van(t)
        if tijd is None:
            continue
        sleutel = tijd.strftime("%Y-%m") if per_maand else tijd.strftime("%Y-%m-%d")
        rij = reeks_dict.setdefault(sleutel, {"winst": 0.0, "aantal": 0})
        rij["winst"] += t.get("bedrag", 0.0)
        rij["aantal"] += 1
    reeks = [
        {"periode": k, "winst": round(v["winst"], 2), "aantal": v["aantal"]}
        for k, v in sorted(reeks_dict.items())
    ]

    top_dict = {}
    for t in oogsten:
        munt = (t.get("munt") or "").replace("/EUR", "")
        rij = top_dict.setdefault(munt, {"winst": 0.0, "aantal": 0})
        rij["winst"] += t.get("bedrag", 0.0)
        rij["aantal"] += 1

    config = laad_config()
    actieve_munten = (
        set(config.get("coins", {}).keys())
        | set(config.get("pot_coins", {}).keys())
        | set(config.get("dalpot_coins", {}).keys())
    )

    # Bij "alles" ook actieve munten opnemen die nog nooit iets hebben
    # opgeleverd — anders zijn ze onzichtbaar, terwijl juist dat interessant
    # is om te zien: welke munt na weken nog niks doet, is een kandidaat om
    # te vervangen.
    if bereik == "alles":
        for munt in actieve_munten:
            top_dict.setdefault(munt, {"winst": 0.0, "aantal": 0})

    alle_top_munten = sorted(
        (
            {"munt": m, "winst": round(v["winst"], 2), "aantal": v["aantal"], "actief": m in actieve_munten}
            for m, v in top_dict.items()
        ),
        key=lambda r: r["winst"], reverse=True,
    )

    return {
        "bereik": bereik,
        "totaal_winst": totaal_winst,
        "aantal_oogsten": aantal,
        "gemiddelde": gemiddelde,
        "totaal_fees": totaal_fees,
        "naar_btc": naar_btc,
        "reeks": reeks,
        "top_munten": alle_top_munten,
        "aantal_munten": len(alle_top_munten),
    }


@app.route("/api/rendement")
def api_rendement():
    """Winstoverzicht voor de Rendement-pagina. bereik = dag, week, maand of alles."""
    try:
        bereik = request.args.get("bereik", "week")
        if bereik not in ("dag", "week", "maand", "alles"):
            bereik = "week"
        return jsonify(bereken_rendement(bereik))
    except Exception as e:
        log_error("api_rendement", e)
        return jsonify({"fout": "Rendement ophalen mislukt."}), 500


@app.route("/rendement")
def rendement_pagina():
    return render_template("rendement.html")


@app.route("/potten")
def potten_pagina():
    return render_template("potten.html")


@app.route("/activiteit")
def activiteit_pagina():
    return render_template("activiteit.html")


@app.route("/api/data")
def api_data():
    """
    Levert dezelfde gegevens als de pagina, maar als JSON. Het dashboard haalt
    dit elke paar seconden op in plaats van de hele pagina te herladen.
    """
    try:
        posities, vrij_cash, totaal_belegd = verzamel_posities()
        state = laad_state()
        btc_waarde = btc_reserve_waarde()
        pot = verzamel_pot()
        dalpot = verzamel_dalpot()
        return jsonify({
            "tijd": nu_nl().strftime("%H:%M:%S"),
            "bot_actief": BOT_ACTIVE,
            "portfolio": {
                "totaal": vrij_cash + totaal_belegd + btc_waarde + pot["belegd"] + dalpot["belegd"],
                "cash": handelscash(vrij_cash, state),
                "belegd": totaal_belegd,
                "reserve": btc_waarde,
                "reserves": reserve_waarden(),
                "gerealiseerd": gerealiseerd_totaal(state),
            },
            "posities": [p for p in posities if p["actief"]],
            "pot": pot,
            "dalpot": dalpot,
        })
    except Exception as e:
        log_error("api_data", e)
        return jsonify({"fout": "Gegevens ophalen mislukt."}), 500


def run_flask():
    # threaded=True: zonder dit verwerkt de server maar één verzoek
    # tegelijk. Bij een dashboard dat elke 10s ververst, plus Telegram en
    # de Beheren-pagina die allemaal dezelfde poort delen, zorgde dat voor
    # merkbare vertraging zodra één verzoek iets langer duurde.
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, use_reloader=False, threaded=True)


# ---------------------------------------------------------------------------
# Opstarten
# ---------------------------------------------------------------------------

def main():
    if not DEMO_MODUS and (not BITVAVO_KEY or not BITVAVO_SECRET):
        raise SystemExit("BITVAVO_API_KEY of BITVAVO_API_SECRET ontbreekt in .env (of zet DEMO_MODUS=1)")
    if len(DASHBOARD_TOKEN) < 16:
        raise SystemExit(
            "DASHBOARD_TOKEN ontbreekt of is te kort (minimaal 16 tekens) in .env. "
            "Maak er een met: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    # Marktlijst eenmalig laden. Nodig voor precisie en minimumcontroles.
    exchange.load_markets()

    global trades_tabel
    trades_tabel = db.table("trades")

    # Startdatum vastleggen, zodat je later weet over welke periode je meet
    state = laad_state()
    if not state.get("gestart"):
        state["gestart"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        bewaar_state(state)

    config = laad_config()
    poll_interval = float(config.get("global_settings", {}).get("poll_interval_seconds", 10))

    # Reservemunten horen in geen enkele lijst (zie is_reserve_munt). Stonden
    # ze er al in van vóór deze controle, dan alleen waarschuwen: niets
    # automatisch verwijderen, dat is aan de gebruiker.
    for lijst, naam in (("coins", "hoofdlijst"), ("pot_coins", "pot"), ("dalpot_coins", "dalpot")):
        dubbel = [c for c in config.get(lijst, {}) if is_reserve_munt(c)]
        if dubbel:
            log_info(f"Reservemunt(en) {dubbel} staan ook in de {naam}.")
            send_telegram_message(
                f"⚠️ *{', '.join(dubbel)}* staat in de {naam}, maar is ook een reservemunt. "
                f"De bot telt dat saldo dan dubbel en kan reserve als winst verkopen. "
                f"Verwijder {', '.join(dubbel)} uit de {naam}.",
                include_keyboard=True,
            )

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=telegram_loop, daemon=True).start()
    threading.Thread(target=icoon_loop, daemon=True).start()
    threading.Thread(target=parameter_loop, daemon=True).start()
    threading.Thread(target=pot_kies_loop, daemon=True).start()
    threading.Thread(target=dalpot_kies_loop, daemon=True).start()
    threading.Thread(target=markten_ververs_loop, daemon=True).start()

    demo_regel = ""
    if DEMO_MODUS:
        demo_regel = f"🧪 *Demo-modus*: nep-saldo, echte koersen, geen echte orders.\n\n"
        print(f"DEMO-MODUS actief. Nep-saldo in {DemoExchange.SALDO_FILE}, data in demo_*.json")
    print(f"Profit Harvester V5.7 gestart. Dashboard op http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    send_telegram_message(
        f"🤖 *Profit Harvester V5.7 Live!* 🚀\n\n"
        f"{demo_regel}"
        f"🌐 Dashboard: `{DASHBOARD_HOST}:{DASHBOARD_PORT}`\n"
        f"⏱️ Check interval: `{poll_interval:.0f}s`\n"
        f"💎 Afgeroomd naar {reserve_naam()}: {euro(btc_reserve_waarde())}\n"
        f"🧪 Pot cash: {euro(laad_state().get('pot_cash_eur', 0.0))}\n\n"
        f"_Hoofdlijst: verkopen automatisch, kopen alleen op jouw knop.\n"
        f"Pot: koopt en verkoopt zelf, binnen zijn eigen grenzen._",
        include_keyboard=True,
    )

    # Uit bot_state.json lezen i.p.v. altijd leeg beginnen — anders denkt de
    # bot na elke herstart dat hij nog niet gemaild heeft, en stuurt hij
    # meteen opnieuw een rapport als het al na 20:00 is. Dat gebeurde de
    # hele avond bij elke deploy.
    laatst_gemaild_datum = laad_state().get("laatst_gemaild_datum", "")

    while True:
        try:
            check_portfolio()
            check_pot_kopen()
            noteer_historie()

            nu = nu_nl()
            vandaag_str = nu.strftime("%Y-%m-%d")
            # Vergelijking op uur, niet op minuut. Anders wordt de mail gemist
            # wanneer de loop net niet op minuut 0 landt. Nederlandse tijd,
            # niet de UTC-klok van de container — anders mailt hij om 22:00.
            if nu.hour >= 20 and laatst_gemaild_datum != vandaag_str:
                stuur_email_rapport()
                laatst_gemaild_datum = vandaag_str
                state = laad_state()
                state["laatst_gemaild_datum"] = vandaag_str
                bewaar_state(state)

        except Exception as e:
            log_error("hoofdloop", e)

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
