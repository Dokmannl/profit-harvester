import sys
sys.path.insert(0, "/app")
import bot

config = bot.laad_config()
hoofdlijst_coins = set(config.get("coins", {}).keys())
pot_coins = set(config.get("pot_coins", {}).keys())

balans = bot.cache.balans(force=True)
tickers = bot.cache.tickers()

vrij_eur = balans["free"].get("EUR", 0.0)

echte_totaal = vrij_eur
regels = []
for munt, aantal in balans["total"].items():
    if munt == "EUR" or not aantal:
        continue
    market = f"{munt}/EUR"
    koers = bot.koers_van(tickers, market) or 0.0
    waarde = aantal * koers
    echte_totaal += waarde
    getrackt = "hoofdlijst" if munt in hoofdlijst_coins else ("pot" if munt in pot_coins else ("BTC" if munt == "BTC" else "NIET GETRACKT"))
    regels.append((munt, aantal, koers, waarde, getrackt))

regels.sort(key=lambda r: -r[3])
print(f"{'munt':<8}{'aantal':>16}  {'koers':>10}  {'waarde':>10}  status")
for munt, aantal, koers, waarde, status in regels:
    print(f"{munt:<8}{aantal:>16.6f}  {koers:>10.4f}  {waarde:>10.2f}  {status}")

print()
print("Vrije EUR:", round(vrij_eur, 2))
print("Echte totaal (alle assets):", round(echte_totaal, 2))

# Wat de bot nu berekent
posities, vrij_cash, totaal_belegd = bot.verzamel_posities()
btc_waarde = bot.btc_reserve_waarde()
pot = bot.verzamel_pot()
bot_totaal = vrij_cash + totaal_belegd + btc_waarde + pot["belegd"]
print()
print("Bot 'Totale waarde':", round(bot_totaal, 2))
print("Verschil (echt - bot):", round(echte_totaal - bot_totaal, 2))

niet_getrackt_waarde = sum(r[3] for r in regels if r[4] == "NIET GETRACKT")
print("Waarde niet-getrackte munten (dust):", round(niet_getrackt_waarde, 2))
