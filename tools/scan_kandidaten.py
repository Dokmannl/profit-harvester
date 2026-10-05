import sys, time
sys.path.insert(0, "/app")
import bot

config = bot.laad_config()
hoofdlijst = set(config.get("coins", {}).keys())
potlijst = set(config.get("pot_coins", {}).keys())
uitgesloten = set(config.get("global_settings", {}).get("pot_uitgesloten", []))
al_gevolgd = hoofdlijst | potlijst | uitgesloten

tickers = bot.cache.tickers()
balans = bot.cache.balans(force=True)

MIN_VOLUME = 1_000_000.0

kandidaten = []
for market, ticker in tickers.items():
    if not market.endswith("/EUR"):
        continue
    coin = market[:-4]
    if coin in al_gevolgd or coin == "EUR":
        continue
    bestaand = balans["total"].get(coin, 0.0)
    if bestaand > 0:
        prijs = ticker.get("last") or 0.0
        if bestaand * prijs > 1.0:
            continue
    volume = ticker.get("quoteVolume") or 0.0
    if volume < MIN_VOLUME:
        continue
    kandidaten.append((coin, market, volume))

kandidaten.sort(key=lambda x: -x[2])
kandidaten = kandidaten[:25]  # alleen de meest liquide checken, scheelt tijd

print(f"{len(kandidaten)} kandidaten met genoeg omzet, dagbeweging aan het meten...\n")
resultaat = []
for coin, market, volume in kandidaten:
    atr = bot.meet_volatiliteit(market)
    time.sleep(0.25)
    if atr is None:
        continue
    prijs = bot.koers_van(tickers, market) or 0.0
    resultaat.append((coin, volume, atr, prijs))

resultaat.sort(key=lambda x: -x[1])
print(f"{'munt':<8}{'24u omzet':>14}  {'dagrange%':>10}  {'koers':>12}")
for coin, volume, atr, prijs in resultaat:
    print(f"{coin:<8}{volume:>14,.0f}  {atr:>9.1f}%  {prijs:>12.4f}")
